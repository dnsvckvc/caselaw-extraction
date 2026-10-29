"""Drift check (week 4): compare the entity-frequency distributions of two periods.

A period is a month (`2025-09`) or a year (`2025`) of decision dates. For the citation kinds
the distribution of a period is the number of decisions that cite each key (statute article,
BGE, file number) or each act (`code`); for `outcome` it is the number of decisions per
outcome; for `label` the number of spans per span class. Two distributions are compared with
the Jensen-Shannon distance (0 identical, 1 disjoint, base-2) and the total variation distance
(half the L1 distance of the shares), and the keys whose share of decisions moved most are
listed. `drift_series` computes the distance between consecutive periods over the whole run,
which is the noise level an alarm threshold must exceed.

Every query goes through the `Store`, so the check runs on DuckDB over a run directory and on
Postgres with the same SQL.
"""

from __future__ import annotations

import math
from typing import Any

from caselaw_extraction.store import Store

KINDS = ("statute", "bge", "docket", "code", "outcome", "label")
PERIODS = ("month", "year")


def _period_sql(period: str) -> str:
    if period == "year":
        return "cast(d.year AS varchar)"
    if period == "month":
        return "substr(cast(d.decision_date AS varchar), 1, 7)"
    raise ValueError(f"period must be one of {PERIODS}, not {period!r}")


def _counts_sql(kind: str, period: str) -> str:
    p = _period_sql(period)
    join = "JOIN decision d ON d.run_id = x.run_id AND d.decision_id = x.decision_id"
    if kind in ("statute", "bge", "docket"):
        return (
            f"SELECT {p} AS period, x.key AS k, count(DISTINCT x.decision_id) AS n "
            f"FROM citation x {join} WHERE x.run_id = ? AND x.kind = '{kind}' GROUP BY 1, 2"
        )
    if kind == "code":
        return (
            f"SELECT {p} AS period, x.code AS k, count(DISTINCT x.decision_id) AS n "
            f"FROM citation x {join} WHERE x.run_id = ? AND x.kind = 'statute' "
            "AND x.code IS NOT NULL GROUP BY 1, 2"
        )
    if kind == "outcome":
        return (
            f"SELECT {p} AS period, coalesce(d.outcome, 'unknown') AS k, count(*) AS n "
            "FROM decision d WHERE d.run_id = ? GROUP BY 1, 2"
        )
    if kind == "label":
        return (
            f"SELECT {p} AS period, x.label AS k, count(*) AS n "
            f"FROM span x {join} WHERE x.run_id = ? GROUP BY 1, 2"
        )
    raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")


def period_counts(store: Store, kind: str, period: str = "month") -> dict[str, dict[str, int]]:
    """{period: {key: count}} for one kind over the whole run."""
    out: dict[str, dict[str, int]] = {}
    for r in store.query(_counts_sql(kind, period), (store.run_id,)):
        if r["period"] is None:
            continue
        out.setdefault(str(r["period"]), {})[str(r["k"])] = int(r["n"])
    return out


def decisions_per_period(store: Store, period: str = "month") -> dict[str, int]:
    p = _period_sql(period)
    rows = store.query(
        f"SELECT {p} AS period, count(*) AS n FROM decision d WHERE d.run_id = ? GROUP BY 1",
        (store.run_id,),
    )
    return {str(r["period"]): int(r["n"]) for r in rows if r["period"] is not None}


def _shares(counts: dict[str, int], keys: set[str]) -> dict[str, float]:
    total = sum(counts.values())
    return {k: (counts.get(k, 0) / total if total else 0.0) for k in keys}


def js_distance(p: dict[str, int], q: dict[str, int]) -> float:
    """Jensen-Shannon distance between two count distributions, base 2, in [0, 1]."""
    keys = set(p) | set(q)
    if not keys:
        return 0.0
    sp, sq = _shares(p, keys), _shares(q, keys)
    div = 0.0
    for k in keys:
        a, b, m = sp[k], sq[k], (sp[k] + sq[k]) / 2
        if a:
            div += 0.5 * a * math.log2(a / m)
        if b:
            div += 0.5 * b * math.log2(b / m)
    return math.sqrt(max(div, 0.0))


def total_variation(p: dict[str, int], q: dict[str, int]) -> float:
    keys = set(p) | set(q)
    sp, sq = _shares(p, keys), _shares(q, keys)
    return 0.5 * sum(abs(sp[k] - sq[k]) for k in keys)


