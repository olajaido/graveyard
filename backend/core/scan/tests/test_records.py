import json

from core.scan import records
from core.scan.tests.support import AS_OF, make_result, make_signals
from core.scoring import sort_results
from core.scoring.types import PathInfo
from core.scoring.v2 import score_package_v2


def _info(purl: str = "pkg:npm/left-pad@1.3.0") -> records.NodeInfo:
    return records.node_info_from_json(
        {
            "key": "npm/left-pad@1.3.0",
            "purl": purl,
            "manifests": ["."],
            "path_infos": [{"runtime": True, "direct": True}],
            "services_affected": 1,
            "example_paths": [{"service": ".", "nodes": ["npm/left-pad@1.3.0"]}],
        }
    )


def test_result_round_trip_is_stable_json() -> None:
    result = make_result()
    doc = records.result_to_json(result)
    assert json.loads(json.dumps(doc)) == doc
    back = records.result_from_json(json.loads(json.dumps(doc)))
    assert back == result


def test_signals_round_trip_with_missing_values() -> None:
    signals = make_signals(s7_advisories=None, s3_last_push_at=None, s5_committers=None)
    assert records.signals_from_json(records.signals_to_json(signals)) == signals


def test_node_info_direct_and_scope() -> None:
    info = _info()
    assert info.direct and info.scope == "runtime"
    dev = records.node_info_from_json(
        {
            "key": "k",
            "purl": "p",
            "manifests": [],
            "path_infos": [{"runtime": False, "direct": False}],
            "services_affected": 1,
        }
    )
    assert not dev.direct and dev.scope == "dev"


def test_scored_node_record_and_grave_rule() -> None:
    result = make_result(s1_declared_death=True)
    assert result.signals is not None
    signals = result.signals.__class__(
        **{**result.signals.__dict__, "paths": (PathInfo(True, True),), "services_affected": 1}
    )
    scoring = sort_results([score_package_v2(signals)])[0]
    record = records.build_node_record(
        _info(), as_of=AS_OF.isoformat(), model_version="v2", result=result, scoring=scoring
    )
    assert record["state"] == "dead" and record["deadReason"] == "declared"
    assert records.is_grave(record)
    assert set(record["evidence"]) and record["modelVersion"] == "v2"
    json.dumps(record)


def test_unscored_node_is_not_a_grave_and_is_counted() -> None:
    record = records.build_node_record(_info(), as_of=AS_OF.isoformat(), model_version="v2")
    assert record["state"] == "unscored" and not records.is_grave(record)
    counts = records.count_nodes(
        [record, {**record, "state": "alive"}, {**record, "state": "dead", "cursed": True}]
    )
    assert counts == {
        "total": 3,
        "alive": 1,
        "resting": 0,
        "ailing": 0,
        "dead": 1,
        "cursed": 1,
        "wounded": 0,
        "unscored": 1,
    }


def test_unknown_is_not_a_grave() -> None:
    assert not records.is_grave({"state": "unknown", "cursed": False, "wounded": False})


def test_alive_but_cursed_is_a_grave() -> None:
    assert records.is_grave({"state": "alive", "cursed": True, "wounded": False})
    assert not records.is_grave({"state": "alive", "cursed": False, "wounded": False})


def test_grave_order_is_priority_then_purl() -> None:
    items: list[dict[str, object]] = [
        {"purl": "b", "priority": 5.0},
        {"purl": "a", "priority": 5.0},
        {"purl": "c", "priority": 9.0},
        {"purl": "d", "priority": None},
    ]
    assert [i["purl"] for i in sorted(items, key=records.grave_sort_key)] == ["c", "a", "b", "d"]


def test_cursor_round_trip_and_rejects() -> None:
    assert records.decode_cursor(records.encode_cursor(150)) == 150
    for bad in ["", "!!!", "b2FiYw", "x" * 40, records.encode_cursor(0) + "A"]:
        assert records.decode_cursor(bad) is None
    import base64

    neg = base64.urlsafe_b64encode(b"o-1").decode()
    assert records.decode_cursor(neg) is None
