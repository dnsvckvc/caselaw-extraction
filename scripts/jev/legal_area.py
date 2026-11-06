"""Pilot, subproject 1: fill `legal_area` with Jev 1.14, against a TF-IDF baseline.

    uv run python scripts/jev/legal_area.py split            # fixed split -> data/pred/legal_area/split.json
    uv run python scripts/jev/legal_area.py baseline         # majority and TF-IDF on the test split
    op run --env-file scripts/jev/openrouter.op.env -- \
      uv run python scripts/jev/legal_area.py predict dev    # the prompt is checked on dev only
    op run --env-file scripts/jev/openrouter.op.env -- \
      uv run python scripts/jev/legal_area.py predict test   # one run after the prompt is frozen
    uv run python scripts/jev/legal_area.py report           # test metrics, calibration, MLflow

The labels are the dataset's `legal_area`, not gold. Classes with fewer than 20 decisions are
left out. The test split is 1,000 decisions, stratified by label, seed 0; the 100 dev decisions
come from the training part. Jev and the window baseline read the same first 6,000 characters.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.pipeline import make_pipeline

from caselaw_extraction import tracking

OUT = Path("data/pred/legal_area")
SPLIT = OUT / "split.json"
MODEL = "typesafe/jev-1.14"
URL = "https://openrouter.ai/api/alpha/decisions"
WINDOW = 6000
MAX_COST_USD = 1.0
MIN_CLASS = 20
WORKERS = 8

INSTRUCTIONS = (
    "Dies ist der Anfang eines Urteils des Schweizerischen Bundesgerichts in Zivilsachen. "
    "Welchem Rechtsgebiet ordnet das Bundesgericht dieses Verfahren zu? Achte vor allem auf "
    "den Abschnitt 'Gegenstand' und auf den Streit in der Sache."
)
CRITERIA = {
    "Schuldbetreibungs- und Konkursrecht": "Betreibung, Rechtsöffnung, Pfändung, Arrest, Konkurs, Kollokation (SchKG).",
    "Familienrecht": "Ehe, Scheidung, Eheschutz, Unterhalt, Obhut, Besuchsrecht, Kindes- und Erwachsenenschutz.",
    "Vertragsrecht": "Streit aus einem bestimmten Vertrag: Kauf, Miete, Arbeit, Werkvertrag, Auftrag, Versicherung.",
    "Sachenrecht": "Eigentum, Stockwerkeigentum, Nachbarrecht, Dienstbarkeiten, Bauhandwerkerpfandrecht.",
    "Erbrecht": "Nachlass, Testament, Erbteilung, Pflichtteil, Willensvollstreckung.",
    "Obligationenrecht (allgemein)": "Allgemeine Forderung nach OR ohne bestimmten Vertragstyp, Bereicherung, Verjährung.",
    "Gesellschaftsrecht": "Aktiengesellschaft, GmbH, Organisationsmangel, aktienrechtliche Verantwortlichkeit.",
    "Immaterialgüter-, Wettbewerbs- und Kartellrecht": "Marken, Patente, Urheberrecht, Design, unlauterer Wettbewerb, Kartellrecht.",
    "Personenrecht": "Persönlichkeitsschutz, Persönlichkeitsverletzung, Namensänderung, Vereine, Stiftungen.",
    "Schiedsgerichtsbarkeit": "Beschwerde gegen einen internationalen Schiedsentscheid (Art. 190 IPRG).",
    "Haftpflichtrecht": "Ausservertragliche Haftung, Schadenersatz, Genugtuung, Werkeigentümer, Motorfahrzeughalter.",
    "Register": "Handelsregister, Handelsregistersperre, Änderung oder Löschung von Registereinträgen.",
    "Zivilprozess": "Nur Binnenschiedsgerichtsbarkeit und Vollstreckbarerklärung. Nicht wählen bei einer Verfahrensfrage in einem Streit aus einem anderen Rechtsgebiet.",
}


def load() -> dict[str, tuple[str, str, int]]:
    """decision_id -> (label, full text, year) for the labelled decisions of the kept classes."""
    rows = duckdb.sql("""
        SELECT d.decision_id, d.legal_area, t.text, d.year
        FROM 'data/runs/regex-v0.4/decisions.parquet' d
        JOIN 'data/runs/texts.parquet' t USING (decision_id)
        WHERE d.legal_area IS NOT NULL
        ORDER BY d.decision_id
    """).fetchall()
    return {r[0]: (r[1], r[2], r[3]) for r in rows if r[1] in CRITERIA}


def split() -> None:
    data = load()
    ids = list(data)
    labels = [data[i][0] for i in ids]
    train, test = train_test_split(ids, test_size=1000, stratify=labels, random_state=0)
    rest, dev = train_test_split(
        train, test_size=100, stratify=[data[i][0] for i in train], random_state=0
    )
    OUT.mkdir(parents=True, exist_ok=True)
    SPLIT.write_text(json.dumps({"train": sorted(train), "dev": sorted(dev), "test": sorted(test)}))
    print(f"labelled {len(ids)}, train {len(train)} (of which dev {len(dev)}), test {len(test)}")


def tfidf(xs: list[str], ys: list[str]) -> GridSearchCV:
    pipe = make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, max_features=300_000),
        LogisticRegression(max_iter=2000, class_weight="balanced"),
    )
    grid = {"logisticregression__C": [1, 10, 100]}
    return GridSearchCV(pipe, grid, cv=3, scoring="f1_macro", n_jobs=4).fit(xs, ys)


def metrics(y: list[str], pred: list[str], conf: np.ndarray | None = None) -> dict[str, float]:
    m = {
        "accuracy": accuracy_score(y, pred),
        "macro_f1": f1_score(y, pred, average="macro", zero_division=0),
    }
    if conf is not None:
        right = np.array([a == b for a, b in zip(y, pred, strict=True)], dtype=float)
        bins = np.minimum((conf * 10).astype(int), 9)
        m["ece_top"] = sum(
            (bins == b).mean() * abs(right[bins == b].mean() - conf[bins == b].mean())
            for b in range(10)
            if (bins == b).any()
        )
    return m


def baseline() -> None:
    data = load()
    s = json.loads(SPLIT.read_text())
    y_tr = [data[i][0] for i in s["train"]]
    y_te = [data[i][0] for i in s["test"]]
    majority = max(set(y_tr), key=y_tr.count)
    results = {"majority": metrics(y_te, [majority] * len(y_te))}
    preds = {}
    for name, view in (("tfidf_window", lambda t: t[:WINDOW]), ("tfidf_full", lambda t: t)):
        t0 = time.time()
        gs = tfidf([view(data[i][1]) for i in s["train"]], y_tr)
        proba = gs.predict_proba([view(data[i][1]) for i in s["test"]])
        pred = gs.classes_[proba.argmax(1)].tolist()
        results[name] = metrics(y_te, pred, proba.max(1)) | {
            "C": gs.best_params_["logisticregression__C"],
            "seconds": time.time() - t0,
        }
        preds[name] = [
            {"decision_id": i, "pred": p, "conf": float(c)}
            for i, p, c in zip(s["test"], pred, proba.max(1), strict=True)
        ]
    # later decisions, unseen years: the missing labels are concentrated in 2026
    old = [i for i in s["train"] if data[i][2] < 2026]
    new = [i for i in s["test"] if data[i][2] == 2026]
    gs = tfidf([data[i][1][:WINDOW] for i in old], [data[i][0] for i in old])
    results["tfidf_window_trained_before_2026_on_2026"] = metrics(
        [data[i][0] for i in new], gs.predict([data[i][1][:WINDOW] for i in new]).tolist()
    ) | {"n": len(new)}
    (OUT / "baseline.json").write_text(json.dumps(results, indent=1))
    (OUT / "baseline-pred.json").write_text(json.dumps(preds))
    print(json.dumps(results, indent=1))


def decide(state: str, key: str) -> dict:
    body = {
        "model": MODEL,
        "state": {"urteil": state},
        "questions": {
            "legal_area": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": CRITERIA}
        },
    }
    req = urllib.request.Request(
        URL,
        json.dumps(body).encode(),
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    for attempt in range(5):
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                out = json.load(r)
            out["latency_s"] = time.time() - t0
            return out
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == 4:
                raise RuntimeError(f"HTTP {e.code}: {e.read()[:300]!r}") from None
        except (urllib.error.URLError, TimeoutError):
            if attempt == 4:
                raise
        time.sleep(2**attempt)
    raise AssertionError


def predict(part: str) -> None:
    key = os.environ["OPENROUTER_API_KEY"]
    data = load()
    ids = json.loads(SPLIT.read_text())[part]
    path = OUT / f"jev-1.14-{part}.jsonl"
    done = {}
    if path.exists():
        done = {json.loads(ln)["decision_id"]: 1 for ln in path.read_text().splitlines()}
    todo = [i for i in ids if i not in done]
    spent = (
        sum(json.loads(ln)["cost"] or 0 for ln in path.read_text().splitlines()) if done else 0.0
    )
    errors = 0

    def one(i: str) -> tuple[str, dict | None, str]:
        try:
            return i, decide(data[i][1][:WINDOW], key), ""
        except Exception as e:  # noqa: BLE001 - the error is counted and the id can be rerun
            return i, None, str(e)

    with path.open("a") as f, ThreadPoolExecutor(WORKERS) as pool:
        for n in range(0, len(todo), WORKERS * 5):
            if spent >= MAX_COST_USD:
                print(f"stopped at the spending cap, USD {spent:.4f}")
                break
            for i, r, err in pool.map(one, todo[n : n + WORKERS * 5]):
                if r is None:
                    errors += 1
                    print(i, err[:200])
                    continue
                a = r["answers"]["legal_area"]
                row = {
                    "decision_id": i,
                    "model": r.get("model"),
                    "type": a.get("type"),
                    "pred": a.get("choice"),
                    "confidence": a.get("confidence"),
                    "probabilities": a.get("probabilities"),
                    "input_tokens": r["usage"]["input_tokens"],
                    "cost": r["usage"].get("cost"),
                    "latency_s": r["latency_s"],
                }
                spent += row["cost"] or 0
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{min(n + WORKERS * 5, len(todo))}/{len(todo)} USD {spent:.4f}", flush=True)
    print(f"done, errors {errors}, USD {spent:.4f}")


def report(part: str = "test") -> None:
    data = load()
    rows = [json.loads(ln) for ln in (OUT / f"jev-1.14-{part}.jsonl").read_text().splitlines()]
    refused = [r for r in rows if r["pred"] is None]
    rows = [r for r in rows if r["pred"] is not None]
    y = [data[r["decision_id"]][0] for r in rows]
    pred = [r["pred"] for r in rows]
    top = np.array([max(r["probabilities"].values()) for r in rows])
    res = metrics(y, pred, top) | {
        "n": len(rows),
        "refused": len(refused),
        "usd_total": sum(r["cost"] or 0 for r in rows),
        "tokens_mean": float(np.mean([r["input_tokens"] for r in rows])),
        "latency_p50_s": float(np.median([r["latency_s"] for r in rows])),
        "latency_p95_s": float(np.percentile([r["latency_s"] for r in rows], 95)),
    }
    right = np.array([a == b for a, b in zip(y, pred, strict=True)])
    res["models"] = sorted({r["model"] for r in rows})
    print(json.dumps(res, indent=1))
    print("\ntop probability bin | n | mean probability | accuracy")
    edges = [0, 0.5, 0.7, 0.8, 0.9, 0.95, 1.0001]
    for lo, hi in zip(edges, edges[1:], strict=False):
        k = (top >= lo) & (top < hi)
        if k.any():
            print(
                f"{lo:.2f}-{min(hi, 1):.2f} | {k.sum()} | {top[k].mean():.3f} | {right[k].mean():.3f}"
            )
    print("\nthreshold | coverage | accuracy above it")
    for t in (0.5, 0.7, 0.8, 0.9, 0.95):
        k = top >= t
        print(f"{t} | {k.mean():.3f} | {right[k].mean() if k.any() else float('nan'):.3f}")
    print("\nclass | n | recall | precision")
    for c in CRITERIA:
        a = np.array(y) == c
        b = np.array(pred) == c
        print(
            f"{c} | {a.sum()} | {(a & b).sum() / max(a.sum(), 1):.2f} | {(a & b).sum() / max(b.sum(), 1):.2f}"
        )
    if part == "test" and (OUT / "baseline-pred.json").exists():
        base = {
            p["decision_id"]: p
            for p in json.loads((OUT / "baseline-pred.json").read_text())["tfidf_window"]
        }
        ids = [r["decision_id"] for r in rows]
        by = [right[n] and base[i]["pred"] != y[n] for n, i in enumerate(ids)]
        bn = [(not right[n]) and base[i]["pred"] == y[n] for n, i in enumerate(ids)]
        print(
            f"\nJev right and tfidf_window wrong: {sum(by)}; Jev wrong and tfidf_window right: {sum(bn)}"
        )
        rng = np.random.default_rng(0)
        bright = np.array([base[i]["pred"] == y[n] for n, i in enumerate(ids)])
        idx = rng.integers(0, len(ids), (2000, len(ids)))
        d = right[idx].mean(1) - bright[idx].mean(1)
        print(
            f"accuracy difference, Jev minus tfidf_window: {right.mean() - bright.mean():+.3f}, 95% bootstrap [{np.percentile(d, 2.5):+.3f}, {np.percentile(d, 97.5):+.3f}]"
        )
        years = np.array([data[i][2] for i in ids])
        for yr in sorted(set(years)):
            k = years == yr
            print(
                f"year {yr}: n {k.sum()}, Jev {right[k].mean():.3f}, tfidf_window {bright[k].mean():.3f}"
            )
        with tracking.run("jev-1.14-legal-area", {"model": MODEL, "window": WINDOW}) as log:
            log.metrics({k: v for k, v in res.items() if isinstance(v, int | float)})


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "split":
        split()
    elif cmd == "baseline":
        baseline()
    elif cmd == "predict":
        predict(sys.argv[2])
    elif cmd == "report":
        report(*sys.argv[2:])
    else:
        raise SystemExit(__doc__)
