from __future__ import annotations

import json
import re
from typing import Any

import pytest

from scan import store
from scan.config import kill_switch_on, load_limits
from scan.store import AUTOPSY_TTL_SECONDS, SCAN_TTL_SECONDS, DynamoScanTable, S3Artefacts

NOW = 1_763_000_000


class _BatchWriter:
    def __init__(self, table: _FakeTable) -> None:
        self._table = table

    def __enter__(self) -> _BatchWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def put_item(self, Item: dict[str, Any]) -> None:  # noqa: N803
        self._table.put_item(Item=Item)


class _FakeTable:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.query_pages = 0

    def put_item(self, Item: dict[str, Any], ConditionExpression: str | None = None) -> None:  # noqa: N803
        key = (Item["pk"], Item["sk"])
        if ConditionExpression and key in self.items:
            raise RuntimeError("ConditionalCheckFailed")
        self.items[key] = dict(Item)

    def get_item(self, Key: dict[str, str]) -> dict[str, Any]:  # noqa: N803
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def update_item(self, **kw: Any) -> None:
        key = (kw["Key"]["pk"], kw["Key"]["sk"])
        if key not in self.items:
            raise RuntimeError("ConditionalCheckFailed")
        for match in re.finditer(r"#a(\d+) = :v(\d+)", kw["UpdateExpression"]):
            name = kw["ExpressionAttributeNames"][f"#a{match.group(1)}"]
            self.items[key][name] = kw["ExpressionAttributeValues"][f":v{match.group(2)}"]

    def query(self, **kw: Any) -> dict[str, Any]:
        pk = kw["ExpressionAttributeValues"][":pk"]
        prefix = kw["ExpressionAttributeValues"][":sk"]
        rows = sorted(
            (i for i in self.items.values() if i["pk"] == pk and i["sk"].startswith(prefix)),
            key=lambda i: i["sk"],
        )
        start = kw.get("ExclusiveStartKey", {}).get("n", 0)
        page = rows[start : start + 2]
        self.query_pages += 1
        out: dict[str, Any] = {"Items": page}
        if start + 2 < len(rows):
            out["LastEvaluatedKey"] = {"n": start + 2}
        return out

    def batch_writer(self, overwrite_by_pkeys: list[str]) -> _BatchWriter:
        assert overwrite_by_pkeys == ["pk", "sk"]
        return _BatchWriter(self)


class _FakeResource:
    def __init__(self) -> None:
        self.table = _FakeTable()
        self.calls = 0

    def Table(self, name: str) -> _FakeTable:  # noqa: N802
        return self.table

    def batch_get_item(self, RequestItems: dict[str, Any]) -> dict[str, Any]:  # noqa: N803
        self.calls += 1
        ((name, request),) = RequestItems.items()
        keys = request["Keys"]
        first, rest = (keys[:1], keys[1:]) if self.calls == 1 and len(keys) > 1 else (keys, [])
        found = [
            self.table.items[(k["pk"], k["sk"])]
            for k in first
            if (k["pk"], k["sk"]) in self.table.items
        ]
        return {
            "Responses": {name: found},
            "UnprocessedKeys": {name: {"Keys": rest}} if rest else {},
        }


def make(now: int = NOW) -> tuple[DynamoScanTable, _FakeResource, list[int]]:
    clock = [now]
    resource = _FakeResource()
    return DynamoScanTable(resource, "graveyard-dev-data", lambda: clock[0]), resource, clock


def test_scan_meta_create_update_get() -> None:
    table, resource, _ = make()
    table.create_scan("S1", {"status": "QUEUED", "counts": {"total": 0}})
    item = resource.table.items[("SCAN#S1", "META")]
    assert item["ttl"] == NOW + SCAN_TTL_SECONDS
    table.update_scan("S1", status="RUNNING", stage="FETCH")
    assert table.get_scan("S1")["status"] == "RUNNING"  # type: ignore[index]
    with pytest.raises(RuntimeError):
        table.create_scan("S1", {})
    with pytest.raises(ValueError):
        table.update_scan("S1", pk="x")
    with pytest.raises(ValueError):
        table.update_scan("S1")
    assert table.get_scan("S2") is None


def test_nodes_round_trip_and_case_insensitive_key() -> None:
    table, resource, _ = make()
    records = [
        {"purl": f"pkg:npm/Pkg{i}@1.0.0", "state": "alive", "mortality": 1.5} for i in range(5)
    ]
    table.put_nodes("S1", records)
    assert ("SCAN#S1", "NODE#npm/pkg0@1.0.0") in resource.table.items
    assert table.get_node("S1", "pkg:npm/PKG0@1.0.0") == records[0]
    assert len(table.list_nodes("S1")) == 5
    assert resource.table.query_pages == 3
    assert table.get_node("S1", "pkg:npm/nope@1.0.0") is None


def test_autopsy_cache_ttl_and_expiry() -> None:
    table, resource, clock = make()
    table.put_autopsy("pkg:pypi/requests@2.0.0", {"signals": {"x": 1.5}})
    stored = resource.table.items[("PKG#pypi/requests@2.0.0", "AUTOPSY#v1")]
    assert stored["ttl"] == NOW + AUTOPSY_TTL_SECONDS
    assert json.loads(stored["doc"]) == {"signals": {"x": 1.5}}
    assert table.get_autopsies(["pkg:pypi/requests@2.0.0"]) == {
        "pkg:pypi/requests@2.0.0": {"signals": {"x": 1.5}}
    }
    clock[0] = NOW + AUTOPSY_TTL_SECONDS  # DynamoDB has not deleted it yet
    assert table.get_autopsies(["pkg:pypi/requests@2.0.0"]) == {}


def test_batch_get_retries_unprocessed_keys() -> None:
    table, resource, _ = make()
    purls = [f"pkg:pypi/p{i}@1.0" for i in range(3)]
    for purl in purls:
        table.put_autopsy(purl, {"n": purl})
    got = table.get_autopsies(purls)
    assert set(got) == set(purls)
    assert resource.calls == 2


class _S3:
    def __init__(self) -> None:
        self.puts: list[dict[str, Any]] = []

    def put_object(self, **kw: Any) -> None:
        self.puts.append(kw)

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        class Body:
            def read(self) -> bytes:
                return b"data"

        return {"Body": Body()}


def test_artefacts_use_kms() -> None:
    s3 = _S3()
    artefacts = S3Artefacts(s3, "graveyard-dev-artefacts")
    artefacts.put("scans/x", b"1")
    assert s3.puts[0]["ServerSideEncryption"] == "aws:kms"
    assert artefacts.get("scans/x") == b"data"


def test_artefact_keys() -> None:
    assert store.manifest_key("S", 2, "uv.lock") == "scans/S/manifests/2/uv.lock"
    assert store.sbom_key("S", 0) == "scans/S/sbom/0.cdx.json"
    assert store.purls_key("S").endswith("purls.json")


def test_config() -> None:
    params = {
        "limits/max-services": "50",
        "limits/max-manifest-bytes": "10",
        "limits/max-file-bytes": "5",
        "limits/max-purls": "2000",
        "kill-switch": " True ",
    }
    limits = load_limits(params.__getitem__)
    assert limits.select.max_services == 50 and limits.max_purls == 2000
    assert kill_switch_on(params.__getitem__)
    assert not kill_switch_on({"kill-switch": "false"}.__getitem__)
    with pytest.raises(ValueError):
        load_limits({**params, "limits/max-purls": "0"}.__getitem__)
