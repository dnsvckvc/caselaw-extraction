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
    rows = store.query(
        f"""
        SELECT d.decision_id, d.docket_number, d.decision_date, d.year, d.chamber, d.legal_area,
               d.outcome, d.outcome_dataset, d.n_spans, d.source_url, count(*) OVER () AS total
        FROM decision d
        WHERE {" AND ".join(where)}
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
