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
BANK_POLICY="nse_bank_cash_cas_2026_v2"
# Narrow reviewed BANKNIFTY research union: exact Dhan NSE_EQ identities
# from the saved PIT batch and observed 360-slot Aug 3-Oct 13, 2026 audit.
# All sixteen are NSE F&O underlyings in the reviewed NSE list. This is not
# a general dated eligibility master; do not apply to arbitrary equities.
BANK_CAS_IDENTITIES={
    "NSE_EQ:21238":"AUBANK","NSE_EQ:5900":"AXISBANK",
    "NSE_EQ:2263":"BANDHANBNK","NSE_EQ:4668":"BANKBARODA",
    "NSE_EQ:10794":"CANBK","NSE_EQ:1023":"FEDERALBNK",
    "NSE_EQ:1333":"HDFCBANK","NSE_EQ:4963":"ICICIBANK",
    "NSE_EQ:11184":"IDFCFIRSTB","NSE_EQ:5258":"INDUSINDBK",
    "NSE_EQ:1922":"KOTAKBANK","NSE_EQ:10666":"PNB",
    "NSE_EQ:18391":"RBLBANK","NSE_EQ:3045":"SBIN",
    "NSE_EQ:10753":"UNIONBANK","NSE_EQ:11915":"YESBANK",
}
BANK_CAS_SYMBOLS=frozenset(BANK_CAS_IDENTITIES.values())


def bank_cas_eligible(day,identity,symbol=None):
    """Reviewed normal-session policy, not proof of every exceptional day."""
    if isinstance(day,str):
        day=date.fromisoformat(day)
    known=BANK_CAS_IDENTITIES.get(identity)
    return day>=CAS_START and known is not None and (symbol is None or symbol==known)


def cash_bank_minutes(day,identity,symbol=None):
    if isinstance(day,str):
        day=date.fromisoformat(day)
    if day<CAS_REVISION and bank_cas_eligible(day,identity,symbol):
        return 360
    return COMPARISON_MINUTES


def cash_close_minute(day,identity,symbol=None):
    return OPEN_MINUTE+cash_bank_minutes(day,identity,symbol)


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


def index_contract_close(day,expiry):
    minutes=index_contract_minutes(day,expiry)
    if minutes is None:
        return None
    minute=OPEN_MINUTE+minutes
    return time(minute//60,minute%60)


def index_expiry_close(expiry):
    """Scheduled normal trading cutoff, not exchange settlement timestamp."""
    return index_contract_close(expiry,expiry)
