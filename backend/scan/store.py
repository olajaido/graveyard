"""The table and the artefacts bucket (SB-DATA-2 to SB-DATA-4).

Items hold ints, strings, bools and small maps natively. Anything with floats (nodes, the
autopsy cache) is stored as a JSON string in ``doc``, because DynamoDB takes no floats.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final, Protocol

from core.purl import package_key, parse_purl

SCAN_TTL_SECONDS: Final = 30 * 24 * 3600
AUTOPSY_TTL_SECONDS: Final = 24 * 3600
UPDATABLE_META: Final = frozenset(
    {"status", "stage", "counts", "partial", "modelVersion", "errorCode", "updatedAt"}
)
_BATCH_GET: Final = 100
_MAX_UNPROCESSED_ROUNDS: Final = 5

type Doc = dict[str, Any]
type Clock = Callable[[], int]


def now_seconds() -> int:
    return int(time.time())


def purl_key(purl: str) -> str:
    """The case-folded package key used in item keys, so one package has one item."""
    return package_key(parse_purl(purl))


# ------------------------------------------------------------------------ artefact keys


def scan_prefix(scan_id: str) -> str:
    return f"scans/{scan_id}/"


def manifest_key(scan_id: str, index: int, name: str) -> str:
    return f"{scan_prefix(scan_id)}manifests/{index}/{name}"


def services_key(scan_id: str) -> str:
    return f"{scan_prefix(scan_id)}services.json"


def sbom_key(scan_id: str, index: int) -> str:
    return f"{scan_prefix(scan_id)}sbom/{index}.cdx.json"


def purls_key(scan_id: str) -> str:
    return f"{scan_prefix(scan_id)}purls.json"


def nodes_key(scan_id: str) -> str:
    return f"{scan_prefix(scan_id)}nodes.json"


# --------------------------------------------------------------------------- protocols


class Artefacts(Protocol):
    def put(self, key: str, body: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...


class ScanTable(Protocol):
    def create_scan(self, scan_id: str, meta: Mapping[str, Any]) -> None: ...

    def update_scan(self, scan_id: str, **attrs: Any) -> None: ...

    def get_scan(self, scan_id: str) -> Doc | None: ...

    def put_nodes(self, scan_id: str, records: Sequence[Mapping[str, Any]]) -> None: ...

    def get_node(self, scan_id: str, purl: str) -> Doc | None: ...

    def list_nodes(self, scan_id: str) -> list[Doc]: ...

    def get_autopsies(self, purls: Sequence[str]) -> dict[str, Doc]: ...

    def put_autopsy(self, purl: str, doc: Mapping[str, Any]) -> None: ...


# ---------------------------------------------------------------------------- boto3


class S3Artefacts:
    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def put(self, key: str, body: bytes) -> None:
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=body, ServerSideEncryption="aws:kms"
        )

    def get(self, key: str) -> bytes:
        data: bytes = self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        return data


class DynamoScanTable:
    """``resource`` is ``boto3.resource("dynamodb")``; ``table_name`` comes from the caller."""

    def __init__(self, resource: Any, table_name: str, clock: Clock = now_seconds) -> None:
        self._resource = resource
        self._name = table_name
        self._table = resource.Table(table_name)
        self._clock = clock

    # scan META
    def create_scan(self, scan_id: str, meta: Mapping[str, Any]) -> None:
        item = {
            **meta,
            "pk": f"SCAN#{scan_id}",
            "sk": "META",
            "ttl": self._clock() + SCAN_TTL_SECONDS,
        }
        self._table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")

    def update_scan(self, scan_id: str, **attrs: Any) -> None:
        unknown = set(attrs) - UPDATABLE_META
        if unknown or not attrs:
            raise ValueError("unsupported scan attributes")
        names = {f"#a{i}": name for i, name in enumerate(attrs)}
        values = {f":v{i}": value for i, value in enumerate(attrs.values())}
        expression = "SET " + ", ".join(f"#a{i} = :v{i}" for i in range(len(attrs)))
        self._table.update_item(
            Key={"pk": f"SCAN#{scan_id}", "sk": "META"},
            UpdateExpression=expression,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(pk)",
        )

    def get_scan(self, scan_id: str) -> Doc | None:
        item = self._table.get_item(Key={"pk": f"SCAN#{scan_id}", "sk": "META"}).get("Item")
        return self._live(item)

    # nodes
    def put_nodes(self, scan_id: str, records: Sequence[Mapping[str, Any]]) -> None:
        ttl = self._clock() + SCAN_TTL_SECONDS
        with self._table.batch_writer(overwrite_by_pkeys=["pk", "sk"]) as batch:
            for record in records:
                batch.put_item(
                    Item={
                        "pk": f"SCAN#{scan_id}",
                        "sk": f"NODE#{purl_key(record['purl'])}",
                        "doc": json.dumps(record, separators=(",", ":")),
                        "ttl": ttl,
                    }
                )

    def get_node(self, scan_id: str, purl: str) -> Doc | None:
        key = {"pk": f"SCAN#{scan_id}", "sk": f"NODE#{purl_key(purl)}"}
        item = self._live(self._table.get_item(Key=key).get("Item"))
        return None if item is None else json.loads(item["doc"])

    def list_nodes(self, scan_id: str) -> list[Doc]:
        nodes: list[Doc] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": "pk = :pk AND begins_with(sk, :sk)",
            "ExpressionAttributeValues": {":pk": f"SCAN#{scan_id}", ":sk": "NODE#"},
        }
        while True:
            page = self._table.query(**kwargs)
            for item in page.get("Items", []):
                if self._live(item) is not None:
                    nodes.append(json.loads(item["doc"]))
            last = page.get("LastEvaluatedKey")
            if not last:
                return nodes
            kwargs["ExclusiveStartKey"] = last

    # autopsy cache
    def get_autopsies(self, purls: Sequence[str]) -> dict[str, Doc]:
        """Cached results by input purl. A missing or expired item is simply absent."""
        by_key = {purl_key(p): p for p in purls}
        keys = [{"pk": f"PKG#{k}", "sk": "AUTOPSY#v1"} for k in by_key]
        found: dict[str, Doc] = {}
        for start in range(0, len(keys), _BATCH_GET):
            pending: Any = {self._name: {"Keys": keys[start : start + _BATCH_GET]}}
            for _ in range(_MAX_UNPROCESSED_ROUNDS):
                response = self._resource.batch_get_item(RequestItems=pending)
                for item in response["Responses"].get(self._name, []):
                    if self._live(item) is not None:
                        found[by_key[item["pk"].removeprefix("PKG#")]] = json.loads(item["doc"])
                pending = response.get("UnprocessedKeys")
                if not pending:
                    break
        return found

    def put_autopsy(self, purl: str, doc: Mapping[str, Any]) -> None:
        self._table.put_item(
            Item={
                "pk": f"PKG#{purl_key(purl)}",
                "sk": "AUTOPSY#v1",
                "doc": json.dumps(doc, separators=(",", ":")),
                "ttl": self._clock() + AUTOPSY_TTL_SECONDS,
            }
        )

    def _live(self, item: Doc | None) -> Doc | None:
        """TTL deletion can lag, so an expired item is treated as absent (SB-DATA-3)."""
        if item is None or int(item.get("ttl", 0)) <= self._clock():
            return None
        return item
