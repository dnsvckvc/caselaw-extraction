"""Shared fixtures: a three-decision synthetic corpus and a pipeline run over it."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from caselaw_extraction import corpus_run, graph

_HEADER = """Bundesgericht
Tribunal fédéral
Tribunale federale
Tribunal federal

{docket}

Urteil vom {date}

{chamber}

Besetzung
Bundesrichterin Hohl, Präsidentin,
Gerichtsschreiber Muster.

Verfahrensbeteiligte
A.________,
Beschwerdeführerin,

gegen

B.________ AG,
Beschwerdegegnerin.

Gegenstand
{subject},

Beschwerde gegen das Urteil des Obergerichts des Kantons Zürich vom 3. März {year}.

Sachverhalt:
"""

_RULING = """

Demnach erkennt das Bundesgericht:

1.
{ruling}

2.
Die Gerichtskosten von Fr. 2'000.-- werden der Beschwerdeführerin auferlegt (Art. 66 Abs. 1 BGG).
"""


def _decision(
    docket: str, date: str, year: int, chamber: str, subject: str, body: str, ruling: str
):
    text = _HEADER.format(docket=docket, date=date, chamber=chamber, subject=subject, year=year)
    text += body + _RULING.format(ruling=ruling)
    return {
        "decision_id": "bger_" + docket.replace("/", "_"),
        "docket_number": docket,
        "decision_date": f"{year}-{date.split('.')[1].strip():0>2}-{date.split('.')[0]:0>2}"
        if date[2:3] == "."
        else f"{year}-01-01",
        "chamber_text": chamber,
        "legal_area": subject,
        "outcome": None,
        "full_text": text,
        "text_length": len(text),
        "source_url": f"https://example.invalid/{docket}",
    }


DECISIONS = [
    _decision(
        "4A_1/2021",
        "5. Mai 2021",
        2021,
        "I. zivilrechtliche Abteilung",
        "Vertragsrecht",
        "A. Die Parteien schlossen einen Vertrag über Fr. 50'000.--. Die Beschwerdeführerin beruft "
        "sich auf Art. 8 ZGB und Art. 97 Abs. 1 OR. Nach der Rechtsprechung (BGE 140 III 86 E. 2, "
        "115 E. 2; Urteil 4A_12/2020 vom 1. Juni 2020 E. 3) trägt sie die Beweislast. Ziff. 4 des "
        "Vertrags ist nicht einschlägig.",
        "Die Beschwerde wird abgewiesen, soweit darauf einzutreten ist.",
    ),
    _decision(
        "5A_2/2022",
        "7. Juni 2022",
        2022,
        "II. zivilrechtliche Abteilung",
        "Familienrecht",
        "A. Streitig ist der Unterhalt von Fr. 1'200.-- im Monat. Gemäss Art. 8 ZGB und Art. 276 "
        "ZGB gilt die Beweislastregel (BGE 140 III 86 E. 2; BGE 142 III 364 E. 2.4). Die "
        "Beschwerdeführerin verweist auf das Urteil 4A_1/2021 vom 5. Mai 2021 E. 1.",
        "Auf die Beschwerde wird nicht eingetreten.",
    ),
    _decision(
        "4A_3/2023",
        "9. Juli 2023",
        2023,
        "I. zivilrechtliche Abteilung",
        "Vertragsrecht",
        "A. Die Beschwerdeführerin verlangt Fr. 10'000.-- Schadenersatz nach Art. 41 OR und Art. "
        "97 Abs. 1 OR (BGE 142 III 364 E. 2.4; Urteil 4A_1/2021 vom 5. Mai 2021 E. 2).",
        "Die Beschwerde wird gutgeheissen und das angefochtene Urteil aufgehoben.",
    ),
]


@pytest.fixture(scope="session")
def synthetic_corpus(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("corpus") / "corpus.parquet"
    pq.write_table(pa.Table.from_pylist(DECISIONS), path)
    return path


@pytest.fixture(scope="session")
def synthetic_run(synthetic_corpus: Path, tmp_path_factory) -> tuple[Path, str]:
    """(runs_dir, run name) of the regex pipeline over the synthetic corpus, with the graph."""
    runs_dir = tmp_path_factory.mktemp("runs")
    corpus_run.run_corpus(
        "synthetic", "regex", scheduler="sync", corpus=synthetic_corpus, runs_dir=runs_dir
    )
    graph.analyse_run("synthetic", runs_dir=runs_dir, html=False)
    return runs_dir, "synthetic"
