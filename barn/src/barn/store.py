from __future__ import annotations

import asyncio
from typing import Protocol

from .domain import BarnEvent, RunState


class RunNotFoundError(KeyError):
    pass


class RunAlreadyExistsError(ValueError):
    pass


class GraphStore(Protocol):
    async def create_run(self, state: RunState) -> RunState: ...

    async def get_run(self, run_id: str) -> RunState: ...

    async def save_run(self, state: RunState, expected_version: int | None = None) -> RunState: ...

    async def append_event(self, event: BarnEvent) -> BarnEvent: ...

    async def list_events(self, run_id: str) -> list[BarnEvent]: ...

    async def get_event_by_command(self, run_id: str, command_id: str) -> BarnEvent | None: ...


class InMemoryGraphStore:
    """Reference store. Copies cross the boundary to prevent accidental mutation."""

    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}
        self._events: dict[str, list[BarnEvent]] = {}
        self._events_by_command: dict[tuple[str, str], BarnEvent] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, run_id: str) -> asyncio.Lock:
        return self._locks.setdefault(run_id, asyncio.Lock())

    async def create_run(self, state: RunState) -> RunState:
        async with self._lock(state.id):
            if state.id in self._runs:
                raise RunAlreadyExistsError(state.id)
            stored = state.model_copy(deep=True)
            self._runs[state.id] = stored
            self._events[state.id] = []
            return stored.model_copy(deep=True)

    async def get_run(self, run_id: str) -> RunState:
        try:
            return self._runs[run_id].model_copy(deep=True)
        except KeyError as exc:
            raise RunNotFoundError(run_id) from exc

    async def save_run(self, state: RunState, expected_version: int | None = None) -> RunState:
        async with self._lock(state.id):
            current = self._runs.get(state.id)
            if current is None:
                raise RunNotFoundError(state.id)
            if expected_version is not None and current.version != expected_version:
                raise ValueError(
                    f"version conflict for {state.id}: expected {expected_version}, actual {current.version}"
                )
            stored = state.model_copy(deep=True)
            stored.version = current.version + 1
            self._runs[state.id] = stored
            return stored.model_copy(deep=True)

    async def append_event(self, event: BarnEvent) -> BarnEvent:
        async with self._lock(event.run_id):
            if event.run_id not in self._runs:
                raise RunNotFoundError(event.run_id)
            key = (event.run_id, event.command_id)
            existing = self._events_by_command.get(key)
            if existing is not None:
                return existing.model_copy(deep=True)
            committed = event.model_copy(deep=True)
            committed.seq = len(self._events[event.run_id]) + 1
            self._events[event.run_id].append(committed)
            self._events_by_command[key] = committed
            return committed.model_copy(deep=True)

    async def list_events(self, run_id: str) -> list[BarnEvent]:
        if run_id not in self._runs:
            raise RunNotFoundError(run_id)
        return [event.model_copy(deep=True) for event in self._events[run_id]]

    async def get_event_by_command(self, run_id: str, command_id: str) -> BarnEvent | None:
        event = self._events_by_command.get((run_id, command_id))
        return event.model_copy(deep=True) if event is not None else None
