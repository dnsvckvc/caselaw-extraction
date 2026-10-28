"""Extraction schema for Swiss Federal Supreme Court (BGer) decisions.

Every extractor (regex, spaCy, transformer, LLM) emits the same `DecisionExtraction`.
Span offsets are character offsets into `full_text` as stored in the corpus.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class Outcome(StrEnum):
    """Dispositiv outcome of the appeal before the BGer."""

    # Values match the `outcome` column of the voilaj/swiss-caselaw dataset so that the
    # dataset's own label can be scored as a silver baseline.
    APPROVED = "approved"  # gutgeheissen
    PARTIAL_APPROVAL = "partial_approval"  # teilweise gutgeheissen
    DISMISSED = "dismissed"  # abgewiesen
    INADMISSIBLE = "inadmissible"  # nicht eingetreten
    MOOT = "moot"  # abgeschrieben / gegenstandslos
    CONSOLIDATED = "consolidated"  # Verfahren vereinigt (rare, usually not the main outcome)
    UNKNOWN = "unknown"


class SpanLabel(StrEnum):
    STATUTE = "STATUTE"  # Art. 8 Abs. 1 ZGB
    BGE = "BGE"  # BGE 140 III 86
    DOCKET = "DOCKET"  # 4A_463/2022 (prior decision cited by docket number)
    AMOUNT = "AMOUNT"  # Fr. 40'000.--
    PARTY_ROLE = "PARTY_ROLE"  # Beschwerdeführer, Beschwerdegegnerin


class Span(BaseModel):
    """A labelled character span in `full_text`."""

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    label: SpanLabel
    text: str

    @model_validator(mode="after")
    def _end_after_start(self) -> Span:
        if self.end <= self.start:
            raise ValueError(f"span end {self.end} must be greater than start {self.start}")
        return self


class StatuteCitation(BaseModel):
    """A normalised statute citation, linked to a Fedlex SR number when known."""

    span: Span
    code: str  # abbreviation as written, e.g. "ZGB", "OR", "BGG"
    article: str  # "8", "321c", "42"
    paragraph: str | None = None  # Abs.
    letter: str | None = None  # lit.
    number: str | None = None  # Ziff.
    sr_number: str | None = None  # Fedlex systematic number, e.g. "210" for ZGB


class BgeCitation(BaseModel):
    """A citation of a published leading decision (Bundesgerichtsentscheid)."""

    span: Span
    volume: int  # 140
    part: str  # "III"
    page: int  # 86
    consideration: str | None = None  # "E. 2.1"

    @property
    def key(self) -> str:
        return f"BGE {self.volume} {self.part} {self.page}"


class DocketCitation(BaseModel):
    """A citation of a BGer decision by docket number, e.g. 4A_463/2022."""

    span: Span
    docket: str
    consideration: str | None = None


class Amount(BaseModel):
    span: Span
    value: float
    currency: str = "CHF"


class Header(BaseModel):
    docket_number: str
    decision_date: date | None = None
    chamber: str | None = None
    appealed_court: str | None = None
    appealed_date: date | None = None


class DecisionExtraction(BaseModel):
    """Everything one extractor produces for one decision."""

    decision_id: str
    extractor: str  # "regex", "spacy", "xlmr", "llm", "opencaselaw"
    header: Header
    statutes: list[StatuteCitation] = Field(default_factory=list)
    bge_citations: list[BgeCitation] = Field(default_factory=list)
    docket_citations: list[DocketCitation] = Field(default_factory=list)
    amounts: list[Amount] = Field(default_factory=list)
    outcome: Outcome = Outcome.UNKNOWN
    party_roles: list[Span] = Field(default_factory=list)

    def all_spans(self) -> list[Span]:
        spans = [s.span for s in self.statutes]
        spans += [b.span for b in self.bge_citations]
        spans += [d.span for d in self.docket_citations]
        spans += [a.span for a in self.amounts]
        spans += self.party_roles
        return sorted(spans, key=lambda s: s.start)
