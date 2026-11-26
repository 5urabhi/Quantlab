"""Process-local notification of committed original market observations.

Only a generation counter is shared. No strategy work runs in a recorder
callback. Consumers also poll for receipts committed by other processes.
"""
from threading import Lock

_LOCK=Lock()
_generation=0


def publish():
    global _generation
    with _LOCK:
        _generation+=1


def generation():
    with _LOCK:
        return _generation
