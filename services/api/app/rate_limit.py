from time import monotonic
from collections import deque
from threading import Lock
from typing import Literal

from fastapi import HTTPException

Action = Literal["token.create", "token.revoke", "service.connection_test"]
LIMITS: dict[Action, int] = {"token.create": 10, "token.revoke": 30, "service.connection_test": 12}
buckets: dict[tuple[str, Action], deque[float]] = {}
lock = Lock()


def limit_action(actor_id: str, action: Action) -> None:
    now = monotonic()
    with lock:
        expired = [key for key, attempts in buckets.items() if not attempts or attempts[-1] <= now - 60]
        for key in expired:
            del buckets[key]
        key = (actor_id, action)
        if key not in buckets and len(buckets) >= 2048:
            raise HTTPException(429, "Request limit reached; try again in a minute")
        recent = buckets.setdefault(key, deque())
        while recent and recent[0] <= now - 60:
            recent.popleft()
        if len(recent) >= LIMITS[action]:
            raise HTTPException(429, "Request limit reached; try again in a minute")
        recent.append(now)
