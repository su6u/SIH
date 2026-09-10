from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Mapping


class MessageRejected(ValueError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _payload_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _message_id(
    sender_id: str,
    boot_id: str,
    sequence: int,
    kind: str,
    payload_hash: str,
) -> str:
    identity = f"{sender_id}|{boot_id}|{sequence}|{kind}|{payload_hash}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def _authentication_tag(signing_key: bytes, fields: Mapping[str, Any]) -> str:
    return hmac.new(
        signing_key,
        _canonical_json(fields).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class MessageEnvelope:
    schema_version: str
    message_id: str
    kind: str
    sender_id: str
    boot_id: str
    sequence: int
    sent_tick: int
    ttl_ticks: int
    map_version: str
    payload: Mapping[str, Any]
    payload_hash: str
    authentication_tag: str

    _FIELDS = frozenset(
        {
            "schema_version",
            "message_id",
            "kind",
            "sender_id",
            "boot_id",
            "sequence",
            "sent_tick",
            "ttl_ticks",
            "map_version",
            "payload",
            "payload_hash",
            "authentication_tag",
        }
    )

    @classmethod
    def create(
        cls,
        *,
        kind: str,
        sender_id: str,
        boot_id: str,
        sequence: int,
        sent_tick: int,
        ttl_ticks: int,
        map_version: str,
        payload: Mapping[str, Any],
        signing_key: bytes,
        schema_version: str = "1.0",
    ) -> "MessageEnvelope":
        if sequence < 0 or sent_tick < 0 or ttl_ticks <= 0:
            raise ValueError("sequence/ticks are invalid")
        if not all((kind, sender_id, boot_id, map_version, schema_version)):
            raise ValueError("message identity fields must not be empty")
        if not isinstance(signing_key, bytes) or not signing_key:
            raise ValueError("signing_key must not be empty")
        digest = _payload_hash(payload)
        message_id = _message_id(sender_id, boot_id, sequence, kind, digest)
        signed_fields = {
            "schema_version": schema_version,
            "message_id": message_id,
            "kind": kind,
            "sender_id": sender_id,
            "boot_id": boot_id,
            "sequence": sequence,
            "sent_tick": sent_tick,
            "ttl_ticks": ttl_ticks,
            "map_version": map_version,
            "payload_hash": digest,
        }
        return cls(
            schema_version=schema_version,
            message_id=message_id,
            kind=kind,
            sender_id=sender_id,
            boot_id=boot_id,
            sequence=sequence,
            sent_tick=sent_tick,
            ttl_ticks=ttl_ticks,
            map_version=map_version,
            payload=dict(payload),
            payload_hash=digest,
            authentication_tag=_authentication_tag(signing_key, signed_fields),
        )

    def validate_integrity(self, signing_key: bytes) -> None:
        if _payload_hash(self.payload) != self.payload_hash:
            raise MessageRejected("payload hash mismatch")
        expected_id = _message_id(
            self.sender_id,
            self.boot_id,
            self.sequence,
            self.kind,
            self.payload_hash,
        )
        if self.message_id != expected_id:
            raise MessageRejected("message identity mismatch")
        signed_fields = {
            "schema_version": self.schema_version,
            "message_id": self.message_id,
            "kind": self.kind,
            "sender_id": self.sender_id,
            "boot_id": self.boot_id,
            "sequence": self.sequence,
            "sent_tick": self.sent_tick,
            "ttl_ticks": self.ttl_ticks,
            "map_version": self.map_version,
            "payload_hash": self.payload_hash,
        }
        expected_tag = _authentication_tag(signing_key, signed_fields)
        if not hmac.compare_digest(self.authentication_tag, expected_tag):
            raise MessageRejected("message authentication failed")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "message_id": self.message_id,
            "kind": self.kind,
            "sender_id": self.sender_id,
            "boot_id": self.boot_id,
            "sequence": self.sequence,
            "sent_tick": self.sent_tick,
            "ttl_ticks": self.ttl_ticks,
            "map_version": self.map_version,
            "payload": dict(self.payload),
            "payload_hash": self.payload_hash,
            "authentication_tag": self.authentication_tag,
        }

    def to_bytes(self) -> bytes:
        return _canonical_json(self.to_mapping()).encode("utf-8")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "MessageEnvelope":
        if set(raw) != cls._FIELDS:
            raise MessageRejected("message envelope fields do not match schema")
        for field in (
            "schema_version",
            "message_id",
            "kind",
            "sender_id",
            "boot_id",
            "map_version",
            "payload_hash",
            "authentication_tag",
        ):
            if not isinstance(raw[field], str) or not raw[field]:
                raise MessageRejected(f"{field} must be a non-empty string")
        for field in ("sequence", "sent_tick", "ttl_ticks"):
            if isinstance(raw[field], bool) or not isinstance(raw[field], int):
                raise MessageRejected(f"{field} must be an integer")
        if raw["sequence"] < 0 or raw["sent_tick"] < 0 or raw["ttl_ticks"] <= 0:
            raise MessageRejected("sequence/ticks are invalid")
        if not isinstance(raw["payload"], dict):
            raise MessageRejected("payload must be an object")
        return cls(
            schema_version=raw["schema_version"],
            message_id=raw["message_id"],
            kind=raw["kind"],
            sender_id=raw["sender_id"],
            boot_id=raw["boot_id"],
            sequence=raw["sequence"],
            sent_tick=raw["sent_tick"],
            ttl_ticks=raw["ttl_ticks"],
            map_version=raw["map_version"],
            payload=dict(raw["payload"]),
            payload_hash=raw["payload_hash"],
            authentication_tag=raw["authentication_tag"],
        )

    @classmethod
    def from_bytes(cls, raw: bytes, *, maximum_bytes: int = 65_507) -> "MessageEnvelope":
        if not isinstance(raw, bytes):
            raise MessageRejected("wire message must be bytes")
        if not raw or len(raw) > maximum_bytes:
            raise MessageRejected("wire message size is invalid")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MessageRejected("wire message is not valid UTF-8 JSON") from error
        if not isinstance(decoded, dict):
            raise MessageRejected("wire message must be an object")
        return cls.from_mapping(decoded)


class ReplayGuard:
    def __init__(
        self,
        *,
        schema_version: str,
        map_version: str,
        authentication_keys: Mapping[str, bytes],
        maximum_payload_bytes: int = 65_536,
        maximum_future_skew_ticks: int = 0,
    ) -> None:
        if maximum_payload_bytes <= 0 or maximum_future_skew_ticks < 0:
            raise ValueError("payload size and future skew limits are invalid")
        if not authentication_keys or any(
            not isinstance(key, bytes) or not key
            for key in authentication_keys.values()
        ):
            raise ValueError("authentication_keys must contain non-empty keys")
        self._schema_version = schema_version
        self._map_version = map_version
        self._maximum_payload_bytes = maximum_payload_bytes
        self._maximum_future_skew_ticks = maximum_future_skew_ticks
        self._authentication_keys = dict(authentication_keys)
        self._last_sequence: dict[tuple[str, str], int] = {}
        self._seen_ids: set[str] = set()

    def accept(self, message: MessageEnvelope, *, current_tick: int) -> None:
        self.validate(message, current_tick=current_tick)
        self._commit(message)

    def validate(self, message: MessageEnvelope, *, current_tick: int) -> None:
        signing_key = self._authentication_keys.get(message.sender_id)
        if signing_key is None:
            raise MessageRejected("unknown authenticated sender")
        message.validate_integrity(signing_key)
        if (
            len(_canonical_json(message.payload).encode("utf-8"))
            > self._maximum_payload_bytes
        ):
            raise MessageRejected("payload exceeds size limit")
        if message.schema_version != self._schema_version:
            raise MessageRejected("schema version mismatch")
        if message.map_version != self._map_version:
            raise MessageRejected("map version mismatch")
        if current_tick + self._maximum_future_skew_ticks < message.sent_tick:
            raise MessageRejected("message timestamp is in the future")
        if current_tick > message.sent_tick + message.ttl_ticks:
            raise MessageRejected("message expired")
        if message.message_id in self._seen_ids:
            raise MessageRejected("duplicate message")
        key = (message.sender_id, message.boot_id)
        if message.sequence <= self._last_sequence.get(key, -1):
            raise MessageRejected("non-increasing sender sequence")

    def _commit(self, message: MessageEnvelope) -> None:
        key = (message.sender_id, message.boot_id)
        self._last_sequence[key] = message.sequence
        self._seen_ids.add(message.message_id)
