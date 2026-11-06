"""Citation graph and the three headline analyses over a run.

1. most-cited statutes: articles and acts by the number of citing decisions
2. trend by year: citations per decision by kind, the share of decisions citing the main
   codes, and the age of the cited BGE volumes
3. most central decisions: in-degree and PageRank over the decision-to-decision graph

The graph nodes are the corpus decisions, the cited BGE (by `BGE vol part page`) and the cited
file numbers that are not in the corpus. An edge is "decision A cites B", one per (A, B) pair.
The centrality table is written next to the run tables so that the API can serve it from
either backend. It holds two variants of the graph: `all`, and `no_routine` without the
citations that Jev 1.14 labelled `routine_standard` (`citation_treatment`, see treatment.py).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import networkx as nx
import pyarrow as pa
import pyarrow.parquet as pq

from caselaw_extraction.corpus_run import RUNS_DIR
from caselaw_extraction.store import DuckDBStore, Store

BGE_FIRST_YEAR = 1874  # BGE volume 1 is 1875; volume 146 is 2020
MAIN_CODES = ("BGG", "ZPO", "ZGB", "OR", "SchKG", "BV")

VARIANTS = ("all", "no_routine")
CENTRALITY_SCHEMA = pa.schema(
    [
        ("variant", pa.string()),  # all | no_routine
        ("node", pa.string()),
        ("kind", pa.string()),  # decision | bge | docket
        ("key", pa.string()),
        ("decision_id", pa.string()),  # set when the node is a corpus decision
        ("in_degree", pa.int32()),  # distinct citing decisions
        ("out_degree", pa.int32()),
        ("pagerank", pa.float64()),
        ("rank_pagerank", pa.int32()),
        ("rank_in_degree", pa.int32()),
    ]
)


def not_routine(alias: str = "c") -> str:
    """SQL condition: the citation `alias` is not labelled routine. A citation without a label
    counts as not routine. The one definition of the API's routine selector."""
    return (
        f"NOT EXISTS (SELECT 1 FROM citation_treatment t WHERE t.run_id = {alias}.run_id "
        f"AND t.span_id = {alias}.span_id AND t.label = 'routine_standard')"
    )


# --- analysis 1: most-cited statutes ----------------------------------------------------------


def top_statutes(
    store: Store, limit: int = 20, year: int | None = None, code: str | None = None
) -> list[dict[str, Any]]:
    where = "c.kind = 'statute' AND c.run_id = ?"
    params: list[Any] = [store.run_id]
    if year:
        where += " AND d.year = ?"
        params.append(year)
    if code:
        where += " AND (c.code = ? OR c.sr = ?)"
        params += [code, code]
    params.append(limit)
    return store.query(
        f"""
        SELECT c.key, c.code, c.sr, c.article,
               count(*) AS mentions, count(DISTINCT c.decision_id) AS decisions
        FROM citation c JOIN decision d ON d.run_id = c.run_id AND d.decision_id = c.decision_id
        WHERE {where}
        GROUP BY c.key, c.code, c.sr, c.article
        ORDER BY decisions DESC, mentions DESC, c.key
        LIMIT ?
        """,
        tuple(params),
    )


def top_codes(store: Store, limit: int = 15) -> list[dict[str, Any]]:
    return store.query(
        """
        SELECT c.code, c.sr, count(*) AS mentions, count(DISTINCT c.decision_id) AS decisions,
               count(DISTINCT c.key) AS articles
        FROM citation c
        WHERE c.kind = 'statute' AND c.run_id = ?
        GROUP BY c.code, c.sr
        ORDER BY decisions DESC, mentions DESC
        LIMIT ?
        """,
        (store.run_id, limit),
    )


# --- analysis 2: trend by year ------------------------------------------------------------------


