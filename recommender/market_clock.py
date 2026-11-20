"""NSE cash session in India time.

Weekend and the holiday list in indian_config close the session. The clock
does not try to guess a Muhurat session.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import indian_config

IST = ZoneInfo("Asia/Kolkata")


def session(moment: datetime | None = None) -> dict:
    """Return whether the cash market is open at `moment`."""
    clock = _in_ist(moment)
    day = clock.strftime("%Y-%m-%d")
    holidays = set(indian_config.get_nse_holidays(clock.year))
    opens, closes = indian_config.get_trading_hours()
    if clock.weekday() >= 5:
        state, reason = "closed", "Weekend"
    elif day in holidays:
        state, reason = "holiday", "NSE holiday"
    elif opens <= clock.time() <= closes:
        state, reason = "open", "Regular session, 9:15 to 15:30 IST"
    else:
        state, reason = "closed", "Outside 9:15 to 15:30 IST"
    return {"state": state, "reason": reason, "as_of": clock.strftime("%Y-%m-%d %H:%M IST")}


def _in_ist(moment: datetime | None) -> datetime:
    if moment is None:
        return datetime.now(IST)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=IST)
    return moment.astimezone(IST)
