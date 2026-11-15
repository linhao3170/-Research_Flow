"""Environment fingerprint and code hash for E2 evidence and certificates.

Both values are content-derived so the executor and the verifier compute the
same fingerprint for the same installation and dataset.  Nothing here reads
secrets or environment variables beyond version strings.
"""

from __future__ import annotations

import hashlib
import platform
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from researchflow.contracts.encoding import hash_payload

__all__ = ["code_hash", "env_fingerprint"]

_PACKAGE_NAMES = ("numpy", "pandas", "scikit-learn", "cryptography", "pydantic")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=1)
def code_hash() -> str:
    """Hash the executable T0 product sources, ruleset and bundled data registry."""

    root = Path(__file__).resolve().parents[1]
    entries: list[list[str]] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        entries.append([path.relative_to(root).as_posix(), _file_sha256(path)])
    rules = root / "rules" / "ruleset.v1.json"
    if rules.is_file():
        entries.append(["rules/ruleset.v1.json", _file_sha256(rules)])
    registry = root / "templates" / "data" / "registry.json"
    if registry.is_file():
        entries.append(["templates/data/registry.json", _file_sha256(registry)])
    return hash_payload(entries)


def _package_versions() -> dict[str, str]:
    from importlib import metadata

    versions: dict[str, str] = {}
    for name in _PACKAGE_NAMES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:  # pragma: no cover - all pinned
            versions[name] = "missing"
    return versions


@lru_cache(maxsize=8)
def env_fingerprint(dataset_sha256: str = "") -> str:
    payload: dict[str, Any] = {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.system(),
        "machine": platform.machine(),
        "packages": _package_versions(),
        "code_hash": code_hash(),
        "dataset_sha256": dataset_sha256,
    }
    return hash_payload(payload)