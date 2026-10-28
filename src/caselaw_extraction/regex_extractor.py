"""Rule-based extractor for German BGer decisions.

It serves two purposes: the pre-annotator for Label Studio and the first extractor in the
comparison. Every span is a character span into the original text.
"""

from __future__ import annotations

import re
from datetime import date

from caselaw_extraction.fedlex import resolve_code
from caselaw_extraction.schema import (
    Amount,
    BgeCitation,
    DecisionExtraction,
    DocketCitation,
    Header,
    Outcome,
    Span,
    SpanLabel,
    StatuteCitation,
)

VERSION = "regex-v0.4"  # guideline v0.3 rules; see docs/report.md section 5

SP = r"[  ]"  # texts mix normal and non-breaking spaces
WS = r"[ \u00a0\n]"  # inside a citation the source often wraps onto a new line

# --- statutes -----------------------------------------------------------------------------------
_ART_SUFFIX = (
    r"(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies|[a-z]{1,2})?(?![a-z])"
)
_ART_NUM = rf"\d{{1,4}}{_ART_SUFFIX}(?:-\d{{1,4}}{_ART_SUFFIX})?"
_ABS = (
    rf"(?:{WS}?Abs\.{WS}?\d{{1,3}}(?:bis|ter)?(?:-\d{{1,3}})?"
    rf"(?:{WS}?(?:,|und|bis|f\.|ff\.|oder){WS}?(?:Abs\.{WS}?)?\d{{1,3}}(?:bis|ter)?)*)?"
)
_SATZ = (
    rf"(?:{WS}?Satz{WS}?\d(?:{WS}?(?:und|bis){WS}?\d)?"
    rf"|{WS}?(?:erster|zweiter|dritter|vierter|letzter){WS}Satz)?"
)
_LIT_ITEM = r"[a-z0-9]{1,3}(?:bis|ter)?(?:-[a-z0-9]{1,3}(?:bis|ter)?)?"
_LIT = (
    rf"(?:{WS}?(?:lit\.|Bst\.|Ziff\.){WS}?{_LIT_ITEM}"
    rf"(?:{WS}?(?:,|und|bis|oder){WS}?(?:(?:lit\.|Bst\.|Ziff\.){WS}?)?{_LIT_ITEM})*)*"
)
_FF = rf"(?:{WS}?f{{1,2}}\.)?"
_UNIT = rf"{_ART_NUM}{_ABS}{_SATZ}{_LIT}{_ABS}{_FF}"
_ABS_ELEM = rf"Abs\.{WS}?\d{{1,3}}(?:bis|ter)?{_SATZ}{_LIT}{_FF}"
_SEP = rf"{WS}?(?:,|und|sowie|bzw\.|oder|i\.{WS}?V\.?{WS}?m\.|in{WS}Verbindung{WS}mit){WS}?"
# a four-digit year ("EPÜ 2000") is tried before a single digit, or the code would end at "EPÜ 2"
_CODE = (
    r"(?P<code>(?:SchlT{SP})?a?[A-ZÄÖÜ][A-Za-zÄÖÜäöü]{0,9}"
    r"(?:{SP}\d{4}(?!\d)|{SP}?\d)?(?:/[A-Z]{2})?)"
)
# v0.3: "Art" without the dot and a missing space before the code ("Art. 17SchKG") are accepted;
# the known-code check in extract_statutes keeps the German noun "Art" out.
STATUTE_RE = re.compile(
    rf"(?<![A-Za-z])(?P<old>a)?(?:Artikeln?|Art\.?){WS}?"
    rf"(?P<units>{_UNIT}(?:{_SEP}(?:(?:Art\.?{WS}?)?{_UNIT}|{_ABS_ELEM}))*)"
    rf"{WS}*{_CODE.replace('{SP}', SP)}(?![A-Za-zäöü])"
)
_UNIT_RE = re.compile(
    rf"(?P<art>{_ART_NUM})"
    rf"(?P<abs>{_ABS})(?P<satz>{_SATZ})(?P<lit>{_LIT})(?P<abs2>{_ABS})"
    rf"|(?P<absonly>{_ABS_ELEM})"  # inherits the article of the previous element
)
_ABS_NUM_RE = re.compile(r"Abs\.\s?(\d{1,3}(?:bis|ter)?)")
_LIT_RE = re.compile(r"(?:lit\.|Bst\.)\s?([a-z]{1,3}(?:-[a-z]{1,3})?)")
_ZIFF_RE = re.compile(r"Ziff\.\s?(\d{1,3})")

