"""Read-only API over the extracted records (week 3).

The service reads one extraction run through a `Store`: Postgres in deployment, DuckDB over
the run's Parquet files for `make demo` and for the contract test. The backend is chosen by
`CASELAW_BACKEND`, `CASELAW_RUN` and `CASELAW_DSN` (see `store.open_store`).
"""

from __future__ import annotations

import contextlib
from collections import OrderedDict
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from caselaw_extraction import drift, graph
from caselaw_extraction.store import Store, open_store

API_VERSION = "0.1.0"


# --- response models -----------------------------------------------------------------------------


class Health(BaseModel):
    status: str
    backend: str
    run_id: str
    api_version: str


class RunOut(BaseModel):
    run_id: str
    extractor: str


class SpanOut(BaseModel):
    start: int
    end: int
    label: str
    text: str


class CitationOut(BaseModel):
    kind: str = Field(description="statute | bge | docket")
    key: str = Field(description="`OR 8`, `BGE 140 III 86` or a normalised file number")
    code: str | None = None
    sr: str | None = Field(None, description="Fedlex systematic number of the act")
    article: str | None = None
    target_decision_id: str | None = Field(
        None, description="set when the cited file number is a decision of this corpus"
    )
    span: SpanOut


class DecisionSummary(BaseModel):
    decision_id: str
    docket_number: str | None
    decision_date: str | None
    year: int | None
    chamber: str | None
    legal_area: str | None
    outcome: str | None = Field(None, description="outcome predicted by the extractor")
    outcome_dataset: str | None = Field(None, description="outcome label shipped with the data")
    n_spans: int | None
    source_url: str | None


class DecisionOut(DecisionSummary):
    citations: list[CitationOut]
    spans: list[SpanOut] = Field(description="all spans, including amounts and party roles")


class DecisionPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[DecisionSummary]


class StatuteCount(BaseModel):
    key: str
    code: str | None
    sr: str | None
    article: str | None
    decisions: int
    mentions: int


class CodeCount(BaseModel):
    code: str | None
    sr: str | None
    decisions: int
    mentions: int
    articles: int


class YearTrend(BaseModel):
    year: int
    decisions: int
    statute_per_decision: float | None
    bge_per_decision: float | None
    docket_per_decision: float | None
    distinct_bge: int | None
    mean_bge_age: float | None


class CentralNode(BaseModel):
    node: str
    kind: str
    key: str
    decision_id: str | None
    in_degree: int
    out_degree: int
    pagerank: float
    rank_pagerank: int
    rank_in_degree: int


class FacetCount(BaseModel):
    value: str | int | None
    decisions: int


class Facets(BaseModel):
    total: int
    year: list[FacetCount]
    outcome: list[FacetCount]
    chamber: list[FacetCount]


class DecisionText(BaseModel):
    decision_id: str
    length: int
    text: str


class Neighbor(BaseModel):
    node: str
    kind: str = Field(description="decision | bge | docket")
    key: str
    decision_id: str | None = None
    year: int | None = None
    outcome: str | None = None
    in_degree: int | None = Field(None, description="from the centrality table, when present")
    pagerank: float | None = None


class Neighbors(BaseModel):
    node: Neighbor
    in_degree: int = Field(description="number of citing decisions in the graph")
    out_degree: int
    cited_by: list[Neighbor] = Field(description="decisions that cite the node, most central first")
    cites: list[Neighbor] = Field(description="nodes the decision cites, most central first")


# --- app ----------------------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.store = open_store()
    warm_cache(app.state.store)
    yield
    app.state.store.close()


app = FastAPI(
    title="Case-law extraction API",
    version=API_VERSION,
    description=(
        "Citations (statute articles, BGE, file numbers), amounts, party roles and outcomes "
        "extracted from Swiss Federal Supreme Court decisions, with the citation graph's "
        "headline analyses. Read-only."
    ),
    lifespan=lifespan,
)


def get_store(request: Request) -> Store:
    return request.app.state.store


StoreDep = Annotated[Store, Depends(get_store)]