def trend_by_year(store: Store, exclude_routine: bool = False) -> list[dict[str, Any]]:
    """One row per year: decisions, citations per decision by kind, distinct BGE cited, mean
    age of the cited BGE volumes (citing year minus volume year). With `exclude_routine`, the
    BGE and file-number figures leave out citations labelled routine."""
    keep = f" AND {not_routine('c')}" if exclude_routine else ""
    return store.query(
        f"""
        WITH per_decision AS (
            SELECT d.decision_id, d.year,
                   sum(CASE WHEN c.kind = 'statute' THEN 1 ELSE 0 END) AS n_statute,
                   sum(CASE WHEN c.kind = 'bge'{keep} THEN 1 ELSE 0 END) AS n_bge,
                   sum(CASE WHEN c.kind = 'docket'{keep} THEN 1 ELSE 0 END) AS n_docket
            FROM decision d LEFT JOIN citation c
                 ON c.run_id = d.run_id AND c.decision_id = d.decision_id
            WHERE d.run_id = ?
            GROUP BY d.decision_id, d.year
        ),
        bge_age AS (
            SELECT d.year,
                   avg(d.year - (cast(split_part(c.key, ' ', 2) AS integer) + ?)) AS mean_bge_age,
                   count(DISTINCT c.key) AS distinct_bge
            FROM citation c JOIN decision d ON d.run_id = c.run_id AND d.decision_id = c.decision_id
            WHERE c.kind = 'bge' AND c.run_id = ?{keep}
            GROUP BY d.year
        )
        SELECT p.year, count(*) AS decisions,
               round(avg(p.n_statute), 2) AS statute_per_decision,
               round(avg(p.n_bge), 2) AS bge_per_decision,
               round(avg(p.n_docket), 2) AS docket_per_decision,
               max(b.distinct_bge) AS distinct_bge,
               round(max(b.mean_bge_age), 1) AS mean_bge_age
        FROM per_decision p LEFT JOIN bge_age b ON b.year = p.year
        GROUP BY p.year
        ORDER BY p.year
        """,
        (store.run_id, BGE_FIRST_YEAR, store.run_id),
    )


def code_share_by_year(store: Store, codes: tuple[str, ...] = MAIN_CODES) -> list[dict[str, Any]]:
    """Share of the year's decisions that cite each code at least once."""
    marks = ", ".join(
        f"round(100.0 * count(DISTINCT CASE WHEN c.code = '{code}' THEN c.decision_id END) "
        f"/ count(DISTINCT d.decision_id), 1) AS {code.lower()}"
        for code in codes
    )
    return store.query(
        f"""
        SELECT d.year, count(DISTINCT d.decision_id) AS decisions, {marks}
        FROM decision d LEFT JOIN citation c
             ON c.run_id = d.run_id AND c.decision_id = d.decision_id AND c.kind = 'statute'
        WHERE d.run_id = ?
        GROUP BY d.year ORDER BY d.year
        """,
        (store.run_id,),
    )


# --- analysis 3: most central decisions ---------------------------------------------------------


def build_graph(store: Store, exclude_routine: bool = False) -> nx.DiGraph:
    """Decision-to-decision graph. Node ids: a corpus decision id, `bge:<key>` or
    `docket:<key>` (a cited file number outside the corpus). With `exclude_routine`, an edge
    A -> B exists only if at least one citation from A to B is not labelled routine."""
    g = nx.DiGraph()
    for r in store.query(
        "SELECT decision_id, year, outcome FROM decision WHERE run_id = ?", (store.run_id,)
    ):
        g.add_node(r["decision_id"], kind="decision", key=r["decision_id"], year=r["year"])
    keep = f" AND {not_routine('c')}" if exclude_routine else ""
    rows = store.query(
        f"""
        SELECT DISTINCT decision_id, kind, key, target_decision_id
        FROM citation c WHERE kind IN ('bge', 'docket') AND run_id = ?{keep}
        """,
        (store.run_id,),
    )
    for r in rows:
        if r["kind"] == "bge":
            target = f"bge:{r['key']}"
            g.add_node(target, kind="bge", key=r["key"])
        elif r["target_decision_id"]:
            target = r["target_decision_id"]
        else:
            target = f"docket:{r['key']}"
            g.add_node(target, kind="docket", key=r["key"])
        if target != r["decision_id"]:
            g.add_edge(r["decision_id"], target)
    return g


def centrality_table(g: nx.DiGraph, variant: str = "all") -> list[dict[str, Any]]:
    pr = nx.pagerank(g, alpha=0.85)
    rows = []
    for node, data in g.nodes(data=True):
        rows.append(
            {
                "variant": variant,
                "node": node,
                "kind": data["kind"],
                "key": data["key"],
                "decision_id": node if data["kind"] == "decision" else None,
                "in_degree": g.in_degree(node),
                "out_degree": g.out_degree(node),
                "pagerank": pr[node],
            }
        )
    for field, rank_field in (("pagerank", "rank_pagerank"), ("in_degree", "rank_in_degree")):
        for i, r in enumerate(sorted(rows, key=lambda r: -r[field]), start=1):
            r[rank_field] = i
    return rows


def write_centrality(run_dir: Path, rows: list[dict[str, Any]]) -> Path:
    out = run_dir / "centrality.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=CENTRALITY_SCHEMA), out, compression="zstd")
    return out


