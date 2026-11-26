"""Additional historical alpha comparisons. No live promotion or order actions."""
from collections import defaultdict
from datetime import timedelta
import importlib.util
import math
import numpy as np
from scipy.special import logsumexp

from . import constituent_alpha as a

VERSION="fitted_alpha_v1"
STATES=3
EM_STEPS=15


def _matrix(rows):
    # Common prior-window index return/volatility features. No labels,
    # forecast targets, future bars or target-session scaling.
    return np.asarray([r["index"][:4] for r in rows],dtype=float)


def _groups(rows,horizon):
    expected=timedelta(minutes=horizon+1)
    groups=[];current=[];previous=None
    for i,row in enumerate(rows):
        t=a._stamp(row["decision_utc"])
        if previous is not None and (row["session"]!=rows[previous]["session"] or
                                     t-a._stamp(rows[previous]["decision_utc"])!=expected):
            if current:groups.append(current)
            current=[]
        current.append(i);previous=i
    if current:groups.append(current)
    return groups


def _emission(x,means,variances):
    return -.5*np.sum(np.log(2*np.pi*variances)[None,:,:]+
                (x[:,None,:]-means[None,:,:])**2/variances[None,:,:],axis=2)


def _forward(logp,initial,transition):
    logt=np.log(np.maximum(transition,1e-12))
    filt=np.empty_like(logp)
    filt[0]=np.log(np.maximum(initial,1e-12))+logp[0]
    filt[0]-=logsumexp(filt[0])
    for j in range(1,len(logp)):
        filt[j]=logp[j]+logsumexp(filt[j-1,:,None]+logt,axis=0)
        filt[j]-=logsumexp(filt[j])
    return filt


def _fit_regimes(train,horizon):
    from sklearn.mixture import GaussianMixture
    from sklearn.preprocessing import StandardScaler
    from threadpoolctl import threadpool_limits
    scaler=StandardScaler().fit(_matrix(train))
    x=scaler.transform(_matrix(train))
    with threadpool_limits(limits=1):
        gmm=GaussianMixture(n_components=STATES,covariance_type="diag",reg_covar=1e-3,
                            max_iter=100,random_state=419,n_init=2).fit(x)
    if not gmm.converged_:
        raise ValueError("Gaussian mixture failed to converge")
    model={"scaler":scaler,"gmm":gmm,"hmm":None}
    groups=_groups(train,horizon)
    if horizon==0 or sum(len(g)-1 for g in groups)<30:
        return model
    means=gmm.means_.copy();variances=np.maximum(gmm.covariances_.copy(),1e-3)
    initial=gmm.weights_.copy()
    transition=np.full((STATES,STATES),.1);np.fill_diagonal(transition,.8)
    for _ in range(EM_STEPS):
        initial_count=np.ones(STATES)*.1
        transitions=np.ones((STATES,STATES))*.1
        weights=np.zeros(STATES);weighted=np.zeros_like(means);squares=np.zeros_like(means)
        logt=np.log(np.maximum(transition,1e-12))
        for group in groups:
            y=x[group];logp=_emission(y,means,variances)
            forward=_forward(logp,initial,transition)
            backward=np.zeros_like(logp)
            for t in range(len(y)-2,-1,-1):
                backward[t]=logsumexp(logt+logp[t+1,None,:]+backward[t+1,None,:],axis=1)
                backward[t]-=logsumexp(backward[t])
            loggamma=forward+backward
            gamma=np.exp(loggamma-logsumexp(loggamma,axis=1,keepdims=True))
            initial_count+=gamma[0]
            for t in range(len(y)-1):
                xi=forward[t,:,None]+logt+logp[t+1,None,:]+backward[t+1,None,:]
                transitions+=np.exp(xi-logsumexp(xi))
            weights+=gamma.sum(axis=0);weighted+=gamma.T@y;squares+=gamma.T@(y*y)
        if min(weights)<1e-4:
            return model
        means=weighted/weights[:,None]
        variances=np.maximum(squares/weights[:,None]-means*means,1e-3)
        initial=initial_count/initial_count.sum()
        transition=transitions/transitions.sum(axis=1,keepdims=True)
    if all(np.all(np.isfinite(v)) for v in (means,variances,initial,transition)):
        model["hmm"]={"means":means,"variances":variances,"initial":initial,"transition":transition}
    return model


def _probabilities(model,rows,horizon,kind):
    x=model["scaler"].transform(_matrix(rows))
    if kind=="gmm":
        return model["gmm"].predict_proba(x)
    params=model["hmm"]
    probs=np.empty((len(rows),STATES))
    for group in _groups(rows,horizon):
        # Only a forward filter on calibration/holdout. No retrospective
        # Viterbi or backward smoothing of hidden states.
        logp=_emission(x[group],params["means"],params["variances"])
        probs[group]=np.exp(_forward(logp,params["initial"],params["transition"]))
    return probs


