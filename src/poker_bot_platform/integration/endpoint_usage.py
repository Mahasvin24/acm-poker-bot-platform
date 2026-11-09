"""Single-worker endpoint admission locks shared by testing and tournament admission."""

import asyncio
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

EndpointKey = tuple[str, int]


@dataclass
class _Entry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class EndpointUsage:
    def __init__(self) -> None:
        self._entries: dict[EndpointKey, _Entry] = {}

    @asynccontextmanager
    async def reserve(self, keys: Iterable[EndpointKey]) -> AsyncIterator[None]:
        # Fixed ordering prevents deadlocks when tournaments share multiple bots.
        entries = [(key, self._entries.setdefault(key, _Entry())) for key in sorted(set(keys))]
        for _, entry in entries:
            entry.users += 1
        acquired: list[_Entry] = []
        try:
            for _, entry in entries:
                await entry.lock.acquire()
                acquired.append(entry)
            yield
        finally:
            for entry in reversed(acquired):
                entry.lock.release()
            for key, entry in entries:
                entry.users -= 1
                if entry.users == 0:
                    del self._entries[key]