# --- BGE ----------------------------------------------------------------------------------------
_PART = r"(?:Ia|Ib|IV|V|III|II|I)"
BGE_RE = re.compile(rf"\bBGE{WS}(?P<vol>\d{{1,3}}){WS}(?P<part>{_PART}){WS}(?P<page>\d{{1,4}})\b")
_PIN = (
    rf"(?:{WS}?E\.?{WS}?[\d.a-z]+(?:{WS}?\[[^\]]{{0,20}}\])?(?:{WS}?(?:f\.|ff\.|und{WS}[\d.a-z]+))?)?"
    rf"(?:{WS}?S\.{WS}?\d+(?:{WS}?f{{1,2}}\.)?)?"
)
# a same-volume short citation (", 115 E. 2") sits between list items; guideline v0.1 gives it
# no span, but the chain must continue past it
_SHORT = rf"(?:{WS}?,{WS}?\d{{1,4}}{_PIN})*"
_PIN_RE = re.compile(_PIN)
# v0.4 (guideline v0.3, question 1): after a BGE citation and its pin cite, a bare page number
# followed by a consideration ("BGE 140 III 86 E. 2, 115 E. 2") cites another decision of the
# same volume and part. The span is the page number; volume and part are inherited.
_SHORT_CITE_RE = re.compile(rf"{WS}?[,;]{WS}?(?P<page>\d{{1,4}})(?={WS}?E\.?{WS}?\d)")
_BGE_CONT_RE = re.compile(
    rf"(?P<sep>{_PIN}{_SHORT}{WS}?[;,]{WS}?)"
    rf"(?P<vol>\d{{1,3}}){WS}(?P<part>{_PART}){WS}(?P<page>\d{{1,4}})\b"
)
_CONS_RE = re.compile(rf"^{WS}?(?:E\.|Erw\.){WS}?(?P<cons>\d+(?:\.\d+)*[a-z]?)")

# --- docket -------------------------------------------------------------------------------------
DOCKET_RE = re.compile(
    r"(?<![\w/.])(?P<docket>(?:[1-9][A-HP][._]|[A-Z]\.)\d{1,4}/ ?\d{4})(?![\w/])"
)

# --- amounts ------------------------------------------------------------------------------------
_MULT = rf"(?:{SP}?(?:Mio|Mrd)\.)?"
_DEC_COMMA = rf",\d{{1,2}}(?={SP}?(?:Mio|Mrd)\.)"  # "Fr. 2,3 Mio." (v0.3)
_NUM = rf"\d{{1,3}}(?:['’]\d{{3}})*(?:\.\d{{1,3}}|{_DEC_COMMA}|\.-{{1,2}}|\.–)?{_MULT}"
AMOUNT_RE = re.compile(
    rf"(?:(?P<cur1>Fr\.?|CHF|EUR|USD)(?![a-z]){SP}?(?P<num1>{_NUM})"
    rf"|(?P<num2>{_NUM}){SP}(?P<cur2>Franken))"
)

# --- header / rubrum ------------------------------------------------------------------------------
MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7,
    "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}  # fmt: skip
