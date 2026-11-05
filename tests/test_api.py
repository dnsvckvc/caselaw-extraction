"""Contract test of the FastAPI service over the DuckDB backend (synthetic run)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(synthetic_run, monkeypatch):
    runs_dir, name = synthetic_run
    monkeypatch.setenv("CASELAW_BACKEND", "duckdb")
    monkeypatch.setenv("CASELAW_RUN", name)
    monkeypatch.setenv("CASELAW_RUNS_DIR", str(runs_dir))
    from caselaw_extraction.api import app

    with TestClient(app) as c:
        yield c


def test_health_and_runs(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["backend"] == "duckdb" and h["run_id"] == "synthetic"
    assert client.get("/runs").json() == [{"run_id": "synthetic", "extractor": "regex"}]


def test_decision_returns_citations_with_spans(client):
    r = client.get("/decisions/bger_4A_1_2021")
    assert r.status_code == 200
    d = r.json()
    assert d["docket_number"] == "4A_1/2021" and d["outcome"] == "dismissed"
    kinds = {c["kind"] for c in d["citations"]}
    assert kinds == {"statute", "bge", "docket"}
    first = d["citations"][0]
    assert set(first) == {"kind", "key", "code", "sr", "article", "target_decision_id", "span"}
    assert set(first["span"]) == {"start", "end", "label", "text"}
    labels = {s["label"] for s in d["spans"]}
    assert "AMOUNT" in labels and "PARTY_ROLE" in labels
    assert client.get("/decisions/does_not_exist").status_code == 404


def test_decision_filters(client):
    page = client.get("/decisions", params={"statute": "ZGB 8"}).json()
    assert page["total"] == 2
    assert {d["decision_id"] for d in page["items"]} == {"bger_4A_1_2021", "bger_5A_2_2022"}
    assert client.get("/decisions", params={"bge": "BGE 140 III 115"}).json()["total"] == 1
    assert client.get("/decisions", params={"docket": "4A_1/2021"}).json()["total"] == 2
    assert (
        client.get("/decisions", params={"docket": "4A_1_2021", "year": 2023}).json()["total"] == 1
    )
    assert client.get("/decisions", params={"outcome": "approved"}).json()["total"] == 1
    page = client.get("/decisions", params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 3 and len(page["items"]) == 1
    assert client.get("/decisions", params={"limit": 0}).status_code == 422


def test_analyses_endpoints(client):
    top = client.get("/statutes/top", params={"limit": 2}).json()
    assert top[0]["key"] == "BGG 66" and top[0]["decisions"] == 3
    codes = client.get("/statutes/codes").json()
    assert codes[0]["code"] == "BGG"
    years = client.get("/trends/years").json()
    assert [y["year"] for y in years] == [2021, 2022, 2023]
    share = client.get("/trends/code-share").json()
    assert share[0]["bgg"] == 100.0
    central = client.get("/decisions/central", params={"by": "in_degree", "limit": 1}).json()
    assert central[0]["in_degree"] == 2
    assert client.get("/decisions/central", params={"by": "degree"}).status_code == 422


def test_openapi_contract(client):
    spec = client.get("/openapi.json").json()
    assert set(spec["paths"]) == {
        "/health",
        "/runs",
        "/decisions",
        "/decisions/{decision_id}",
        "/decisions/{decision_id}/text",
        "/decisions/facets",
        "/decisions/central",
        "/graph/neighbors",
        "/statutes/top",
        "/statutes/codes",
        "/trends/years",
        "/trends/code-share",
        "/drift",
        "/drift/series",
    }
    schemas = spec["components"]["schemas"]
    assert {
        "DecisionOut",
        "CitationOut",
        "SpanOut",
        "StatuteCount",
        "YearTrend",
        "CentralNode",
    } <= set(schemas)
    assert schemas["CitationOut"]["required"] == ["kind", "key", "span"]


def test_drift_endpoints(client):
    r = client.get("/drift", params={"a": "2021", "b": "2022", "period": "year"})
    assert r.status_code == 200
    body = r.json()
    assert body["decisions_a"] == 1 and "statute" in body["kinds"]
    assert (
        client.get("/drift", params={"a": "2021", "b": "1999", "period": "year"}).status_code == 404
    )
    series = client.get("/drift/series", params={"period": "year"}).json()
    assert len(series) == 2 and set(series[0]) >= {"from", "to", "js_distance"}
    assert client.get("/drift/series", params={"period": "week"}).status_code == 422


def test_aggregate_endpoints_are_cacheable(client):
    r = client.get("/statutes/top?limit=5")
    assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=3600"
    assert client.get("/statutes/top?limit=5").json() == r.json()
    assert "cache-control" not in client.get("/decisions?limit=1").headers


def test_facets_follow_the_decision_filters(client):
    f = client.get("/decisions/facets").json()
    assert f["total"] == 3
    assert [(r["value"], r["decisions"]) for r in f["year"]] == [(2021, 1), (2022, 1), (2023, 1)]
    assert sum(r["decisions"] for r in f["outcome"]) == 3
    assert {r["value"] for r in f["chamber"]} == {
        "I. zivilrechtliche Abteilung",
        "II. zivilrechtliche Abteilung",
    }
    f = client.get("/decisions/facets", params={"statute": "ZGB 8"}).json()
    assert f["total"] == client.get("/decisions", params={"statute": "ZGB 8"}).json()["total"]
    assert [r["value"] for r in f["year"]] == [2021, 2022]
    assert "cache-control" in client.get("/decisions/facets").headers


def test_decision_text_matches_span_offsets(client):
    d = client.get("/decisions/bger_4A_1_2021").json()
    t = client.get("/decisions/bger_4A_1_2021/text").json()
    assert t["decision_id"] == "bger_4A_1_2021" and t["length"] == len(t["text"])
    for s in d["spans"]:
        assert t["text"][s["start"] : s["end"]] == s["text"]
    assert client.get("/decisions/does_not_exist/text").status_code == 404


def test_graph_neighbors(client):
    # 4A_1/2021 is cited by the two later decisions and cites one BGE pair and one file number
    n = client.get("/graph/neighbors", params={"node": "bger_4A_1_2021"}).json()
    assert n["node"]["kind"] == "decision" and n["node"]["year"] == 2021
    assert {r["node"] for r in n["cited_by"]} == {"bger_5A_2_2022", "bger_4A_3_2023"}
    assert n["in_degree"] == 2
    cites = {r["node"]: r["kind"] for r in n["cites"]}
    assert cites["bge:BGE 140 III 86"] == "bge" and cites["docket:4A_12_2020"] == "docket"
    assert all(r["pagerank"] is not None for r in n["cited_by"])
    # a BGE node: cited by, nothing cited
    b = client.get("/graph/neighbors", params={"node": "bge:BGE 142 III 364"}).json()
    assert b["node"]["kind"] == "bge" and b["cites"] == []
    assert {r["node"] for r in b["cited_by"]} == {"bger_5A_2_2022", "bger_4A_3_2023"}
    assert b["in_degree"] == 2
    # limit applies per direction; unknown nodes are 404
    assert (
        len(
            client.get("/graph/neighbors", params={"node": "bger_4A_1_2021", "limit": 1}).json()[
                "cited_by"
            ]
        )
        == 1
    )
    assert client.get("/graph/neighbors", params={"node": "bge:BGE 1 I 1"}).status_code == 404
    assert client.get("/graph/neighbors", params={"node": "nope"}).status_code == 404
