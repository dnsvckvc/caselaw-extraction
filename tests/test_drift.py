"""Drift check on the synthetic run (one decision per year: 2021, 2022, 2023)."""

from __future__ import annotations

import pytest

from caselaw_extraction import drift
from caselaw_extraction.store import DuckDBStore


@pytest.fixture
def store(synthetic_run):
    runs_dir, name = synthetic_run
    s = DuckDBStore(runs_dir / name)
    yield s
    s.close()


def test_distances():
    assert drift.js_distance({"a": 5, "b": 5}, {"a": 50, "b": 50}) == 0.0
    assert drift.js_distance({"a": 1}, {"b": 1}) == pytest.approx(1.0)
    assert drift.total_variation({"a": 1, "b": 1}, {"a": 1}) == pytest.approx(0.5)
    assert drift.js_distance({}, {}) == 0.0
    assert drift.quantile([0.1, 0.2, 0.3, 0.4], 0.5) == pytest.approx(0.25)


def test_periods(store):
    assert drift.decisions_per_period(store, "year") == {"2021": 1, "2022": 1, "2023": 1}
    months = drift.decisions_per_period(store, "month")
    assert {m[:4] for m in months} == {"2021", "2022", "2023"}
    assert all(len(m) == 7 and m[4] == "-" for m in months)
    statute = drift.period_counts(store, "statute", "year")
    assert "ZGB 8" in statute["2021"] or "OR 97" in statute["2021"]


def test_report_and_series(store):
    r = drift.drift_report(store, "2021", "2022", period="year")
    assert r["decisions_a"] == 1 and r["decisions_b"] == 1
    assert set(r["kinds"]) == set(drift.KINDS)
    outcome = r["kinds"]["outcome"]
    # dismissed in 2021, inadmissible in 2022: disjoint distributions
    assert outcome["js_distance"] == pytest.approx(1.0)
    assert outcome["movers"][0]["delta"] in (100.0, -100.0)
    label = r["kinds"]["label"]
    assert 0.0 <= label["js_distance"] <= 1.0
    series = drift.drift_series(store, "year", "statute")
    assert [(s["from"], s["to"]) for s in series] == [("2021", "2022"), ("2022", "2023")]
    with pytest.raises(ValueError):
        drift.drift_report(store, "2021", "1999", period="year")
    text = drift.format_drift(r)
    assert "outcome" in text and "2021" in text
    assert "steps" in drift.format_series(series, "statute")