def _augment(model,rows,horizon,kind):
    probs=_probabilities(model,rows,horizon,kind)
    return [{**r,"full":r["full"]+list(v)} for r,v in zip(rows,probs)]


def _optional_fit(kind,train,cal,test):
    # Optional packages must actually be installed. No silent substitution.
    from threadpoolctl import threadpool_limits
    if importlib.util.find_spec(kind) is None:
        return None,"optional_dependency_missing"
    x=np.asarray([r["full"] for r in train])
    y=np.asarray([r["class"]+1 for r in train])
    try:
        if kind=="lightgbm":
            from lightgbm import LGBMClassifier
            model=LGBMClassifier(objective="multiclass",n_estimators=100,num_leaves=7,
                min_child_samples=20,learning_rate=.05,reg_lambda=1.,random_state=419,
                n_jobs=1,verbosity=-1)
        else:
            from xgboost import XGBClassifier
            model=XGBClassifier(objective="multi:softprob",num_class=3,n_estimators=100,
                max_depth=2,min_child_weight=5,learning_rate=.05,reg_lambda=1.,
                random_state=419,n_jobs=1,tree_method="hist",verbosity=0)
        with threadpool_limits(limits=1):
            model.fit(x,y)
            if tuple(model.classes_)!=(0,1,2):
                return None,"incomplete_class_support"
            pc=model.predict_proba(np.asarray([r["full"] for r in cal]))
            pt=model.predict_proba(np.asarray([r["full"] for r in test]))
        return (pc,pt),"fitted"
    except (ImportError,OSError,ValueError,RuntimeError):
        return None,"optional_model_unavailable"


def assess(train,cal,test,horizon,baseline,progress=None):
    methods={};records=[];states={};predictions={}
    if progress:progress(87,"Fitting training-only Gaussian mixture and Markov regimes")
    try:
        model=_fit_regimes(train,horizon)
        for kind in ("gmm","hmm"):
            name="constituent_"+kind+"_logistic"
            if kind=="hmm" and model["hmm"] is None:
                states[name]="insufficient_contiguous_training_windows";continue
            fitted=a._fit("constituent_logistic",_augment(model,train,horizon,kind))
            predictions[name]=(a._predict(fitted,_augment(model,cal,horizon,kind)),
                               a._predict(fitted,_augment(model,test,horizon,kind)))
            states[name]="fitted"
    except (ValueError,RuntimeError,FloatingPointError,np.linalg.LinAlgError):
        states.setdefault("constituent_gmm_logistic","fit_unavailable")
        states.setdefault("constituent_hmm_logistic","fit_unavailable")
    for kind in ("lightgbm","xgboost"):
        if progress:progress(90,"Checking optional "+kind+" model")
        prediction,state=_optional_fit(kind,train,cal,test)
        name="constituent_"+kind
        states[name]=state
        if prediction is not None:predictions[name]=prediction
    for name,(pc,pt) in predictions.items():
        temperature=a._calibrate(pc,cal)
        probs=a._temperature(pt,temperature)
        calls=[a._call(v) for v in probs]
        item=a._directional_stats(test,calls,probs)
        prior=baseline["training_class_prior"]["brier"]
        index=baseline["index_logistic"]["brier"]
        constituent=baseline["constituent_logistic"]["brier"]
        item.update(temperature=temperature,
            brier_skill_vs_prior=1-item["brier"]/prior if prior>0 else None,
            brier_skill_vs_index_logistic=1-item["brier"]/index if index>0 else None,
            brier_skill_vs_constituent_logistic=1-item["brier"]/constituent if constituent>0 else None,
            descriptive_gate_passed=bool(item["brier"]<min(prior,index,constituent) and item["directional_calls"]>=20
                and item["call_sessions"]>=10 and item["mean_net_index_proxy_bps"] is not None and item["mean_net_index_proxy_bps"]>0))
        methods[name]=item
        for r,pr,call in zip(test,probs,calls):
            records.append({"method":name,"session":r["session"],"decision_utc":r["decision_utc"],
                "target_utc":r["target_utc"],"regime":r["regime"],"reference_price":r["reference_price"],
                "actual_return_bps":r["return_bps"],"actual_class":r["class"],"call":call,
                "p_down":pr[0],"p_flat":pr[1],"p_up":pr[2],
                "net_index_proxy_bps":call*r["return_bps"]-a.COST_BPS if call else 0.,
                "q10_bps":None,"q50_bps":None,"q90_bps":None})
    return methods,states,records