# The aggregate endpoints read a run that never changes while the service runs, so their
# results are cached in the process (the top-statutes aggregate costs about one second on a
# small server) and marked cacheable for clients and proxies.
_CACHE: OrderedDict[tuple, Any] = OrderedDict()
CACHE_MAX = 512
CACHE_CONTROL = "public, max-age=3600"


def _get_or_compute(store: Store, key: tuple, compute: Callable[[], Any]) -> Any:
    full = (store.backend, store.run_id, *key)
    if full in _CACHE:
        _CACHE.move_to_end(full)
        return _CACHE[full]
    value = compute()
    _CACHE[full] = value
    if len(_CACHE) > CACHE_MAX:
        _CACHE.popitem(last=False)
    return value


def cached(store: Store, response: Response, key: tuple, compute: Callable[[], Any]) -> Any:
    response.headers["Cache-Control"] = CACHE_CONTROL
    return _get_or_compute(store, key, compute)


def warm_cache(store: Store) -> None:
    """Fill the cache with the default views at startup, so the first visitor does not pay
    for the aggregates (about one second each on a small server). Off with CASELAW_WARM=0."""
    import os

    if os.environ.get("CASELAW_WARM", "1") == "0":
        return
    jobs: list[tuple[tuple, Callable[[], Any]]] = [
        (("statutes_top", 20, None, None), lambda: graph.top_statutes(store, 20, None, None)),
        (("codes", 20), lambda: graph.top_codes(store, 20)),
        (("trend_years",), lambda: graph.trend_by_year(store)),
        (("central", 20, "pagerank", None), lambda: graph.central_decisions(store, 20)),
    ]
    for key, compute in jobs:
        # a warm-up failure must not stop the service
        with contextlib.suppress(Exception):
            _get_or_compute(store, key, compute)


def _date(v: Any) -> str | None:
    return None if v is None else str(v)


def _summary(r: dict[str, Any]) -> DecisionSummary:
    return DecisionSummary(**{**r, "decision_date": _date(r.get("decision_date"))})


@app.get("/health", response_model=Health)
def health(store: StoreDep) -> Health:
    return Health(status="ok", backend=store.backend, run_id=store.run_id, api_version=API_VERSION)


@app.get("/runs", response_model=list[RunOut])
def runs(store: StoreDep) -> list[RunOut]:
    return [RunOut(**r) for r in store.query("SELECT run_id, extractor FROM extraction_run")]


@app.get("/decisions/central", response_model=list[CentralNode])
def central(
    store: StoreDep,
    response: Response,
    limit: int = Query(20, ge=1, le=200),
    by: str = Query("pagerank", pattern="^(pagerank|in_degree)$"),
    kind: str | None = Query(None, pattern="^(decision|bge|docket)$"),
) -> list[CentralNode]:
    """Most central nodes of the citation graph: cited BGE, cited file numbers and corpus
    decisions, by PageRank or by the number of citing decisions."""
    rows = cached(
        store,
        response,
        ("central", limit, by, kind),
        lambda: graph.central_decisions(store, limit, by, kind),
    )
    return [CentralNode(**r) for r in rows]


def _decision_where(
    store: Store,
    statute: str | None,
    bge: str | None,
    docket: str | None,
    year: int | None,
    outcome: str | None,
    chamber: str | None,
) -> tuple[str, list[Any]]:
    """WHERE clause (alias `d`) and parameters shared by `/decisions` and `/decisions/facets`."""
    where = ["d.run_id = ?"]
    params: list[Any] = [store.run_id]
    for kind, value in (("statute", statute), ("bge", bge), ("docket", docket)):
        if value:
            key = value.replace("/", "_").replace(".", "_") if kind == "docket" else value
            where.append(
                "EXISTS (SELECT 1 FROM citation c WHERE c.run_id = d.run_id "
                "AND c.decision_id = d.decision_id AND c.kind = ? AND c.key = ?)"
            )
            params += [kind, key]
    for col, value in (("year", year), ("outcome", outcome), ("chamber", chamber)):
        if value is not None:
            where.append(f"d.{col} = ?")
            params.append(value)
    return " AND ".join(where), params