_DATE_RE = re.compile(rf"(?P<d>\d{{1,2}})\.{SP}(?P<m>[A-Za-zäöü]+){SP}(?P<y>\d{{4}})")
URTEIL_RE = re.compile(rf"(?:Urteil|Verfügung|Entscheid){SP}vom{SP}{_DATE_RE.pattern}")
CHAMBER_RE = re.compile(
    r"^(?P<ch>(?:I|II|III|IV)\.\s?(?:[Zz]ivil|[Öö]ffentlich|[Ss]traf|[Ss]ozial)[a-zäöü-]*\s?"
    r"(?:Abteilung|Kammer|Gerichtshof))",
    re.MULTILINE,
)
APPEAL_RE = re.compile(
    rf"Beschwerde{SP}gegen{SP}(?:den|das|die){SP}(?:Urteil|Entscheid|Beschluss|Verfügung|Zirkulationsbeschluss)"
    rf"{SP}(?:des|der){SP}(?P<court>[^,;\n(]+?){SP}vom{SP}{_DATE_RE.pattern}"
)
PARTY_ROLE_RE = re.compile(
    r"\b(?P<role>Beschwerdeführer(?:in(?:nen)?|n)?|Beschwerdegegner(?:in(?:nen)?|n)?|"
    r"Gesuchsteller(?:in(?:nen)?|n)?|Gesuchsgegner(?:in(?:nen)?|n)?|Kläger(?:in(?:nen)?|n)?|"
    r"Beklagte[rn]?|Berufungskläger(?:in)?|Berufungsbeklagte[rn]?|Nebenintervenient(?:in)?)\b"
)
RUBRUM_START = re.compile(r"Verfahrensbeteiligte|Parteien")
RUBRUM_END = re.compile(r"\nGegenstand\b")

# --- dispositiv -----------------------------------------------------------------------------------
# "Demnach erkennt das Bundesgericht:", "... der Präsident:", "... die Präsidentin:",
# "... das präsidierende Mitglied:", "... der Einzelrichter:", "Demnach verfügt ...:"
# Short single-judge rulings drop the "Demnach" and continue after a semicolon:
# "...entstanden ist (Art. 68 BGG);\n\nverfügt die Präsidentin:"
DISPOSITIV_RE = re.compile(
    r"(?:(?:Demnach\s+)?(?:erkennt|verfügt|beschliesst)\s+(?:das|der|die)\s+[^:\n]{0,40}"
    r"|Das\s+Bundesgericht\s+(?:erkennt|verfügt|beschliesst)):",
    re.IGNORECASE,
)
_OUTCOME_RULES: list[tuple[re.Pattern[str], Outcome]] = [
    (re.compile(r"teilweise\s+gutgeheissen|teilweise\s+gutzuheissen"), Outcome.PARTIAL_APPROVAL),
    (re.compile(r"gutgeheissen|Gutheissung"), Outcome.APPROVED),
    (re.compile(r"abgewiesen"), Outcome.DISMISSED),
    (re.compile(r"nicht\s+eingetreten"), Outcome.INADMISSIBLE),
    (re.compile(r"abgeschrieben|gegenstandslos"), Outcome.MOOT),
    (re.compile(r"aufgehoben|berichtigt|erläutert"), Outcome.APPROVED),
    (re.compile(r"vereinigt"), Outcome.CONSOLIDATED),
]
# Dispositiv items that decide a side request, not the appeal itself.
_SIDE_REQUEST_RE = re.compile(
    r"Sistierung|sistiert|vereinigt|Ausstand|unentgeltliche[nr]?\s+Rechtspflege|"
    r"Fristwiederherstellung|Wiederherstellung\s+der\s+Frist|"
    r"aufschiebende[nr]?\s+Wirkung|entgegengenommen|Verfahren\s+\S+\s+und\s+\S+\s+werden",
)


def _span(
    m: re.Match[str], label: SpanLabel, text: str, start: int | None = None, end: int | None = None
) -> Span:
    s = m.start() if start is None else start
    e = m.end() if end is None else end
    return Span(start=s, end=e, label=label, text=text[s:e])


def parse_german_date(m: re.Match[str]) -> date | None:
    month = MONTHS.get(m.group("m").lower())
    if month is None:
        return None
    try:
        return date(int(m.group("y")), month, int(m.group("d")))
    except ValueError:
        return None


def extract_header(text: str) -> Header:
    head = text[:1500]
    docket_m = DOCKET_RE.search(head)
    docket = docket_m.group("docket") if docket_m else "unknown"
    urteil = URTEIL_RE.search(head)
    chamber = CHAMBER_RE.search(head)
    appeal = APPEAL_RE.search(text[:6000])
    return Header(
        docket_number=docket,
        decision_date=parse_german_date(urteil) if urteil else None,
        chamber=chamber.group("ch").strip() if chamber else None,
        appealed_court=appeal.group("court").strip() if appeal else None,
        appealed_date=parse_german_date(appeal) if appeal else None,
    )


