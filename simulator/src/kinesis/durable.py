from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Protocol


class DurableStateError(ValueError):
    pass


class PeerStateStore(Protocol):
    def load(self) -> Mapping[str, Any] | None: ...

    def save(self, state: Mapping[str, Any]) -> None: ...


class JsonPeerStateStore:
    """Atomic, fsync-backed local state for one robot process.

    The file is private to a robot.  It is not shared storage and is never used
    as a coordination service.  Atomic replacement prevents a power loss from
    leaving a partially written membership or fencing record.
    """

    def __init__(self, path: str | Path, *, maximum_bytes: int = 1_048_576) -> None:
        if maximum_bytes <= 0:
            raise ValueError("maximum_bytes must be positive")
        self.path = Path(path)
        self._maximum_bytes = maximum_bytes

    def load(self) -> Mapping[str, Any] | None:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as error:
            raise DurableStateError(f"cannot read peer state: {error}") from error
        if not raw or len(raw) > self._maximum_bytes:
            raise DurableStateError("peer state size is invalid")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DurableStateError("peer state is not valid UTF-8 JSON") from error
        if not isinstance(decoded, dict):
            raise DurableStateError("peer state root must be an object")
        return decoded

    def save(self, state: Mapping[str, Any]) -> None:
        encoded = json.dumps(
            state,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if not encoded or len(encoded) > self._maximum_bytes:
            raise DurableStateError("peer state size is invalid")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
            )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_name, self.path)
                directory = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            except BaseException:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
                raise
        except OSError as error:
            raise DurableStateError(f"cannot persist peer state: {error}") from error