def central_decisions(
    store: Store,
    limit: int = 20,
    by: str = "pagerank",
    kind: str | None = None,
    variant: str = "all",
) -> list[dict[str, Any]]:
    order = "pagerank" if by == "pagerank" else "in_degree"
    where = "WHERE run_id = ? AND variant = ?" + (" AND kind = ?" if kind else "")
    params: tuple[Any, ...] = (store.run_id, variant, *([kind] if kind else []), limit)
    return store.query(
        f"""
        SELECT node, kind, key, decision_id, in_degree, out_degree, pagerank,
               rank_pagerank, rank_in_degree
        FROM centrality {where}
        ORDER BY {order} DESC, node
        LIMIT ?
        """,
        params,
    )


# --- visualisation ------------------------------------------------------------------------------


def export_html(g: nx.DiGraph, rows: list[dict[str, Any]], out: Path, top: int = 150) -> Path:
    """Static HTML of the subgraph around the `top` nodes by PageRank (pyvis / vis-network)."""
    from pyvis.network import Network

    keep = {r["node"] for r in sorted(rows, key=lambda r: -r["pagerank"])[:top]}
    sub = g.subgraph(keep)
    by_node = {r["node"]: r for r in rows}
    colors = {"decision": "#4C78A8", "bge": "#F58518", "docket": "#9D9D9D"}
    net = Network(height="800px", width="100%", directed=True, cdn_resources="in_line")
    for node, data in sub.nodes(data=True):
        r = by_node[node]
        net.add_node(
            node,
            label=data["key"],
            title=f"{data['kind']} {data['key']}: cited by {r['in_degree']}, "
            f"PageRank rank {r['rank_pagerank']}",
            color=colors[data["kind"]],
            size=8 + 2 * (r["in_degree"] ** 0.5),
        )
    for a, b in sub.edges():
        net.add_edge(a, b, color="#CCCCCC")
    net.toggle_physics(True)
    out.parent.mkdir(parents=True, exist_ok=True)
    net.write_html(str(out), open_browser=False, notebook=False)
    return out


# --- driver -------------------------------------------------------------------------------------


