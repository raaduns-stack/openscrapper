from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass(frozen=True)
class JobEvent:
    stage: str
    state: str = "running"
    message: str = ""
    counts: dict[str, int] = field(default_factory=dict)
    items: list[dict[str, str]] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class JobEventSink:
    def __init__(self, callback: Callable[[JobEvent], None], max_events: int = 250):
        self.callback = callback
        self.max_events = max_events
        self.events: list[JobEvent] = []

    def emit(self, event: JobEvent) -> None:
        self.events.append(event)
        if len(self.events) > self.max_events:
            del self.events[:-self.max_events]
        self.callback(event)


class NullJobEventSink:
    def emit(self, event: JobEvent) -> None:
        return None


def emit_event(sink: Any, stage: str, message: str = "", state: str = "running", **counts: int) -> None:
    if sink is None:
        return
    sink.emit(JobEvent(stage=stage, state=state, message=message, counts=counts))
