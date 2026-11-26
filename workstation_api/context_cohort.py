"""Forward context cohort registry. A registered cohort cannot be reset in UI."""
from contextlib import closing
from datetime import timedelta
from hashlib import sha256
import json
import sqlite3
from . import constituent_alpha as a, constituent_prospective as p, shared_market_data, replay_storage

TABLE="alpha_context_cohorts"

def _setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS alpha_context_cohorts(
        scope TEXT NOT NULL,horizon INTEGER NOT NULL,policy_hash TEXT NOT NULL,
        registered_utc TEXT NOT NULL,start_session TEXT NOT NULL,cohort_id TEXT NOT NULL,
        PRIMARY KEY(scope,horizon,policy_hash))""")

def _identity(scope,horizon):
    from . import context_alpha
    if scope not in context_alpha.SCOPES or horizon not in a.HORIZONS:
        raise ValueError("Select a supported context scope and original ledger horizon")
    return context_alpha.policy_for(horizon)

def register(scope,horizon,confirm,*,now=None):
    if confirm is not True:
        raise ValueError("Confirm a forward-only context study; the start date cannot be reset")
    policy=_identity(scope,horizon)
    now=now or p._now()
    registered=p._iso(now)
    start=(p._session(now).date()+timedelta(days=1)).isoformat()
    ident=sha256(json.dumps([scope,horizon,policy,registered,start],separators=(",",":")).encode()).hexdigest()
    path=shared_market_data.database_path();path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path,timeout=8)) as db,db:
        _setup(db)
        db.execute("INSERT OR IGNORE INTO alpha_context_cohorts VALUES(?,?,?,?,?,?)",
                   (scope,horizon,policy,registered,start,ident))
    return get(scope,horizon)

def get(scope,horizon):
    policy=_identity(scope,horizon)
    if not shared_market_data.database_path().is_file():
        return None
    with closing(a._read()) as db:
        if not replay_storage.fetchone(db,"SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(TABLE,)):
            return None
        row=replay_storage.fetchone(db,"""SELECT scope,horizon,policy_hash,registered_utc,start_session,cohort_id
            FROM alpha_context_cohorts WHERE scope=? AND horizon=? AND policy_hash=?""",(scope,horizon,policy))
    if not row:
        return None
    keys=("scope","horizon","policy_hash","registered_utc","start_session","cohort_id")
    item=dict(zip(keys,row))
    expected=sha256(json.dumps([scope,horizon,policy,item["registered_utc"],item["start_session"]],separators=(",",":")).encode()).hexdigest()
    if expected!=item["cohort_id"]:
        raise ValueError("Context cohort registration checksum mismatch")
    return item
