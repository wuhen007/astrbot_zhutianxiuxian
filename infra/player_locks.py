"""Per-player command locks with cleanup after the last waiter exits."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class _Entry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class PlayerLockPool:
    def __init__(self):
        self._entries: dict[str, _Entry] = {}

    @asynccontextmanager
    async def hold(self, uid: str) -> AsyncIterator[None]:
        key = str(uid)
        entry = self._entries.get(key)
        if entry is None:
            entry = _Entry()
            self._entries[key] = entry
        entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            entry.users -= 1
            if entry.users == 0 and self._entries.get(key) is entry:
                del self._entries[key]
