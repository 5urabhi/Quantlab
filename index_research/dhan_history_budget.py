"""Process-wide budget for real Dhan historical HTTP requests.

Index/equity/active/expired-option transports share this scheduler. This
does not include live quote endpoints, external apps, or other processes;
it is a conservative local allocation, not an account-wide quota claim.
"""
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from threading import Condition
from urllib.error import HTTPError
import math
import time

START_SPACING = .35  # under 3 historical starts/s; leave headroom below 5/s
MAX_IN_FLIGHT = 2
MAX_24H_STARTS = 80000
COOLDOWN_SECONDS = 900
DAY_SECONDS = 86400


class HistoricalThrottle(RuntimeError):
    def __init__(self, seconds):
        self.retry_after_seconds = max(1, math.ceil(seconds))
        super().__init__("Dhan historical rate limit (HTTP 429); shared cooldown")


def retry_after(headers):
    value = str(headers.get("Retry-After", "")).strip() if headers else ""
    try:
        if value.isdigit() and len(value) <= 9:
            return int(value)
        when = parsedate_to_datetime(value)
        if when.tzinfo is not None:
            return max(0, math.ceil((when-datetime.now(timezone.utc)).total_seconds()))
    except (ValueError, TypeError, OverflowError):
        pass
    return 0


class HistoryBudget:
    def __init__(self, spacing=START_SPACING, max_in_flight=MAX_IN_FLIGHT,
                 max_starts=MAX_24H_STARTS, day_seconds=DAY_SECONDS,
                 cooldown_seconds=COOLDOWN_SECONDS):
        self.spacing=spacing
        self.max_in_flight=max_in_flight
        self.max_starts=max_starts
        self.day_seconds=day_seconds
        self.cooldown_seconds=cooldown_seconds
        self.condition=Condition()
        self.starts=deque()
        self.active=0
        self.last_start=None
        self.cooldown_until=0.0

    def _prune(self, now):
        while self.starts and self.starts[0]+self.day_seconds<=now:
            self.starts.popleft()

    def remaining_cooldown(self):
        with self.condition:
            now=time.monotonic()
            self._prune(now)
            budget_delay=(self.starts[0]+self.day_seconds-now
                          if len(self.starts)>=self.max_starts else 0)
            return max(0, math.ceil(max(self.cooldown_until-now,budget_delay)))

    def throttle(self, seconds=0):
        with self.condition:
            self.cooldown_until=max(self.cooldown_until,
                                    time.monotonic()+max(self.cooldown_seconds,seconds))
            self.condition.notify_all()

    @contextmanager
    def slot(self):
        with self.condition:
            while True:
                now=time.monotonic()
                self._prune(now)
                remaining=max(0,self.cooldown_until-now)
                if len(self.starts)>=self.max_starts:
                    remaining=max(remaining,self.starts[0]+self.day_seconds-now)
                if remaining>0:
                    raise HistoricalThrottle(remaining)
                spacing=(max(0,self.last_start+self.spacing-now)
                         if self.last_start is not None else 0)
                if self.active<self.max_in_flight and not spacing:
                    self.active+=1
                    self.last_start=now
                    self.starts.append(now)
                    break
                self.condition.wait(timeout=spacing or .1)
        try:
            yield
        except HTTPError as exc:
            if exc.code==429:
                self.throttle(retry_after(exc.headers))
            raise
        finally:
            with self.condition:
                self.active-=1
                self.condition.notify_all()

    def snapshot(self):
        with self.condition:
            self._prune(time.monotonic())
            return {"historical_starts_last_24h":len(self.starts),
                    "historical_local_24h_limit":self.max_starts,
                    "historical_max_in_flight":self.max_in_flight,
                    "historical_start_spacing_seconds":self.spacing,
                    "historical_active_requests":self.active,
                    "historical_process_local":True}


BUDGET=HistoryBudget()
