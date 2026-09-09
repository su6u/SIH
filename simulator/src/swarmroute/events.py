from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class SimulationEvent:
    sequence: int
    tick: int
    kind: str
    entity_id: str
    data: Mapping[str, Any]


class EventLog:
    def __init__(self) -> None:
        self._events: list[SimulationEvent] = []

    def append(
        self,
        *,
        tick: int,
        kind: str,
        entity_id: str,
        data: Mapping[str, Any] | None = None,
    ) -> SimulationEvent:
        if tick < 0 or not kind or not entity_id:
            raise ValueError("event identity and tick are invalid")
        event = SimulationEvent(
            len(self._events) + 1, tick, kind, entity_id, dict(data or {})
        )
        self._events.append(event)
        return event

    @property
    def events(self) -> tuple[SimulationEvent, ...]:
        return tuple(self._events)

    def json_lines(self) -> Iterable[str]:
        for event in self._events:
            yield json.dumps(
                asdict(event),
                default=_json_default,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")