def compare(
    a: dict[str, int], b: dict[str, int], n_a: int, n_b: int, top: int = 10
) -> dict[str, Any]:
    """Distances between two periods and the keys whose share of decisions moved most.
    Shares are in percent of the period's decisions (or spans, for `label`)."""
    keys = set(a) | set(b)
    movers = []
    for k in keys:
        share_a = 100.0 * a.get(k, 0) / n_a if n_a else 0.0
        share_b = 100.0 * b.get(k, 0) / n_b if n_b else 0.0
        movers.append(
            {
                "key": k,
                "n_a": a.get(k, 0),
                "n_b": b.get(k, 0),
                "share_a": round(share_a, 2),
                "share_b": round(share_b, 2),
                "delta": round(share_b - share_a, 2),
            }
        )
    movers.sort(key=lambda m: (-abs(m["delta"]), m["key"]))
    return {
        "js_distance": round(js_distance(a, b), 4),
        "total_variation": round(total_variation(a, b), 4),
        "distinct_a": len(a),
        "distinct_b": len(b),
        "new_in_b": sum(1 for k in b if k not in a),
        "gone_in_b": sum(1 for k in a if k not in b),
        "movers": movers[:top],
    }


def drift_report(
    store: Store,
    a: str,
    b: str,
    period: str = "month",
    kinds: tuple[str, ...] = KINDS,
    top: int = 10,
) -> dict[str, Any]:
    """Compare period `a` with period `b` for every kind."""
    dec = decisions_per_period(store, period)
    for x in (a, b):
        if x not in dec:
            raise ValueError(f"no decisions in {period} {x!r} of run {store.run_id}")
    kinds_out = {}
    for kind in kinds:
        pc = period_counts(store, kind, period)
        base_a = base_b = None
        if kind == "label":
            base_a, base_b = sum(pc.get(a, {}).values()), sum(pc.get(b, {}).values())
        kinds_out[kind] = compare(
            pc.get(a, {}), pc.get(b, {}), base_a or dec[a], base_b or dec[b], top
        )
    return {
        "run_id": store.run_id,
        "period": period,
        "a": a,
        "b": b,
        "decisions_a": dec[a],
        "decisions_b": dec[b],
        "kinds": kinds_out,
    }


def drift_series(store: Store, period: str = "month", kind: str = "statute") -> list[dict]:
    """Distance between each period and the one before it, over the whole run."""
    pc = period_counts(store, kind, period)
    dec = decisions_per_period(store, period)
    periods = sorted(dec)
    rows = []
    for prev, cur in zip(periods, periods[1:], strict=False):
        rows.append(
            {
                "from": prev,
                "to": cur,
                "decisions": dec[cur],
                "distinct_keys": len(pc.get(cur, {})),
                "js_distance": round(js_distance(pc.get(prev, {}), pc.get(cur, {})), 4),
                "total_variation": round(total_variation(pc.get(prev, {}), pc.get(cur, {})), 4),
            }
        )
    return rows


def quantile(values: list[float], q: float) -> float:
    """Linear-interpolated quantile; the alarm threshold is a high quantile of the series."""
    if not values:
        return 0.0
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def format_drift(report: dict[str, Any]) -> str:
    lines = [
        f"drift {report['run_id']}: {report['period']} {report['a']} ({report['decisions_a']} "
        f"decisions) -> {report['b']} ({report['decisions_b']} decisions)",
        "",
        f"{'kind':<8} {'JS dist':>8} {'TV dist':>8} {'keys a':>7} {'keys b':>7} "
        f"{'new':>5} {'gone':>5}",
    ]
    for kind, k in report["kinds"].items():
        lines.append(
            f"{kind:<8} {k['js_distance']:>8.3f} {k['total_variation']:>8.3f} "
            f"{k['distinct_a']:>7} {k['distinct_b']:>7} {k['new_in_b']:>5} {k['gone_in_b']:>5}"
        )
    for kind, k in report["kinds"].items():
        if not k["movers"]:
            continue
        lines += ["", f"{kind}: largest moves (share of decisions, percent)"]
        for m in k["movers"]:
            lines.append(
                f"  {m['key']:<28} {m['share_a']:>6.1f} -> {m['share_b']:>6.1f}  "
                f"({m['delta']:+.1f}; {m['n_a']} -> {m['n_b']})"
            )
    return "\n".join(lines)


def format_series(rows: list[dict], kind: str) -> str:
    js = [r["js_distance"] for r in rows]
    lines = [f"{'from':<8} {'to':<8} {'decisions':>9} {'keys':>6} {'JS dist':>8} {'TV dist':>8}"]
    for r in rows:
        lines.append(
            f"{r['from']:<8} {r['to']:<8} {r['decisions']:>9} {r['distinct_keys']:>6} "
            f"{r['js_distance']:>8.3f} {r['total_variation']:>8.3f}"
        )
    if js:
        lines += [
            "",
            f"{kind}: {len(js)} steps, JS distance median {quantile(js, 0.5):.3f}, "
            f"p95 {quantile(js, 0.95):.3f}, max {max(js):.3f}",
        ]
    return "\n".join(lines)
