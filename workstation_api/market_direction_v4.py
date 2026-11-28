"""Dedicated direction network: optional lagged dynamic graph and soft experts.

Pretraining predicts instrument-specific movement, sign and excursions.
Fine-tuning only predicts conditional material sign; V3 stays independent.
No trade execution, fitted future information, or named regime guarantees.
"""
import torch
from torch import nn
from torch.nn import functional as F

from workstation_api.market_dynamics_v3 import MarketDynamicsV3,PATCH,LOCAL,SESSION,DAILY,HEADS,DROPOUT


def sign_loss(logits,target,mask,weights,gate=None):
    """Only observed non-flat horizons contribute; equal active horizon loss."""
    logits=logits.float();target=target.float()
    active=mask.bool()&(target.abs()>5.)
    w=weights.float()[:,None]*active
    label=(target>5.).float()
    raw=F.binary_cross_entropy_with_logits(logits,label,reduction="none")
    support=w.sum(dim=0)
    loss=((raw*w).sum(dim=0)/support.clamp_min(1.)*(support>0)).sum()/(support>0).sum().clamp_min(1)
    if gate is not None:
        # Soft routing, weak anti-collapse regularizer; no imposed regime label.
        mass=(gate.float()*w[:,:,None]).sum(dim=(0,1))/w.sum().clamp_min(1.)
        balance=(mass*torch.log((mass*gate.shape[-1]).clamp_min(1e-8))).sum()
        loss=loss+.01*balance
    return loss


class DirectionGraph(MarketDynamicsV3):
    def __init__(self,assets,channels,aux_channels,memory_channels,horizons,width=128,variant="graph_moe"):
        super().__init__(assets,channels,aux_channels,memory_channels,horizons,width)
        if variant not in ("plain","graph","graph_moe"):raise ValueError("Unknown V4 variant")
        self.variant=variant
        del self.primary
        if variant!="plain":
            self.graph=nn.MultiheadAttention(width,HEADS,dropout=DROPOUT,batch_first=True)
            self.graph_norm=nn.LayerNorm(width)
            self.lag=nn.Parameter(torch.zeros(1,1,1,width))
        self.experts=nn.ModuleList(nn.Sequential(nn.Linear(2*width,2*width),nn.GELU(),nn.Dropout(DROPOUT),
                                                nn.Linear(2*width,horizons))
                                   for _ in range(6 if variant=="graph_moe" else 1))
        if variant=="graph_moe":
            self.gate=nn.Sequential(nn.Linear(2*width,width),nn.GELU(),nn.Linear(width,horizons*6))

    def graph_tokens(self,tokens,observed):
        """Every observed stock queries same completed patch and past patch.

        Distinct previous-patch keys permit dynamic lagged relationships.
        No future patch key and no unobserved node can influence a valid query.
        """
        if self.variant=="plain":return tokens
        b,n,a,w=tokens.shape
        previous=torch.cat((torch.zeros_like(tokens[:,:1]),tokens[:,:-1]),dim=1)+self.lag
        past=torch.cat((torch.zeros_like(observed[:,:1]),observed[:,:-1]),dim=1)
        keys=torch.cat((tokens,previous),dim=2).reshape(b*n,2*a,w)
        valid=torch.cat((observed,past),dim=2).reshape(b*n,2*a)
        # One dummy key only if every real key is masked. Output masked below.
        mask=~valid;mask[:,0]&=valid.any(dim=1)
        query=tokens.reshape(b*n,a,w)
        z,_=self.graph(query,keys,keys,key_padding_mask=mask,need_weights=False)
        return self.graph_norm(query+z).reshape(b,n,a,w)*observed[:,:,:,None]

    def forward(self,x,aux,session,daily,session_valid,daily_valid,*,pretrain=False):
        b,t,a,c=x.shape;n=t//PATCH
        if (t,a,c)!=(LOCAL,self.assets,self.channels) or aux.shape!=(b,t,self.aux_channels):
            raise ValueError("Invalid V4 local input")
        if session.shape!=(b,SESSION,self.memory_channels) or daily.shape!=(b,DAILY,self.memory_channels):
            raise ValueError("Invalid V4 memory")
        patches=x.reshape(b,n,PATCH,a,c).permute(0,1,3,2,4)
        observed=patches[...,0].gt(0).any(dim=3)
        if not bool(observed[:,-1,0].all()):raise ValueError("Missing index decision")
        tokens=self.patch(patches.reshape(b,n,a,PATCH*c))+self.identity
        tokens=self.graph_tokens(tokens,observed)
        keys=tokens.reshape(b*n,a,self.width)
        key_mask=~observed.reshape(b*n,a);key_mask[:,0]&=observed.reshape(b*n,a).any(dim=1)
        query=keys[:,:1]
        for attention,norm in zip(self.cross,self.cross_norm):
            z,_=attention(query,keys,keys,key_padding_mask=key_mask,need_weights=False)
            query=norm(query+z)
        local=query.reshape(b,n,self.width);valid=observed[:,:,0]
        combined=torch.cat((local,self.aux(aux.reshape(b,n,PATCH*self.aux_channels))),dim=-1)
        with torch.autocast(device_type=x.device.type,enabled=False):
            recurrent,_=self.gru((combined*valid[:,:,None]).float())
        supported=torch.cat((daily_valid,session_valid,valid),dim=1)
        all_tokens=torch.cat((self.daily(daily),self.session(session),recurrent),dim=1)
        encoded=self.temporal((all_tokens+self.position)*supported[:,:,None],src_key_padding_mask=~supported)
        last=encoded[:,-1]
        average=(encoded*supported[:,:,None]).sum(dim=1)/supported.sum(dim=1,keepdim=True).clamp_min(1)
        if pretrain:
            per_asset=(tokens*observed[:,:,:,None]).sum(dim=1)/observed.sum(dim=1)[:,:,None].clamp_min(1)
            context=last[:,None,:].expand(-1,a,-1)
            return self.pretrain_head(torch.cat((per_asset,context),dim=-1)).reshape(b,a,2,5)
        state=torch.cat((last,average),dim=-1)
        scores=torch.stack([expert(state).float() for expert in self.experts],dim=-1)
        if self.variant!="graph_moe":return scores[...,0],None
        weights=self.gate(state).reshape(b,self.horizons,6).float().softmax(dim=-1)
        p=(scores.sigmoid()*weights).sum(dim=-1).clamp(1e-6,1-1e-6)
        return torch.logit(p),weights
