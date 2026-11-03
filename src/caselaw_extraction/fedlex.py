"""Resolve statute abbreviations (ZGB, OR, BGG, ...) to Fedlex SR numbers.

The Fedlex SPARQL endpoint is public. Results are cached as JSON so that the pipeline does not
depend on the endpoint at run time.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

ENDPOINT = "https://fedlex.data.admin.ch/sparqlendpoint"
CACHE = Path("data/interim/fedlex_abbreviations.json")

QUERY = """
PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT DISTINCT ?abbr ?sr ?act ?title WHERE {
  ?act a jolux:ConsolidationAbstract ;
       jolux:classifiedByTaxonomyEntry/skos:notation ?sr ;
       jolux:isRealizedBy ?expr .
  ?expr jolux:language <http://publications.europa.eu/resource/authority/language/DEU> ;
        jolux:titleShort ?abbr .
  OPTIONAL { ?expr jolux:title ?title }
  FILTER(datatype(?sr) = <https://fedlex.data.admin.ch/vocabulary/notation-type/id-systematique>)
  FILTER(STRLEN(?abbr) <= 12)
}
"""

# Hand-checked core codes. They win over Fedlex when the two disagree, and they make the
# regex extractor work offline before the cache exists.
CORE_CODES: dict[str, str] = {
    "BV": "101",
    "EMRK": "0.101",
    "ZGB": "210",
    "OR": "220",
    "SchKG": "281.1",
    "IPRG": "291",
    "ZPO": "272",
    "BGG": "173.110",
    "VwVG": "172.021",
    "VGG": "173.32",
    "StGB": "311.0",
    "StPO": "312.0",
    "ATSG": "830.1",
    "AHVG": "831.10",
    "IVG": "831.20",
    "BVG": "831.40",
    "UVG": "832.20",
    "KVG": "832.10",
    "AVIG": "837.0",
    "VVG": "221.229.1",
    "URG": "231.1",
    "MSchG": "232.11",
    "PatG": "232.14",
    "UWG": "241",
    "KG": "251",
    "FusG": "221.301",
    "SVG": "741.01",
    "DBG": "642.11",
    "StHG": "642.14",
    "AIG": "142.20",
    "AsylG": "142.31",
    "BGFA": "935.61",
    "LugÜ": "0.275.12",
    "GBV": "211.432.1",
    "HRegV": "221.411",
    "VZAE": "142.201",
    "RPG": "700",
    "USG": "814.01",
    "DSG": "235.1",
    "BankG": "952.0",
    "FINMAG": "956.1",
    "KAG": "951.31",
    "BEHG": "954.1",
    "FIDLEG": "950.1",
    "FINIG": "954.1",
    "ArG": "822.11",
    "MWSTG": "641.20",
    "PartG": "211.231",
    "ELG": "831.30",
    "EOG": "834.1",
    "FamZG": "836.2",
    "FZG": "831.42",
    "OHG": "312.5",
    "BetmG": "812.121",
    "WG": "514.54",
    "BZP": "273",
    "VGKE": "173.320.2",
    "BGerR": "173.110.131",
    "IRSG": "351.1",
    "StBOG": "173.71",
    "VStrR": "313.0",
    "VStG": "642.21",
    "ZStV": "211.112.2",
    "KVV": "832.102",
    "UVV": "832.202",
    "AHVV": "831.101",
    "IVV": "831.201",
}


def fetch_abbreviations(timeout: float = 120.0) -> dict[str, dict[str, str]]:
    """Query Fedlex. Returns {abbr: {"sr": ..., "act": ..., "title": ...}}; first hit wins."""
    with httpx.Client(timeout=timeout) as client:
        r = client.get(
            ENDPOINT,
            params={"query": QUERY},
            headers={"Accept": "application/sparql-results+json"},
        )
        r.raise_for_status()
    out: dict[str, dict[str, str]] = {}
    for b in r.json()["results"]["bindings"]:
        abbr = b["abbr"]["value"].strip()
        if abbr in out:
            continue
        out[abbr] = {
            "sr": b["sr"]["value"],
            "act": b["act"]["value"],
            "title": b.get("title", {}).get("value", ""),
        }
    return out


def load_code_map(cache: Path = CACHE, refresh: bool = False) -> dict[str, str]:
    """Abbreviation -> SR number. Core codes override the Fedlex cache."""
    fedlex: dict[str, dict[str, str]] = {}
    if refresh or not cache.exists():
        try:
            fedlex = fetch_abbreviations()
        except httpx.HTTPError:
            fedlex = {}
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(fedlex, ensure_ascii=False, indent=1))
        except OSError:
            pass  # read-only working directory (the API image); the cache is a convenience
    else:
        fedlex = json.loads(cache.read_text())
    merged = {k: v["sr"] for k, v in fedlex.items()}
    merged.update(CORE_CODES)
    return merged


def resolve_code(code: str, known: dict[str, str]) -> tuple[str, str] | None:
    """Resolve the code part of a statute citation to (canonical abbreviation, SR number).

    The lookup order matters: the Fedlex list keys some treaties with a year (`EPÜ 2000`), so the
    full form is tried before the year is stripped; an `a` prefix marks an old version of the
    same act (`aVVG`); `SchlT ZGB` resolves to the act after the `SchlT` token.
    """
    code = " ".join(code.split())
    forms = [code]
    base = re.sub(r"\s+\d{4}$", "", code)
    if base != code:
        forms.append(base)
    forms += [f[1:] for f in list(forms) if f.startswith("a") and len(f) > 2]
    forms += [f.split()[-1] for f in list(forms) if " " in f]
    for f in forms:
        if f in known:
            return f, known[f]
    return None