@app.get("/decisions/facets", response_model=Facets)
def decision_facets(
    store: StoreDep,
    response: Response,
    statute: str | None = Query(None, description="citation key, e.g. `OR 8` or `BGG 42`"),
    bge: str | None = Query(None, description="`BGE 140 III 86`"),
    docket: str | None = Query(None, description="cited file number, `4A_12/2020` or `4A_12_2020`"),
    year: int | None = None,
    outcome: str | None = None,
    chamber: str | None = None,
) -> Facets:
    """Decision counts per year, outcome and chamber under the same filters as `/decisions`,
    for the facet chips of a browse page (one request instead of one per facet value)."""
    where, params = _decision_where(store, statute, bge, docket, year, outcome, chamber)

    def compute() -> dict[str, Any]:
        out: dict[str, Any] = {}
        for col in ("year", "outcome", "chamber"):
            rows = store.query(
                f"SELECT d.{col} AS value, count(*) AS decisions FROM decision d WHERE {where} "
                f"GROUP BY d.{col} ORDER BY d.{col}",
                tuple(params),
            )
            out[col] = [{"value": r["value"], "decisions": int(r["decisions"])} for r in rows]
        out["total"] = sum(r["decisions"] for r in out["year"])
        return out

    key = ("facets", statute, bge, docket, year, outcome, chamber)
    return Facets(**cached(store, response, key, compute))


@app.get("/decisions/{decision_id}/text", response_model=DecisionText)
def decision_text(decision_id: str, store: StoreDep, response: Response) -> DecisionText:
    """Full text of a decision (CC0 source data); span offsets of `/decisions/{id}` index it."""
    if not store.query(
        "SELECT 1 FROM decision WHERE run_id = ? AND decision_id = ?", (store.run_id, decision_id)
    ):
        raise HTTPException(404, f"decision {decision_id} is not in run {store.run_id}")
    rows = store.query("SELECT text FROM decision_text WHERE decision_id = ?", (decision_id,))
    if not rows:
        raise HTTPException(404, f"no text loaded for {decision_id} (caselaw db-load-texts)")
    response.headers["Cache-Control"] = CACHE_CONTROL
    text = rows[0]["text"]
    return DecisionText(decision_id=decision_id, length=len(text), text=text)


@app.get("/decisions/{decision_id}", response_model=DecisionOut)
def decision(decision_id: str, store: StoreDep) -> DecisionOut:
    rows = store.query(
        """
        SELECT decision_id, docket_number, decision_date, year, chamber, legal_area, outcome,
               outcome_dataset, n_spans, source_url
        FROM decision WHERE run_id = ? AND decision_id = ?
        """,
        (store.run_id, decision_id),
    )
    if not rows:
        raise HTTPException(404, f"decision {decision_id} is not in run {store.run_id}")
    spans = store.query(
        """
        SELECT span_id, start_char AS "start", end_char AS "end", label, text
        FROM span WHERE run_id = ? AND decision_id = ? ORDER BY start_char, end_char
        """,
        (store.run_id, decision_id),
    )
    by_span = {s["span_id"]: s for s in spans}
    cits = store.query(
        """
        SELECT span_id, kind, key, code, sr, article, target_decision_id
        FROM citation WHERE run_id = ? AND decision_id = ?
        """,
        (store.run_id, decision_id),
    )
    cits.sort(key=lambda c: (by_span[c["span_id"]]["start"], c["key"]))
    return DecisionOut(
        **_summary(rows[0]).model_dump(),
        citations=[
            CitationOut(
                **{k: v for k, v in c.items() if k != "span_id"}, span=_span(by_span[c["span_id"]])
            )
            for c in cits
        ],
        spans=[_span(s) for s in spans],
    )


def _span(s: dict[str, Any]) -> SpanOut:
    return SpanOut(start=s["start"], end=s["end"], label=s["label"], text=s["text"])


