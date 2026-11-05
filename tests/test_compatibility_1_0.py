"""The published 0.49.0 file and documented Python calls remain usable."""

from pathlib import Path
from shutil import copyfile
import inspect
import json

import trikedb
from trikedb import TrikeDB


def test_published_0_49_0_public_python_signatures_remain_stable():
    fixture = Path(__file__).parent / "fixtures" / "public_api_0_49_0.json"
    contract = json.loads(fixture.read_text(encoding="utf-8"))
    assert list(trikedb.__all__) == contract["exports"]
    assert {
        name: str(inspect.signature(getattr(TrikeDB, name)))
        for name in contract["methods"]
    } == contract["methods"]


def test_published_0_49_0_file_and_python_api_round_trip(tmp_path):
    source = Path(__file__).parent / "fixtures" / "compat_0_49_0.yaml"
    path = tmp_path / "graph.yaml"
    copyfile(source, path)

    graph = TrikeDB(path, validate_on_load=True)
    assert graph.node("sales") == {
        "type": "service", "label": "Sales service", "owner": "example-team"
    }
    assert graph.node("orders") == {"type": "table", "pii": False}
    assert {(triple.s, triple.p, triple.o) for triple in graph.triples()} == {
        ("sales", "USES", "orders"),
        ("daily-refresh", "HAS_STEP", "extract"),
        ("daily-refresh", "HAS_STEP", "publish"),
        ("extract", "NEXT_STEP", "publish"),
    }
    assert list(graph.query(["?service USES orders"]))

    graph.add("publish", "PRODUCES", "report", prov="compatibility-test")
    graph.set_node("report", type="dataset", label="Daily report")
    graph.save()
    reopened = TrikeDB(path, validate_on_load=True)
    assert len(reopened) == 5
    assert reopened.node("report") == {"type": "dataset", "label": "Daily report"}
    assert list(reopened.triples(s="publish", p="PRODUCES", o="report"))
    assert list(reopened.query(["?workflow HAS_STEP extract", "extract NEXT_STEP publish"]))