def extract_statutes(text: str, code_map: dict[str, str] | None = None) -> list[StatuteCitation]:
    out: list[StatuteCitation] = []
    known = set(code_map or {})
    for m in STATUTE_RE.finditer(text):
        code = m.group("code")
        toks = code.split()
        base_code = toks[0] if toks[-1].isdigit() else toks[-1]  # "SchlT ZGB"->ZGB, "EPÜ 2000"->EPÜ
        if known:
            hit = resolve_code(code, code_map or {})
            if hit is None:
                continue
            base_code = hit[0]
        span = _span(m, SpanLabel.STATUTE, text)
        article = ""
        for u in _UNIT_RE.finditer(m.group("units")):
            if u.group("absonly"):
                if not article:
                    continue
                abs_m = _ABS_NUM_RE.search(u.group("absonly"))
                lit_m = _LIT_RE.search(u.group("absonly"))
                ziff_m = _ZIFF_RE.search(u.group("absonly"))
            else:
                article = u.group("art")
                abs_m = _ABS_NUM_RE.search(u.group("abs") or "") or _ABS_NUM_RE.search(
                    u.group("abs2") or ""
                )
                lit_m = _LIT_RE.search(u.group("lit") or "")
                ziff_m = _ZIFF_RE.search(u.group("lit") or "")
            out.append(
                StatuteCitation(
                    span=span,
                    code=code,
                    article=article,
                    paragraph=abs_m.group(1) if abs_m else None,
                    letter=lit_m.group(1) if lit_m else None,
                    number=ziff_m.group(1) if ziff_m else None,
                    sr_number=(code_map or {}).get(base_code),
                )
            )
    return out


def extract_bge(text: str) -> list[BgeCitation]:
    out: list[BgeCitation] = []
    seen: set[tuple[int, int]] = set()
    for m in BGE_RE.finditer(text):
        pos = m.end()
        cons = _CONS_RE.match(text[pos : pos + 30])
        out.append(
            BgeCitation(
                span=_span(m, SpanLabel.BGE, text),
                volume=int(m.group("vol")),
                part=m.group("part"),
                page=int(m.group("page")),
                consideration=cons.group("cons") if cons else None,
            )
        )
        seen.add((m.start(), m.end()))
        vol, part = int(m.group("vol")), m.group("part")
        pos = _short_citations(text, pos, vol, part, out)
        # chained citations: "BGE 140 III 86 E. 2; 139 III 133 E. 1.1, 138 III 2"
        while True:
            c = _BGE_CONT_RE.match(text, pos)
            if not c:
                break
            s = c.start("vol")
            cons2 = _CONS_RE.match(text[c.end() : c.end() + 30])
            vol, part = int(c.group("vol")), c.group("part")
            out.append(
                BgeCitation(
                    span=Span(start=s, end=c.end(), label=SpanLabel.BGE, text=text[s : c.end()]),
                    volume=vol,
                    part=part,
                    page=int(c.group("page")),
                    consideration=cons2.group("cons") if cons2 else None,
                )
            )
            pos = _short_citations(text, c.end(), vol, part, out)
    return out


def _short_citations(text: str, pos: int, vol: int, part: str, out: list[BgeCitation]) -> int:
    """Emit same-volume short citations that follow the citation ending at `pos`; return the
    position after the last one (and its pin cite), or `pos` unchanged."""
    while True:
        pin = _PIN_RE.match(text, pos)
        if pin:
            pos = pin.end()
        sc = _SHORT_CITE_RE.match(text, pos)
        if not sc:
            return pos
        a, b = sc.start("page"), sc.end("page")
        cons = _CONS_RE.match(text[b : b + 30])
        out.append(
            BgeCitation(
                span=Span(start=a, end=b, label=SpanLabel.BGE, text=text[a:b]),
                volume=vol,
                part=part,
                page=int(sc.group("page")),
                consideration=cons.group("cons") if cons else None,
            )
        )
        pos = b


