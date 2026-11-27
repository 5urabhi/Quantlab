"""MarketDynamics V3: hierarchical multi-asset temporal representation.

No market-data IO, orders, or pretrained external model. All sequences end
at the decision; daily tokens describe only earlier observed sessions.
"""
import torch
from torch import nn
from torch.nn import functional as F

PATCH=5
LOCAL=30
SESSION=25
DAILY=60
HEADS=8
DROPOUT=.15


def distribution(raw):
    """Two factorized Bernoulli heads plus coherent three-value regression."""
    raw=raw.float()
    move=raw[...,0];sign=raw[...,1]
    lp=torch.stack((F.logsigmoid(move)+F.logsigmoid(-sign),
                    F.logsigmoid(-move),
                    F.logsigmoid(move)+F.logsigmoid(sign)),dim=-1)
    ret=raw[...,2:3]
    exc=F.softplus(raw[...,3:5])+torch.cat((F.relu(ret),F.relu(-ret)),dim=-1)
    return lp,torch.cat((ret,exc),dim=-1)


def factorized_loss(raw,target,mask,weights):
    """Explicit conditional sign objective; flat labels never train sign."""
    raw=raw.float();target=target.float();mask=mask.float()
    material=(target[...,0].abs()>.5).float()
    positive=(target[...,0]>.5).float()
    shape=(len(weights),)+(1,)*(mask.ndim-1)
    w=weights.float().reshape(shape)*mask
    # Normalize within the observed batch, separately for material sign.
    move=F.binary_cross_entropy_with_logits(raw[...,0],material,reduction="none")
    sign=F.binary_cross_entropy_with_logits(raw[...,1],positive,reduction="none")
    _,reg=distribution(raw)
    magnitude=F.smooth_l1_loss(reg,target,reduction="none").mean(dim=-1)
    return ((move*w).sum()/w.sum().clamp_min(1)+
            (sign*w*material).sum()/(w*material).sum().clamp_min(1)+
            .25*(magnitude*w).sum()/w.sum().clamp_min(1))


class MarketDynamicsV3(nn.Module):
    def __init__(self,assets,channels,aux_channels,memory_channels,horizons=6,width=128):
        super().__init__()
        if min(assets,channels,aux_channels,memory_channels,horizons)<1 or width%HEADS:
            raise ValueError("Invalid V3 dimensions")
        self.assets=assets;self.channels=channels;self.aux_channels=aux_channels
        self.memory_channels=memory_channels;self.width=width;self.horizons=horizons
        self.patch=nn.Sequential(nn.Linear(PATCH*channels,width),nn.LayerNorm(width),nn.GELU())
        self.identity=nn.Parameter(torch.empty(1,1,assets,width));nn.init.normal_(self.identity,std=.02)
        self.cross=nn.ModuleList(nn.MultiheadAttention(width,HEADS,dropout=DROPOUT,batch_first=True) for _ in range(2))
        self.cross_norm=nn.ModuleList(nn.LayerNorm(width) for _ in range(2))
        self.aux=nn.Sequential(nn.Linear(PATCH*aux_channels,width),nn.LayerNorm(width),nn.GELU())
        self.gru=nn.GRU(2*width,width,num_layers=2,dropout=DROPOUT,batch_first=True)
        self.daily=nn.Sequential(nn.Linear(memory_channels,width),nn.LayerNorm(width),nn.GELU())
        self.session=nn.Sequential(nn.Linear(memory_channels,width),nn.LayerNorm(width),nn.GELU())
        self.position=nn.Parameter(torch.empty(1,DAILY+SESSION+LOCAL//PATCH,width))
        nn.init.normal_(self.position,std=.02)
        layer=nn.TransformerEncoderLayer(width,HEADS,dim_feedforward=2*width,
                    dropout=DROPOUT,activation="gelu",batch_first=True,norm_first=True)
        self.temporal=nn.TransformerEncoder(layer,num_layers=2,enable_nested_tensor=False)
        self.primary=nn.Sequential(nn.Linear(2*width,2*width),nn.GELU(),nn.Dropout(DROPOUT),
                                   nn.Linear(2*width,horizons*5))
        self.pretrain_head=nn.Sequential(nn.Linear(2*width,2*width),nn.GELU(),nn.Dropout(DROPOUT),
                                         nn.Linear(2*width,2*5))

    def forward(self,x,aux,session,daily,session_valid,daily_valid,*,pretrain=False):
        b,t,a,c=x.shape;n=t//PATCH
        if (t,a,c)!=(LOCAL,self.assets,self.channels) or aux.shape!=(b,t,self.aux_channels):
            raise ValueError("Invalid local V3 input")
        if session.shape!=(b,SESSION,self.memory_channels) or daily.shape!=(b,DAILY,self.memory_channels):
            raise ValueError("Invalid multiscale V3 input")
        if session_valid.shape!=(b,SESSION) or daily_valid.shape!=(b,DAILY):
            raise ValueError("Invalid multiscale masks")
        patches=x.reshape(b,n,PATCH,a,c).permute(0,1,3,2,4)
        observed=patches[...,0].gt(0).any(dim=3)
        if not bool(observed[:,-1,0].all()):raise ValueError("Missing target minute")
        tokens=self.patch(patches.reshape(b,n,a,PATCH*c))+self.identity
        keys=tokens.reshape(b*n,a,self.width)
        key_mask=~observed.reshape(b*n,a)
        key_mask[:,0]=False # guarantee a key even in padded/gapped patches
        query=keys[:,:1]
        for attention,norm in zip(self.cross,self.cross_norm):
            z,_=attention(query,keys,keys,key_padding_mask=key_mask,need_weights=False)
            query=norm(query+z)
        local=query.reshape(b,n,self.width)
        valid=observed[:,:,0]
        combined=torch.cat((local,self.aux(aux.reshape(b,n,PATCH*self.aux_channels))),dim=-1)
        # Keep cuDNN recurrent arithmetic in float32 even with BF16 projections.
        with torch.autocast(device_type=x.device.type,enabled=False):
            recurrent,_=self.gru((combined*valid[:,:,None]).float())
        all_tokens=torch.cat((self.daily(daily),self.session(session),recurrent),dim=1)
        supported=torch.cat((daily_valid,session_valid,valid),dim=1)
        all_tokens=(all_tokens+self.position)*supported[:,:,None]
        encoded=self.temporal(all_tokens,src_key_padding_mask=~supported)
        last=encoded[:,-1]
        average=(encoded*supported[:,:,None]).sum(dim=1)/supported.sum(dim=1,keepdim=True).clamp_min(1)
        global_state=torch.cat((last,average),dim=-1)
        if pretrain:
            # Shared instrument-specific local encoding plus contextual state.
            # Every observed instrument target contributes, not just BANKNIFTY.
            per_asset=(tokens*observed[:,:,:,None]).sum(dim=1)/observed.sum(dim=1)[:,:,None].clamp_min(1)
            context=last[:,None,:].expand(-1,a,-1)
            return self.pretrain_head(torch.cat((per_asset,context),dim=-1)).reshape(b,a,2,5)
        return self.primary(global_state).reshape(b,self.horizons,5)