@app.get("/decisions", response_model=DecisionPage)
def decisions(
    store: StoreDep,
    statute: str | None = Query(None, description="citation key, e.g. `OR 8` or `BGG 42`"),
    bge: str | None = Query(None, description="`BGE 140 III 86`"),
    docket: str | None = Query(None, description="cited file number, `4A_12/2020` or `4A_12_2020`"),
    year: int | None = None,
    outcome: str | None = None,
    chamber: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> DecisionPage:
    """Decisions, filtered by what they cite and by their metadata. Newest first."""
    where, params = _decision_where(store, statute, bge, docket, year, outcome, chamber)
    rows = store.query(
        f"""
        SELECT d.decision_id, d.docket_number, d.decision_date, d.year, d.chamber, d.legal_area,
               d.outcome, d.outcome_dataset, d.n_spans, d.source_url, count(*) OVER () AS total
        FROM decision d
        WHERE {where}
        ORDER BY d.decision_date DESC, d.decision_id
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    )
    total = int(rows[0]["total"]) if rows else 0
    return DecisionPage(total=total, limit=limit, offset=offset, items=[_summary(r) for r in rows])


@app.get("/statutes/top", response_model=list[StatuteCount])
def statutes_top(
    store: StoreDep,
    response: Response,
    limit: int = Query(20, ge=1, le=500),
    year: int | None = None,
    code: str | None = Query(None, description="restrict to one act, by abbreviation or SR"),
) -> list[StatuteCount]:
    """Most-cited statute articles, by the number of citing decisions."""
    rows = cached(
        store,
        response,
        ("statutes_top", limit, year, code),
        lambda: graph.top_statutes(store, limit, year, code),
    )
    return [StatuteCount(**r) for r in rows]


@app.get("/statutes/codes", response_model=list[CodeCount])
def statutes_codes(
    store: StoreDep, response: Response, limit: int = Query(20, ge=1, le=500)
) -> list[CodeCount]:
    """Most-cited acts."""
    rows = cached(store, response, ("codes", limit), lambda: graph.top_codes(store, limit))
    return [CodeCount(**r) for r in rows]


@app.get("/trends/years", response_model=list[YearTrend])
def trends_years(store: StoreDep, response: Response) -> list[YearTrend]:
    """Citations per decision by kind and the age of the cited BGE volumes, per year."""
    rows = cached(store, response, ("trend_years",), lambda: graph.trend_by_year(store))
    return [YearTrend(**r) for r in rows]


@app.get("/drift/series", response_model=list[dict[str, Any]])
def drift_series(
    store: StoreDep,
    response: Response,
    period: str = Query("month", pattern="^(month|year)$"),
    kind: str = Query("statute", pattern="^(statute|bge|docket|code|outcome|label)$"),
) -> list[dict[str, Any]]:
    """Drift check: Jensen-Shannon and total-variation distance between each period and the
    one before it, over the whole run. The noise level for an alarm threshold."""
    return cached(
        store,
        response,
        ("drift_series", period, kind),
        lambda: drift.drift_series(store, period, kind),
    )


@app.get("/drift", response_model=dict[str, Any])
def drift_report(
    store: StoreDep,
    response: Response,
    a: str = Query(description="first period, `2025-09` or `2025`"),
    b: str = Query(description="second period"),
    period: str = Query("month", pattern="^(month|year)$"),
    top: int = Query(10, ge=1, le=100),
) -> dict[str, Any]:
    """Drift check: entity-frequency distributions of period `a` against period `b`, per kind,
    with the keys whose share of decisions moved most."""
    try:
        return cached(
            store,
            response,
            ("drift", a, b, period, top),
            lambda: drift.drift_report(store, a, b, period, top=top),
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/trends/code-share", response_model=list[dict[str, Any]])
def trends_code_share(store: StoreDep, response: Response) -> list[dict[str, Any]]:
    """Share of each year's decisions that cite BGG, ZPO, ZGB, OR, SchKG and BV, in percent."""
    return cached(
        store,
        response,
        ("code_share",),
        lambda: [
            {k: (float(v) if k not in ("year", "decisions") else int(v)) for k, v in r.items()}
            for r in graph.code_share_by_year(store)
        ],
    )


# --- citation graph -----------------------------------------------------------------------------

_NEIGHBOR_COLS = """
    n.node, n.kind, n.key, n.decision_id, d.year, d.outcome, c.in_degree, c.pagerank
"""


def _neighbor_rows(store: Store, nodes_sql: str, params: tuple[Any, ...], limit: int) -> list[dict]:
    """Enrich node ids (`nodes_sql` yields node, kind, key, decision_id) with the decision's
    year and outcome and the centrality values; most central first."""
    return store.query(
        f"""
        WITH n AS ({nodes_sql})
        SELECT {_NEIGHBOR_COLS}
        FROM n
        LEFT JOIN decision d ON d.run_id = ? AND d.decision_id = n.decision_id
        LEFT JOIN centrality c ON c.run_id = ? AND c.node = n.node
        ORDER BY c.pagerank DESC NULLS LAST, n.node
        LIMIT ?
        """,
        (*params, store.run_id, store.run_id, limit),
    )


@app.get("/graph/neighbors", response_model=Neighbors)
def graph_neighbors(
    store: StoreDep,
    response: Response,
    node: str = Query(
        description="graph node id: a corpus decision id (`bger_4A_12_2020`), "
        "`bge:BGE 140 III 115` or `docket:4A_12_2020` (a cited file number outside the corpus)"
    ),
    limit: int = Query(50, ge=1, le=500, description="neighbours per direction"),
) -> Neighbors:
    """One hop of the citation graph around a node: the decisions that cite it and, for a corpus
    decision, the BGE, file numbers and corpus decisions it cites. Same node ids as
    `/decisions/central`."""
    if node.startswith(("bge:", "docket:")):
        kind, _, key = node.partition(":")
    else:
        kind, key = "decision", node
    run = store.run_id
    if kind == "decision":
        rows = store.query(
            "SELECT decision_id, year, outcome FROM decision WHERE run_id = ? AND decision_id = ?",
            (run, node),
        )
        if not rows:
            raise HTTPException(404, f"decision {node} is not in run {run}")
        cited_by_sql = """
            SELECT DISTINCT decision_id AS node, 'decision' AS kind, decision_id AS key,
                   decision_id FROM citation
            WHERE run_id = ? AND kind = 'docket' AND target_decision_id = ?
        """
        cites_sql = """
            SELECT DISTINCT
                CASE WHEN kind = 'bge' THEN 'bge:' || key
                     WHEN target_decision_id IS NOT NULL THEN target_decision_id
                     ELSE 'docket:' || key END AS node,
                CASE WHEN kind = 'bge' THEN 'bge'
                     WHEN target_decision_id IS NOT NULL THEN 'decision'
                     ELSE 'docket' END AS kind,
                CASE WHEN target_decision_id IS NOT NULL THEN target_decision_id
                     ELSE key END AS key,
                target_decision_id AS decision_id
            FROM citation
            WHERE run_id = ? AND decision_id = ? AND kind IN ('bge', 'docket')
              AND (target_decision_id IS NULL OR target_decision_id <> decision_id)
        """
        cites = _neighbor_rows(store, cites_sql, (run, node), limit)
    else:
        cited_by_sql = """
            SELECT DISTINCT decision_id AS node, 'decision' AS kind, decision_id AS key,
                   decision_id FROM citation
            WHERE run_id = ? AND kind = ? AND key = ? AND target_decision_id IS NULL
        """
        cites = []
    cited_by = _neighbor_rows(
        store, cited_by_sql, (run, node) if kind == "decision" else (run, kind, key), limit
    )
    central = store.query(
        "SELECT in_degree, out_degree, pagerank FROM centrality WHERE run_id = ? AND node = ?",
        (run, node),
    )
    if kind != "decision" and not central and not cited_by:
        raise HTTPException(404, f"node {node} is not in the citation graph of run {run}")
    me = _neighbor_rows(
        store,
        "SELECT ? AS node, ? AS kind, ? AS key, ? AS decision_id",
        (node, kind, key, node if kind == "decision" else None),
        1,
    )[0]
    response.headers["Cache-Control"] = CACHE_CONTROL
    return Neighbors(
        node=Neighbor(**me),
        in_degree=int(central[0]["in_degree"]) if central else len(cited_by),
        out_degree=int(central[0]["out_degree"]) if central else len(cites),
        cited_by=[Neighbor(**r) for r in cited_by],
        cites=[Neighbor(**r) for r in cites],
    )
