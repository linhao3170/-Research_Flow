"""Dataset resolution for the bundled offline tabular template (T0 WP-05).

Only ``local://datasets/<file>`` URIs that resolve inside the active data root
are accepted.  Network URIs, absolute paths, backslashes and ``..`` segments
are rejected before any file access.

The data root defaults to ``researchflow/templates/data`` and can be pointed at
an isolated copy with ``RESEARCHFLOW_DATA_ROOT`` (used by the three offline
end-to-end runs so each run owns its input files).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from researchflow.templates.errors import (
    DatasetError,
    DatasetHashMismatch,
    DatasetPathEscape,
    DatasetUriInvalid,
)

__all__ = [
    "BUNDLED_DATA_ROOT",
    "DatasetFile",
    "data_root",
    "dataset_file_sha256",
    "dataset_registry",
    "load_dataset_frame",
    "resolve_dataset",
]

BUNDLED_DATA_ROOT = Path(__file__).resolve().parent / "data"
URI_PREFIX = "local://datasets/"


def data_root() -> Path:
    configured = os.environ.get("RESEARCHFLOW_DATA_ROOT")
    return Path(configured).resolve() if configured else BUNDLED_DATA_ROOT


def _registry_path() -> Path:
    return data_root() / "registry.json"


@dataclass(frozen=True, slots=True)
class DatasetFile:
    uri: str
    path: Path
    sha256: str
    license: str
    rows: int
    columns: tuple[str, ...]


def dataset_registry() -> dict[str, Any]:
    path = _registry_path()
    if not path.is_file():
        raise DatasetError(f"dataset registry missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def dataset_file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_uri(uri: str) -> str:
    if not isinstance(uri, str) or not uri.startswith(URI_PREFIX):
        raise DatasetUriInvalid(
            "dataset URI must be local://datasets/<file> (T0 is offline; no network URI)",
            field_path="dataset_ref.uri",
        )
    relative = uri[len(URI_PREFIX) :]
    if (
        not relative
        or relative.startswith("/")
        or "\\" in relative
        or "://" in relative
        or any(segment in {"", ".", ".."} for segment in relative.split("/"))
    ):
        raise DatasetPathEscape(
            "dataset URI must not contain absolute, empty, '.' or '..' segments",
            field_path="dataset_ref.uri",
        )
    return relative


def resolve_dataset(uri: str, sha256: str) -> DatasetFile:
    relative = _relative_uri(uri)
    registry = dataset_registry()
    entry = registry.get("datasets", {}).get(uri)
    if entry is None:
        raise DatasetError(
            f"dataset URI is not registered: {uri}", field_path="dataset_ref.uri"
        )
    root = data_root()
    path = (root / relative).resolve()
    if root not in path.parents:
        raise DatasetPathEscape(
            "dataset path escapes the active data directory",
            field_path="dataset_ref.uri",
        )
    if not path.is_file():
        raise DatasetError(
            f"dataset file is missing: {relative}", field_path="dataset_ref.uri"
        )
    actual = dataset_file_sha256(path)
    if actual != sha256:
        raise DatasetHashMismatch(
            "dataset_ref.sha256 does not match the data file "
            f"(expected {sha256}, actual {actual})",
            field_path="dataset_ref.sha256",
        )
    if entry.get("sha256") != actual:
        raise DatasetHashMismatch(
            "data file changed without updating the dataset registry",
            field_path="dataset_ref.sha256",
        )
    return DatasetFile(
        uri=uri,
        path=path,
        sha256=actual,
        license=str(entry.get("license", "")),
        rows=int(entry.get("rows", 0)),
        columns=tuple(str(column) for column in entry.get("columns", [])),
    )


def load_dataset_frame(dataset: DatasetFile):
    import pandas as pd

    frame = pd.read_csv(dataset.path)
    if list(frame.columns) != list(dataset.columns):
        raise DatasetError(
            "dataset columns do not match the registry",
            field_path="dataset_ref.uri",
        )
    if len(frame) != dataset.rows:
        raise DatasetError(
            "dataset row count does not match the registry",
            field_path="dataset_ref.uri",
        )
    return frame