"""In-memory ``ScanTable`` and ``Artefacts`` for tests. Not shipped in the Lambda zip."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from scan.store import UPDATABLE_META, Doc, purl_key


class FakeArtefacts:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, body: bytes) -> None:
        self.objects[key] = body

    def get(self, key: str) -> bytes:
        return self.objects[key]


class FakeTable:
    def __init__(self) -> None:
        self.scans: dict[str, Doc] = {}
        self.nodes: dict[str, dict[str, Doc]] = {}
        self.autopsies: dict[str, Doc] = {}

    def create_scan(self, scan_id: str, meta: Mapping[str, Any]) -> None:
        if scan_id in self.scans:
            raise ValueError("exists")
        self.scans[scan_id] = dict(meta)

    def update_scan(self, scan_id: str, **attrs: Any) -> None:
        if set(attrs) - UPDATABLE_META or scan_id not in self.scans:
            raise ValueError("unsupported")
        self.scans[scan_id].update(attrs)

    def get_scan(self, scan_id: str) -> Doc | None:
        return self.scans.get(scan_id)

    def put_nodes(self, scan_id: str, records: Sequence[Mapping[str, Any]]) -> None:
        bucket = self.nodes.setdefault(scan_id, {})
        for record in records:
            bucket[purl_key(record["purl"])] = dict(record)

    def get_node(self, scan_id: str, purl: str) -> Doc | None:
        return self.nodes.get(scan_id, {}).get(purl_key(purl))

    def list_nodes(self, scan_id: str) -> list[Doc]:
        return list(self.nodes.get(scan_id, {}).values())

    def get_autopsies(self, purls: Sequence[str]) -> dict[str, Doc]:
        return {p: self.autopsies[purl_key(p)] for p in purls if purl_key(p) in self.autopsies}

    def put_autopsy(self, purl: str, doc: Mapping[str, Any]) -> None:
        self.autopsies[purl_key(purl)] = dict(doc)