def format_table(rows: list[dict[str, Any]], cols: list[str] | None = None) -> str:
    if not rows:
        return "(no rows)"
    cols = cols or list(rows[0].keys())
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c)
            cells.append(f"{v:.5f}" if isinstance(v, float) and c == "pagerank" else str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def analyse_run(name: str, runs_dir: Path = RUNS_DIR, html: bool = True) -> dict[str, Any]:
    """Build the graph, write the centrality table (and the HTML), and return the three
    analyses as tables. Also writes `analyses.json` into the run directory."""
    run_dir = runs_dir / name
    store = DuckDBStore(run_dir)
    g = build_graph(store)
    rows = centrality_table(g)
    g_kept = build_graph(store, exclude_routine=True)
    write_centrality(run_dir, rows + centrality_table(g_kept, "no_routine"))
    store.close()
    store = DuckDBStore(run_dir)  # pick up the new centrality view
    out: dict[str, Any] = {
        "graph": {
            "nodes": g.number_of_nodes(),
            "edges": g.number_of_edges(),
            "nodes_by_kind": dict(
                sorted(Counter(d["kind"] for _, d in g.nodes(data=True)).items())
            ),
            "edges_no_routine": g_kept.number_of_edges(),
        },
        "top_statutes": top_statutes(store, 20),
        "top_codes": top_codes(store, 15),
        "trend_by_year": trend_by_year(store),
        "code_share_by_year": code_share_by_year(store),
        "central_pagerank": central_decisions(store, 20, "pagerank"),
        "central_in_degree": central_decisions(store, 20, "in_degree"),
        "central_corpus_decisions": central_decisions(store, 10, "in_degree", kind="decision"),
    }
    if html:
        out["html"] = str(export_html(g, rows, run_dir / "graph.html"))
    store.close()
    (run_dir / "analyses.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False, default=str)
    )
    return out


def format_analyses(a: dict[str, Any]) -> str:
    parts = [
        f"graph: {a['graph']['nodes']} nodes ({a['graph']['nodes_by_kind']}), "
        f"{a['graph']['edges']} edges",
        "\n## Most-cited statute articles (by citing decisions)\n",
        format_table(a["top_statutes"], ["key", "sr", "decisions", "mentions"]),
        "\n## Most-cited acts\n",
        format_table(a["top_codes"], ["code", "sr", "decisions", "mentions", "articles"]),
        "\n## Trend by year\n",
        format_table(a["trend_by_year"]),
        "\n## Share of decisions citing each code (percent)\n",
        format_table(a["code_share_by_year"]),
        "\n## Most central nodes by PageRank\n",
        format_table(
            a["central_pagerank"], ["kind", "key", "in_degree", "pagerank", "rank_in_degree"]
        ),
        "\n## Most cited corpus decisions (in-degree inside the corpus)\n",
        format_table(
            a["central_corpus_decisions"], ["key", "in_degree", "out_degree", "rank_pagerank"]
        ),
    ]
    if "html" in a:
        parts.append(f"\nHTML: {a['html']}")
    return "\n".join(parts)


# --- comparison of two runs ---------------------------------------------------------------------


def compare_runs(a: str, b: str, runs_dir: Path = RUNS_DIR, examples: int = 10) -> dict[str, Any]:
    """Edge-level agreement of two runs over the same corpus: for each citation kind, the keys
    (decision, key) found by both, by `a` only and by `b` only; and the overlap of the top-20
    statute and centrality lists."""
    import duckdb

    con = duckdb.connect()
    for alias, name in (("a", a), ("b", b)):
        con.execute(
            f"CREATE VIEW c_{alias} AS SELECT DISTINCT decision_id, kind, key "
            f"FROM read_parquet('{runs_dir / name / 'citations.parquet'}')"
        )
    rows = con.execute(
        """
        WITH u AS (
            SELECT coalesce(x.decision_id, y.decision_id) AS decision_id,
                   coalesce(x.kind, y.kind) AS kind, coalesce(x.key, y.key) AS key,
                   x.key IS NOT NULL AS in_a, y.key IS NOT NULL AS in_b
            FROM c_a x FULL OUTER JOIN c_b y
              ON x.decision_id = y.decision_id AND x.kind = y.kind AND x.key = y.key
        )
        SELECT kind, sum(CASE WHEN in_a AND in_b THEN 1 ELSE 0 END) AS both_,
               sum(CASE WHEN in_a AND NOT in_b THEN 1 ELSE 0 END) AS only_a,
               sum(CASE WHEN in_b AND NOT in_a THEN 1 ELSE 0 END) AS only_b
        FROM u GROUP BY kind ORDER BY kind
        """
    ).fetchall()
    kinds = {}
    for kind, both, only_a, only_b in rows:
        both, only_a, only_b = int(both), int(only_a), int(only_b)
        kinds[kind] = {
            "both": both,
            f"only_{a}": only_a,
            f"only_{b}": only_b,
            "jaccard": round(both / max(1, both + only_a + only_b), 4),
        }
    ex: dict[str, list] = {}
    for alias, other, label in (("a", "b", f"only_{a}"), ("b", "a", f"only_{b}")):
        ex[label] = con.execute(
            f"""
            SELECT x.kind, x.key, x.decision_id FROM c_{alias} x
            WHERE NOT EXISTS (SELECT 1 FROM c_{other} y WHERE y.decision_id = x.decision_id
                              AND y.kind = x.kind AND y.key = x.key)
            ORDER BY hash(x.decision_id || x.key) LIMIT ?
            """,
            [examples],
        ).fetchall()
    # top lists
    sa, sb = DuckDBStore(runs_dir / a), DuckDBStore(runs_dir / b)
    top_a = [r["key"] for r in top_statutes(sa, 20)]
    top_b = [r["key"] for r in top_statutes(sb, 20)]
    cen_a = (
        [r["node"] for r in central_decisions(sa, 20)]
        if (runs_dir / a / "centrality.parquet").exists()
        else []
    )
    cen_b = (
        [r["node"] for r in central_decisions(sb, 20)]
        if (runs_dir / b / "centrality.parquet").exists()
        else []
    )
    sa.close()
    sb.close()
    return {
        "runs": [a, b],
        "citations": kinds,
        "top20_statutes_shared": len(set(top_a) & set(top_b)),
        "top20_statutes_same_order": top_a == top_b,
        "top20_central_shared": len(set(cen_a) & set(cen_b)),
        "examples": ex,
    }


def format_comparison(c: dict[str, Any]) -> str:
    a, b = c["runs"]
    lines = [
        f"| kind | both | only {a} | only {b} | Jaccard |",
        "|---|---|---|---|---|",
    ]
    for kind, v in c["citations"].items():
        lines.append(
            f"| {kind} | {v['both']} | {v[f'only_{a}']} | {v[f'only_{b}']} | {v['jaccard']} |"
        )
    lines.append("")
    lines.append(
        f"top-20 statute articles shared: {c['top20_statutes_shared']} of 20 "
        f"(same order: {c['top20_statutes_same_order']}); "
        f"top-20 central nodes shared: {c['top20_central_shared']} of 20"
    )
    for label, rows in c["examples"].items():
        lines.append(f"\nexamples {label}:")
        lines += [f"  {kind:8s} {key:28s} {did}" for kind, key, did in rows]
    return "\n".join(lines)
