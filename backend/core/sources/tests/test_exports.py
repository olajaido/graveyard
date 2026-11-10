"""The pure public names resolve from ``core.sources`` to their defining objects (SRC-NFR-4)."""

from __future__ import annotations

import importlib

import pytest

import core.sources as pkg

EXPECTED = {
    "Evidence": "core.sources.model",
    "SourceWarning": "core.sources.model",
    "ItemError": "core.sources.model",
    "SourceResult": "core.sources.model",
    "SourceStats": "core.sources.model",
    "BatchResult": "core.sources.model",
    "EVIDENCE_KEYS": "core.sources.model",
    "WARNING_CODES": "core.sources.model",
    "SOURCE_NAMES": "core.sources.model",
    "ITEM_ERROR_CODES": "core.sources.model",
    "REPO_VIA_VALUES": "core.sources.model",
    "JsonValue": "core.sources.model",
    "SourcesConfig": "core.sources.config",
    "HostPolicy": "core.sources.config",
    "Timeouts": "core.sources.config",
    "RetryPolicy": "core.sources.config",
    "CachePolicy": "core.sources.config",
    "Limits": "core.sources.config",
    "SecretToken": "core.sources.secret",
    "redact": "core.sources.secret",
    "Clock": "core.sources.clock",
    "RepoVia": "core.sources.repo_resolve",
}


def test_all_matches_the_expected_names() -> None:
    assert set(pkg.__all__) == set(EXPECTED)


@pytest.mark.parametrize(("name", "module"), sorted(EXPECTED.items()))
def test_name_is_the_defining_object(name: str, module: str) -> None:
    assert getattr(pkg, name) is getattr(importlib.import_module(module), name)