_HEADER_END_RE = re.compile(r"\n(?:Besetzung|Urteil vom|Verfügung vom|Entscheid vom|Sachverhalt)")


def own_dockets(text: str, own_docket: str | None) -> set[str]:
    """The decision's own file numbers. Joined proceedings list several of them in the header,
    which ends at the "Urteil vom" or "Besetzung" line."""
    m = _HEADER_END_RE.search(text[:2000])
    head = text[: m.start()] if m else ""
    own = {d.group("docket") for d in DOCKET_RE.finditer(head)}
    if own_docket:
        own.add(own_docket)
    return own


def extract_dockets(text: str, own_docket: str | None) -> list[DocketCitation]:
    out: list[DocketCitation] = []
    own = own_dockets(text, own_docket)
    for m in DOCKET_RE.finditer(text):
        d = m.group("docket")
        if d in own:
            continue
        tail = text[m.end() : m.end() + 60]
        cons = re.search(rf"(?:E\.|Erw\.){SP}?(\d+(?:\.\d+)*[a-z]?)", tail)
        out.append(
            DocketCitation(
                span=_span(m, SpanLabel.DOCKET, text),
                docket=d,
                consideration=cons.group(1) if cons else None,
            )
        )
    return out


def _parse_amount(num: str) -> float:
    mult = 1.0
    if re.search(r"Mio\.$", num):
        mult = 1e6
    elif re.search(r"Mrd\.$", num):
        mult = 1e9
    num = re.sub(r"\s?(?:Mio|Mrd)\.$", "", num).replace("'", "").replace("’", "")
    num = num.replace(",", ".")  # decimal comma (v0.3)
    num = re.sub(r"\.(?:-{1,2}|–)$", "", num)
    return float(num) * mult


def extract_amounts(text: str) -> list[Amount]:
    out: list[Amount] = []
    for m in AMOUNT_RE.finditer(text):
        num = m.group("num1") or m.group("num2")
        cur = m.group("cur1") or m.group("cur2")
        currency = {"Fr.": "CHF", "Fr": "CHF", "Franken": "CHF"}.get(cur, cur)
        out.append(
            Amount(
                span=_span(m, SpanLabel.AMOUNT, text), value=_parse_amount(num), currency=currency
            )
        )
    return out


def extract_party_roles(text: str) -> list[Span]:
    start_m = RUBRUM_START.search(text[:3000])
    if not start_m:
        return []
    end_m = RUBRUM_END.search(text, start_m.end())
    end = end_m.start() if end_m else min(len(text), start_m.end() + 2500)
    out: list[Span] = []
    seen: set[str] = set()
    for m in PARTY_ROLE_RE.finditer(text, start_m.end(), end):
        role = m.group("role")
        if role in seen:
            continue
        seen.add(role)
        out.append(_span(m, SpanLabel.PARTY_ROLE, text))
    return out


def extract_outcome(text: str) -> Outcome:
    matches = list(DISPOSITIV_RE.finditer(text))
    if not matches:
        return Outcome.UNKNOWN
    m = matches[-1]  # the dispositiv is the last such header in the decision
    disp = text[m.end() : m.end() + 1500]
    # first numbered item that is not a consolidation order
    items = re.split(r"\n\s*\d\.\s*\n?", disp)
    candidates = items[1:] or [disp]
    for i, item in enumerate(candidates):
        # skip side requests, but not if nothing else is left to read
        if _SIDE_REQUEST_RE.search(item) and i + 1 < len(candidates):
            continue
        hit = next((o for rx, o in _OUTCOME_RULES if rx.search(item)), None)
        if hit is not None:
            return hit
    return Outcome.UNKNOWN


def extract(
    decision_id: str, text: str, code_map: dict[str, str] | None = None
) -> DecisionExtraction:
    header = extract_header(text)
    return DecisionExtraction(
        decision_id=decision_id,
        extractor="regex",
        header=header,
        statutes=extract_statutes(text, code_map),
        bge_citations=extract_bge(text),
        docket_citations=extract_dockets(text, header.docket_number),
        amounts=extract_amounts(text),
        outcome=extract_outcome(text),
        party_roles=extract_party_roles(text),
    )
