"""Ed25519 key storage and trust anchors (T0 WP-11).

The private key never leaves the runtime key store: it is not written into an
Evidence Bundle, an evidence payload, a report, a certificate or a log.  Only
the public key + fingerprint are published in a trust anchor document that the
offline verifier receives from *outside* the bundle.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from researchflow.contracts.encoding import hash_payload

__all__ = [
    "DEFAULT_KEY_ID",
    "KeyRecord",
    "KeyStore",
    "TrustAnchorError",
    "TrustedKey",
    "load_trust_anchor",
    "trust_anchor_from_public_keys",
]

DEFAULT_KEY_ID = "rf-t0-ed25519-01"
ALG = "Ed25519"


class TrustAnchorError(RuntimeError):
    code = "SIGNATURE_INVALID"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)


def public_key_fingerprint(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return hash_payload({"alg": ALG, "public_key_b64": _b64(raw)})


@dataclass(frozen=True, slots=True)
class KeyRecord:
    key_id: str
    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey
    fingerprint: str

    def public_document(self) -> dict[str, Any]:
        raw = self.public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        return {
            "key_id": self.key_id,
            "alg": ALG,
            "public_key_b64": _b64(raw),
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True, slots=True)
class TrustedKey:
    key_id: str
    alg: str
    public_key: Ed25519PublicKey
    fingerprint: str


class KeyStore:
    def __init__(self, root: str | Path, *, key_id: str = DEFAULT_KEY_ID) -> None:
        self._root = Path(root)
        self._key_id = key_id

    @property
    def root(self) -> Path:
        return self._root

    @property
    def key_id(self) -> str:
        return self._key_id

    def _private_path(self, key_id: str) -> Path:
        return self._root / f"{key_id}.private.json"

    def _public_path(self, key_id: str) -> Path:
        return self._root / f"{key_id}.public.json"

    def generate(self, *, key_id: str | None = None, overwrite: bool = False) -> KeyRecord:
        key_id = key_id or self._key_id
        self._root.mkdir(parents=True, exist_ok=True)
        private_path = self._private_path(key_id)
        if private_path.exists() and not overwrite:
            raise FileExistsError(f"key already exists: {key_id} (refusing to overwrite)")
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        record = KeyRecord(
            key_id=key_id,
            private_key=private_key,
            public_key=public_key,
            fingerprint=public_key_fingerprint(public_key),
        )
        private_bytes = private_key.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        )
        private_document = {
            "schema_version": "1.0",
            "key_id": key_id,
            "alg": ALG,
            "private_key_b64": _b64(private_bytes),
            "public_key_b64": _b64(
                public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
            ),
            "fingerprint": record.fingerprint,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        }
        private_path.write_text(
            json.dumps(private_document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:  # best effort on Windows; the directory is git-ignored and local.
            os.chmod(private_path, 0o600)
        except OSError:  # pragma: no cover - Windows ACLs are unchanged
            pass
        self._public_path(key_id).write_text(
            json.dumps(record.public_document(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return record

    def load(self, key_id: str | None = None) -> KeyRecord:
        key_id = key_id or self._key_id
        private_path = self._private_path(key_id)
        if not private_path.is_file():
            raise FileNotFoundError(f"private key is missing for {key_id}")
        document = json.loads(private_path.read_text(encoding="utf-8"))
        if document.get("alg") != ALG:
            raise TrustAnchorError(f"unsupported key algorithm: {document.get('alg')}")
        private_key = Ed25519PrivateKey.from_private_bytes(
            _unb64(str(document["private_key_b64"]))
        )
        public_key = private_key.public_key()
        fingerprint = public_key_fingerprint(public_key)
        if fingerprint != document.get("fingerprint"):
            raise TrustAnchorError("key fingerprint does not match the stored private key")
        return KeyRecord(
            key_id=key_id,
            private_key=private_key,
            public_key=public_key,
            fingerprint=fingerprint,
        )

    def load_or_create(self, key_id: str | None = None) -> KeyRecord:
        try:
            return self.load(key_id)
        except FileNotFoundError:
            return self.generate(key_id=key_id)

    def trust_anchor_document(self, key_id: str | None = None) -> dict[str, Any]:
        record = self.load(key_id)
        return {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            ),
            "keys": [record.public_document()],
        }

    def write_trust_anchor(self, path: str | Path, key_id: str | None = None) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.trust_anchor_document(key_id), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return target


def load_trust_anchor(path: str | Path) -> dict[str, TrustedKey]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema_version") != "1.0":
        raise TrustAnchorError("unsupported trust anchor schema_version")
    keys: dict[str, TrustedKey] = {}
    for entry in document.get("keys", []):
        if entry.get("alg") != ALG:
            raise TrustAnchorError(f"unsupported key algorithm: {entry.get('alg')}")
        raw = _unb64(str(entry["public_key_b64"]))
        public_key = Ed25519PublicKey.from_public_bytes(raw)
        fingerprint = public_key_fingerprint(public_key)
        if fingerprint != entry.get("fingerprint"):
            raise TrustAnchorError(
                f"trust anchor fingerprint mismatch for {entry.get('key_id')}"
            )
        keys[str(entry["key_id"])] = TrustedKey(
            key_id=str(entry["key_id"]),
            alg=ALG,
            public_key=public_key,
            fingerprint=fingerprint,
        )
    if not keys:
        raise TrustAnchorError("trust anchor contains no keys")
    return keys


def trust_anchor_from_public_keys(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": "1.0", "keys": entries}