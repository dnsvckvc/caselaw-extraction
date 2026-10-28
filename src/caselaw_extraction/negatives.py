"""Pre-annotator for the four negative classes of guideline v0.2.

CONTRACT_ARTICLE, BARE_ARTICLE, OTHER_LAW and JOURNAL_REF are references that look like
citations but link to nothing. This module proposes spans for them so that the labelling agents
correct rather than search. It is a pre-annotator, not an extractor: its recall is deliberately
wide and the agents decide. Spans that overlap an existing (citation) span are never proposed.
"""

from __future__ import annotations

import re

from caselaw_extraction.fedlex import resolve_code

WS = r"[  \n]"
_UNITS = (
    rf"(?:{WS}*(?:Abs\.|Absatz|Ziff\.|Ziffer|lit\.|Bst\.|Buchstabe|Satz|Nr\.){WS}*[\w]+"
    rf"(?:{WS}*(?:und|bis|,|-){WS}*[a-z\d]+)*)*"
)
_NUM = r"\d{1,4}[a-z]{0,6}"
_CHAIN = rf"(?:{WS}*(?:-|bis|und|sowie|,){WS}*(?:Art\.?{WS}*)?{_NUM}{_UNITS})*"
_ART_REF = re.compile(
    rf"(?<![A-Za-z\d])(?:Artikeln?|Art\.?|§§?){WS}*{_NUM}{_UNITS}{_CHAIN}(?:{WS}*(?:f\.|ff\.))?"
)
# "Ziff. 6 der AGB": a clause number alone is a span only when an instrument follows
_ZIFF_REF = re.compile(
    rf"(?<![A-Za-z\d])(?:Ziff\.|Ziffern?){WS}*{_NUM}(?:\.{_NUM})*{_UNITS}"
    rf"(?:{WS}*(?:und|i\.V\.m\.|,){WS}*(?:Ziff\.|Ziffern?){WS}*{_NUM}(?:\.{_NUM})*{_UNITS})*"
)

_INSTRUMENT_WORD = (
    rf"(?:AGB|AVB|AB|GAV|ABV|VVB|VSB(?:{WS}\d{{4}})?|GT{WS}\d+(?:{WS}[IVX]+)?(?:/GT{WS}\d+(?:{WS}[IVX]+)?)*"
    r"|Tarife|Vergleichs?|Vergleichsvereinbarung|Statuten|Reglement(?:s|es)?|Police|Konzession|Pflichtenheft"
    r"|(?i:\w*(?:vertrag|vertrags|vertrages|vereinbarung|abkommens?|agreements?|bedingungen"
    r"|reglement|reglements|reglementes|statuten|ordnung|ordnungen|tarife?s?)\b))"
)
_INSTRUMENT = re.compile(
    rf"{WS}*(?:(?:des|der|dieses|dieser|seines|ihres){WS}+(?:\w+{WS}+){{0,3}}?)?(?P<name>{_INSTRUMENT_WORD})"
)
_ABBREV = re.compile(
    rf"{WS}*(?P<abbr>a?[A-ZÄÖÜ][A-Za-zÄÖÜäöü]{{1,9}}(?:/[A-Z]{{2}})?(?:{WS}+\d{{4}}(?!\d))?)(?![A-Za-zäöü])"
)
_TITLE = re.compile(
    rf"{WS}*(?:des|der){WS}+(?:Bundesgesetzes|Gesetzes|Verordnung|Reglements|Bundesverfassung|Verfassung)"
)
# instruments are private law; these abbreviations are law codes even though Fedlex lacks them
_FOREIGN_CODES = {
    "BGB",
    "ZPO/ZH",
    "AEUV",
    "EUV",
    "CC",
    "CO",
    "HGB",
    "StPO/ZH",
    "GG",
    "ABGB",
    "UWG/EU",
}

_JOURNALS = (
    "SVR|Pra|SJ|ZBJV|ZR|sic!|AJP|PJA|SZZP|BlSchK|SJZ|plädoyer|JdT|SemJud|ZBl|SZW|GVP|BJM"
    r"|FamPra\.ch|FamPra|ZWR|RVJ|AGVE|LGVE|BVR|PKG|ZGRG|SZS|ARV|JAR|mp|MRA|SZIER|recht"
    "|Jusletter|ZSR|ZStrR|ASA|StR|RDAF|Rep|HAVE|REAS|EuGRZ|ZPR|CaS|CHK|BR/DC|BR|ZBGR|SZZP|ius.focus"
    "|AJP/PJA|Plädoyer|Anwaltsrevue|SJZ/RSJ|ZKE|RtiD|Pra."
)
JOURNAL_RE = re.compile(
    rf"(?<![\w.])(?P<j>{_JOURNALS}){WS}+(?:\d{{2,4}}(?:{WS}*\(\d{{4}}\))?|\d{{4}}){WS}*"
    rf"(?:[IVX]+{WS}+)?(?:(?:Nr\.|S\.|N|Rz\.|p\.){WS}*)?\d+[a-z]?"
)


def _overlaps(a: int, b: int, taken: list[tuple[int, int]]) -> bool:
    return any(x < b and a < y for x, y in taken)


def propose(text: str, taken_spans: list[dict], code_map: dict[str, str]) -> list[dict]:
    """Candidate negative spans that do not overlap `taken_spans` (the citation gold)."""
    taken = [(s["start"], s["end"]) for s in taken_spans]
    out: list[dict] = []
    for m in _ART_REF.finditer(text):
        a, b = m.start(), m.end()
        tail = text[b : b + 80]
        label, end = "BARE_ARTICLE", b
        mi = _INSTRUMENT.match(tail)
        ma = _ABBREV.match(tail)
        if mi:
            label, end = "CONTRACT_ARTICLE", b + mi.end()
        elif ma:
            abbr = ma.group("abbr")
            if resolve_code(abbr, code_map):
                continue  # a federal act: STATUTE territory, already in the citation gold
            if abbr in _FOREIGN_CODES or "/" in abbr or abbr.isupper():
                label, end = "OTHER_LAW", b + ma.end()
            else:
                label, end = "BARE_ARTICLE", b  # "Art. 8 Dieser Vertrag": the word is not a code
        elif _TITLE.match(tail):
            label, end = "BARE_ARTICLE", b
        if not re.search(r"\d", text[a:end]):
            continue
        if _overlaps(a, end, taken):
            continue
        out.append({"start": a, "end": end, "label": label, "text": text[a:end]})
        taken.append((a, end))
    for m in _ZIFF_REF.finditer(text):
        mi = _INSTRUMENT.match(text[m.end() : m.end() + 80])
        if not mi:
            continue
        a, end = m.start(), m.end() + mi.end()
        if _overlaps(a, end, taken):
            continue
        out.append({"start": a, "end": end, "label": "CONTRACT_ARTICLE", "text": text[a:end]})
        taken.append((a, end))
    for m in JOURNAL_RE.finditer(text):
        a, b = m.start(), m.end()
        if _overlaps(a, b, taken):
            continue
        out.append({"start": a, "end": b, "label": "JOURNAL_REF", "text": text[a:b]})
        taken.append((a, b))
    out.sort(key=lambda s: (s["start"], s["end"]))
    return out
