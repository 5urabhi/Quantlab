"""Compact optional PyTorch sequence models for numeric market observations.

All models share a patch encoder and BANKNIFTY-query cross-asset attention.
Only the temporal encoder changes. No pretrained language model, order API,
external download at import, or training inside the live workstation process.
"""
import torch
from torch import nn
from torch.nn import functional as F

MODEL_TYPES=("cnn","gru","transformer")
PATCH=5
WIDTH=32
HEADS=4
DROPOUT=.15
MAX_PATCHES=24


class MarketSequence(nn.Module):
    def __init__(self,kind,assets,channels,context_dim,width=WIDTH):
        super().__init__()
        if kind not in MODEL_TYPES or assets<1 or channels!=8 or context_dim<1 or width%HEADS:
            raise ValueError("Invalid market sequence architecture")
        self.kind=kind;self.assets=assets;self.width=width
        self.patch=nn.Sequential(nn.Linear(PATCH*channels,width),nn.LayerNorm(width),nn.GELU())
        self.asset_embedding=nn.Parameter(torch.empty(1,1,assets,width))
        nn.init.normal_(self.asset_embedding,std=.02)
        self.cross_asset=nn.MultiheadAttention(width,HEADS,dropout=DROPOUT,batch_first=True)
        self.cross_norm=nn.LayerNorm(width)
        self.position=nn.Parameter(torch.empty(1,MAX_PATCHES,width))
        nn.init.normal_(self.position,std=.02)
        if kind=="transformer":
            layer=nn.TransformerEncoderLayer(width,HEADS,dim_feedforward=2*width,
                    dropout=DROPOUT,activation="gelu",batch_first=True,norm_first=False)
            self.temporal=nn.TransformerEncoder(layer,num_layers=2,enable_nested_tensor=False)
        elif kind=="gru":
            self.temporal=nn.GRU(width,width,num_layers=1,batch_first=True)
        else:
            self.temporal=nn.Sequential(nn.Conv1d(width,width,3,padding=2,dilation=2),
                                        nn.GELU(),nn.Dropout(DROPOUT),
                                        nn.Conv1d(width,width,3,padding=1),nn.GELU())
        self.context=nn.Sequential(nn.Linear(context_dim,width),nn.LayerNorm(width),
                                   nn.GELU(),nn.Dropout(DROPOUT))
        self.join=nn.Sequential(nn.Linear(width*3,width*2),nn.LayerNorm(width*2),nn.GELU(),
                                nn.Dropout(DROPOUT),nn.Linear(width*2,13))

    def forward(self,x,context):
        # x: batch, chronological one-minute observations, instrument, channels.
        b,t,a,c=x.shape
        if a!=self.assets or c!=8 or t%PATCH or not PATCH<=t<=PATCH*MAX_PATCHES:
            raise ValueError("Invalid market sequence dimensions")
        n=t//PATCH
        # Preserve order of all five minutes within each patch, per asset.
        patches=x.reshape(b,n,PATCH,a,c).permute(0,1,3,2,4)
        observed=patches[...,6].gt(0).any(dim=3)
        # The target index is always complete; explicit guard avoids
        # fully-masked attention producing NaNs for malformed input.
        if not bool(observed[:,:,0].all()):raise ValueError("Target index patch missing")
        tokens=self.patch(patches.reshape(b,n,a,PATCH*c))+self.asset_embedding
        tokens=tokens.reshape(b*n,a,self.width)
        mask=~observed.reshape(b*n,a)
        query=tokens[:,:1]
        cross,_=self.cross_asset(query,tokens,tokens,key_padding_mask=mask,need_weights=False)
        sequence=self.cross_norm(query+cross).reshape(b,n,self.width)+self.position[:,-n:]
        if self.kind=="gru":
            sequence,_=self.temporal(sequence)
        elif self.kind=="cnn":
            # The entire sequence ends at decision time, so symmetric
            # padding within the observed window is not future leakage.
            sequence=self.temporal(sequence.transpose(1,2)).transpose(1,2)
        else:
            sequence=self.temporal(sequence)
        z=self.join(torch.cat((sequence[:,-1],sequence.mean(dim=1),self.context(context)),dim=1))
        candle=torch.cat((z[:,:2],F.softplus(z[:,2:4])),dim=1)
        # Nested directional thresholds: P(>=50) <= P(>=30) <= P(>=20).
        # Both tails are bounded by the corresponding direction probability.
        up=z[:,4:5]
        # Conditional probabilities of reaching increasingly large positive/
        # negative *closing* moves, not intrabar touches.
        pos=torch.sigmoid(z[:,7:10]).cumprod(dim=1)*torch.sigmoid(up)
        neg=torch.sigmoid(z[:,10:13]).cumprod(dim=1)*torch.sigmoid(-up)
        events=torch.cat((torch.sigmoid(up),pos,neg),dim=1)
        # Coherent quantile interval around the same central close estimate.
        low=candle[:,1]-F.softplus(z[:,5])
        high=candle[:,1]+F.softplus(z[:,6])
        return candle,events,torch.stack((low,high),dim=1)


def objective(output,y,event,weight):
    candle,prob,interval=output
    # Targets normalized by causal recent volatility; focus on close but
    # retain the four OHLC components, direction, move tails and quantiles.
    components=F.smooth_l1_loss(candle,y,reduction="none")
    candle_loss=(components*components.new_tensor([.25,2.,1.,1.])).sum(dim=1)/4.25
    event_loss=F.binary_cross_entropy(prob.clamp(1e-6,1-1e-6),event,reduction="none")
    event_loss=(event_loss[:,0]+event_loss[:,1:].mean(dim=1))/2
    error=y[:,1:2]-interval
    q=interval.new_tensor([.1,.9])
    quantile=torch.maximum(q*error,(q-1)*error).mean(dim=1)
    loss=candle_loss+.6*event_loss+.4*quantile
    # Weights are fixed across the training partition. Do not renormalize
    # each minibatch by its own sum (which would distort session weighting).
    return (loss*weight).mean()
