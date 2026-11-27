"""Dated regular NSE session boundaries for the supported research scope.

NSE/CMTR/74466 and NSE/FAOP/74467 (effective 2026-08-03);
NSE/CMTR/77355 and NSE/FAOP/77356 (effective 2026-12-07).
Not a holiday, special-session, or point-in-time listing calendar.
"""
from datetime import date, time

CAS_START=date(2026,8,3)
CAS_REVISION=date(2026,12,7)
OPEN_MINUTE=9*60+15
COMPARISON_MINUTES=375
BANK_POLICY="nse_bank_cash_cas_2026_v1"
BANK_CAS_SYMBOLS=frozenset({
    "AUBANK","AXISBANK","BANKBARODA","CANBK","FEDERALBNK","HDFCBANK",
    "ICICIBANK","IDFCFIRSTB","INDUSINDBK","KOTAKBANK","PNB","SBIN",
    "UNIONBANK","YESBANK",
})


def cash_bank_minutes(day,identity,symbol):
    if isinstance(day,str):
        day=date.fromisoformat(day)
    if identity.startswith("NSE_EQ:") and symbol in BANK_CAS_SYMBOLS and CAS_START<=day<CAS_REVISION:
        return 360
    return COMPARISON_MINUTES


def derivatives_segment_minutes(day):
    if isinstance(day,str):
        day=date.fromisoformat(day)
    if day<CAS_START:
        return 375
    if day<CAS_REVISION:
        return 385
    return 390


def derivatives_close(day):
    minute=OPEN_MINUTE+derivatives_segment_minutes(day)
    return time(minute//60,minute%60)


def index_contract_minutes(day,expiry):
    """Exact expiry is required for a full-session denominator after revision.

    The segment maximum remains suitable for a read-only capture gate.
    Rolling historical receipts without exact expiry must not guess it.
    """
    if isinstance(day,str):
        day=date.fromisoformat(day)
    if isinstance(expiry,str):
        expiry=date.fromisoformat(expiry)
    if day>=CAS_REVISION:
        if expiry is None:
            return None
        if expiry<day:
            raise ValueError("Contract already expired")
        if expiry==day:
            return COMPARISON_MINUTES
    return derivatives_segment_minutes(day)
