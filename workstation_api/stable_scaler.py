"""Numerically stable finite, weighted, train-only feature scaling."""
import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin


class StableWeightedScaler(TransformerMixin, BaseEstimator):
    def fit(self, X, y=None, sample_weight=None):
        x=np.asarray(X,dtype=np.float64)
        if x.ndim!=2 or len(x)==0 or not np.isfinite(x).all():
            raise ValueError("Feature scaling requires nonempty finite numeric rows")
        w=np.ones(len(x)) if sample_weight is None else np.asarray(sample_weight,dtype=np.float64)
        if w.shape!=(len(x),) or not np.isfinite(w).all() or np.any(w<0) or w.sum()<=0:
            raise ValueError("Invalid feature weights")
        w=w/w.sum()
        # Center relative to an observed reference before estimating variance.
        # Direct E[x^2]-E[x]^2 is unstable on near-constant columns.
        self.reference_=x[0].copy()
        offset=x-self.reference_
        self.offset_mean_=np.sum(offset*w[:,None],axis=0)
        centered=offset-self.offset_mean_
        self.var_=np.sum(centered*centered*w[:,None],axis=0)
        if not np.isfinite(self.var_).all():
            raise ValueError("Feature variance outside finite numeric range")
        scale=np.sqrt(self.var_)
        tolerance=8*np.finfo(np.float64).eps*np.maximum(1.,np.max(np.abs(x),axis=0))
        self.scale_=np.where(scale<=tolerance,1.,scale)
        self.n_features_in_=x.shape[1]
        return self

    def transform(self, X):
        x=np.asarray(X,dtype=np.float64)
        if x.ndim!=2 or x.shape[1]!=self.n_features_in_ or not np.isfinite(x).all():
            raise ValueError("Invalid feature matrix")
        z=((x-self.reference_)-self.offset_mean_)/self.scale_
        if not np.isfinite(z).all():
            raise ValueError("Scaled features outside finite numeric range")
        return z
