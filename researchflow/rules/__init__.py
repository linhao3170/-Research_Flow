"""Frozen T0 ruleset loader (WP-08).

The ruleset is a data file, not code: ``researchflow/rules/ruleset.v1.json``.
Its JCS SHA-256 is the ``ruleset_hash`` that a ``TaskSpec`` must declare and
that the Gate binds into every evaluation.  Adding a required check or changing
a tolerance means editing the file and bumping ``ruleset_version``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from researchflow.contracts.encoding import hash_payload

__all__ = [
    "RULESET_PATH",
    "RULESET_VERSION",
    "RULESET_HASH",
    "load_ruleset",
    "required_checks_for",
    "ruleset_hash",
]

RULESET_PATH = Path(__file__).resolve().parent.parent / "rules" / "ruleset.v1.json"


@lru_cache(maxsize=1)
def load_ruleset() -> dict[str, Any]:
    return json.loads(RULESET_PATH.read_text(encoding="utf-8"))


def ruleset_hash(document: dict[str, Any] | None = None) -> str:
    return hash_payload(load_ruleset() if document is None else document)


RULESET_HASH = ruleset_hash()
RULESET_VERSION = str(load_ruleset()["ruleset_version"])


def required_checks_for(node_type: str) -> tuple[str, ...]:
    checks = load_ruleset()["required_checks"].get(node_type)
    if not checks:
        raise KeyError(f"node type has no required checks in the ruleset: {node_type}")
    return tuple(str(check) for check in checks)