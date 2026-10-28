from datetime import date

from caselaw_extraction import regex_extractor as rx
from caselaw_extraction.fedlex import CORE_CODES
from caselaw_extraction.schema import Outcome

HEADER = """Bundesgericht

4A_463/2022

Urteil vom 3. Januar 2023

I. zivilrechtliche Abteilung

Besetzung
Bundesrichterin Hohl, präsidierendes Mitglied,

Verfahrensbeteiligte
A.________,
vertreten durch Rechtsanwältin Patricia Zumsteg,
Beschwerdeführer,

gegen

B.________ AG,
Beschwerdegegnerin.

Gegenstand
Revision; gerichtlicher Vergleich,

Beschwerde gegen das Urteil des Sozialversicherungsgerichts des Kantons Basel-Stadt vom 31. März 2022 (ZV.2021.2).
"""


def test_header():
    h = rx.extract_header(HEADER)
    assert h.docket_number == "4A_463/2022"
    assert h.decision_date == date(2023, 1, 3)
    assert h.chamber == "I. zivilrechtliche Abteilung"
    assert h.appealed_court == "Sozialversicherungsgerichts des Kantons Basel-Stadt"
    assert h.appealed_date == date(2022, 3, 31)


def test_party_roles_once_each_in_rubrum():
    spans = rx.extract_party_roles(HEADER + "\nDer Beschwerdeführer macht geltend...")
    assert [s.text for s in spans] == ["Beschwerdeführer", "Beschwerdegegnerin"]


def _statutes(text):
    return [
        (s.span.text, s.code, s.article, s.paragraph, s.letter, s.number)
        for s in rx.extract_statutes(text, CORE_CODES)
    ]


def test_simple_statute():
    assert _statutes("gemäss Art. 42 Abs. 1 BGG ist") == [
        ("Art. 42 Abs. 1 BGG", "BGG", "42", "1", None, None)
    ]


def test_statute_with_lit_and_ziff():
    out = _statutes("nach Art. 97 Abs. 1 lit. a Ziff. 2 OR.")
    assert out == [("Art. 97 Abs. 1 lit. a Ziff. 2 OR", "OR", "97", "1", "a", "2")]


def test_statute_chain_shares_span():
    out = _statutes("(Art. 95 und 96 BGG)")
    assert [o[0] for o in out] == ["Art. 95 und 96 BGG"] * 2
    assert [o[2] for o in out] == ["95", "96"]


def test_statute_ivm_chain_one_span():
    out = _statutes("Art. 97 Abs. 1 i.V.m. Art. 105 Abs. 2 BGG")
    assert len(out) == 2
    assert out[0][0] == "Art. 97 Abs. 1 i.V.m. Art. 105 Abs. 2 BGG"
    assert (out[0][2], out[0][3]) == ("97", "1")
    assert (out[1][2], out[1][3]) == ("105", "2")


def test_statute_two_codes_two_spans():
    out = _statutes("Art. 42 Abs. 2 BGG i.V.m. Art. 106 Abs. 2 BGG")
    assert [o[0] for o in out] == ["Art. 42 Abs. 2 BGG", "Art. 106 Abs. 2 BGG"]


def test_old_version_and_bis_article():
    out = _statutes("aArt. 139 Ziff. 2 StGB und Art. 8a ZGB sowie Art. 93bis OR")
    assert [(o[0], o[2]) for o in out] == [
        ("aArt. 139 Ziff. 2 StGB", "139"),
        ("Art. 8a ZGB", "8a"),
        ("Art. 93bis OR", "93bis"),
    ]


def test_unknown_code_is_skipped_when_code_map_given():
    assert _statutes("Art. 5 Verordnung") == []


def test_sr_number_linked():
    s = rx.extract_statutes("Art. 8 ZGB", CORE_CODES)[0]
    assert s.sr_number == "210"


def test_bge_single_with_consideration():
    b = rx.extract_bge("vgl. BGE 140 III 86 E. 2.1 S. 88")
    assert [(x.span.text, x.key, x.consideration) for x in b] == [
        ("BGE 140 III 86", "BGE 140 III 86", "2.1")
    ]


def test_bge_chain():
    b = rx.extract_bge("(BGE 140 III 86 E. 2; 139 III 133 E. 1.1, 138 III 2 E. 3 S. 5)")
    assert [x.span.text for x in b] == ["BGE 140 III 86", "139 III 133", "138 III 2"]
    assert [x.consideration for x in b] == ["2", "1.1", "3"]


def test_bge_parts():
    b = rx.extract_bge("BGE 146 I 30, BGE 120 Ia 31, BGE 133 V 477")
    assert [x.part for x in b] == ["I", "Ia", "V"]


def test_dockets_exclude_own():
    d = rx.extract_dockets(
        "Urteil 4A_12/2016 vom 10. Mai 2016 E. 3.2; 4C.195/2005; 4A_463/2022", "4A_463/2022"
    )
    assert [(x.docket, x.consideration) for x in d] == [
        ("4A_12/2016", "3.2"),
        ("4C.195/2005", None),
    ]


def test_amounts():
    a = rx.extract_amounts("Fr. 40'000.-- und CHF 12'500.50 sowie 1'200 Franken und EUR 300")
    assert [(x.value, x.currency) for x in a] == [
        (40000.0, "CHF"),
        (12500.5, "CHF"),
        (1200.0, "CHF"),
        (300.0, "EUR"),
    ]


DISP = "\n\nDemnach erkennt das Bundesgericht:\n\n1.\nDie Beschwerde wird {}.\n\n2.\nDie Gerichtskosten von Fr. 2'000.-- werden dem Beschwerdeführer auferlegt.\n"


def test_outcomes():
    assert (
        rx.extract_outcome(DISP.format("abgewiesen, soweit darauf einzutreten ist"))
        is Outcome.DISMISSED
    )
    assert rx.extract_outcome(DISP.format("teilweise gutgeheissen")) is Outcome.PARTIAL_APPROVAL
    assert rx.extract_outcome(DISP.format("gutgeheissen")) is Outcome.APPROVED
    assert (
        rx.extract_outcome(
            "Demnach erkennt das Bundesgericht:\n\n1.\nAuf die Beschwerde wird nicht eingetreten.\n"
        )
        is Outcome.INADMISSIBLE
    )
    assert rx.extract_outcome(DISP.format("als gegenstandslos abgeschrieben")) is Outcome.MOOT
    assert rx.extract_outcome("no dispositiv here") is Outcome.UNKNOWN


def test_outcome_skips_consolidation_item():
    text = "Demnach erkennt das Bundesgericht:\n\n1.\nDie Verfahren 4A_1/2020 und 4A_2/2020 werden vereinigt.\n\n2.\nDie Beschwerden werden abgewiesen.\n"
    assert rx.extract_outcome(text) is Outcome.DISMISSED


def test_full_extract_spans_are_consistent():
    text = (
        HEADER
        + "\nErwägungen:\n1. Nach Art. 42 Abs. 1 BGG (BGE 140 III 86 E. 2.1) ... Urteil 4A_12/2016 E. 3 ... Fr. 40'000.--"
        + DISP.format("abgewiesen")
    )
    ex = rx.extract("x", text, CORE_CODES)
    for s in ex.all_spans():
        assert text[s.start : s.end] == s.text
    assert ex.outcome is Outcome.DISMISSED
    assert ex.header.docket_number == "4A_463/2022"
    assert [d.docket for d in ex.docket_citations] == ["4A_12/2016"]


def test_outcome_president_variants():
    for head in [
        "Demnach erkennt der Präsident:",
        "Demnach erkennt die Präsidentin:",
        "Demnach erkennt das präsidierende Mitglied:",
        "Demnach verfügt der Einzelrichter:",
    ]:
        text = (
            head
            + "\n\n1.\n\nAuf die Beschwerde wird nicht eingetreten.\n\n2.\n\nEs werden keine Gerichtskosten erhoben.\n"
        )
        assert rx.extract_outcome(text) is Outcome.INADMISSIBLE, head


def test_outcome_uses_first_item_not_later_legal_aid_item():
    text = "Demnach erkennt das Bundesgericht:\n\n1.\n\nDie Beschwerde wird abgewiesen, soweit darauf eingetreten wird.\n\n2.\n\nDas Gesuch um unentgeltliche Rechtspflege wird gutgeheissen.\n"
    assert rx.extract_outcome(text) is Outcome.DISMISSED


def test_outcome_header_without_demnach_after_semicolon():
    text = "kein Aufwand entstanden ist (\nArt. 68 BGG\n);\n\nverfügt die Präsidentin:\n\n1.\n\nDas Verfahren wird infolge Rückzugs der Beschwerde abgeschrieben.\n\n2.\n\nDie Gerichtskosten von Fr. 300.-- werden der Beschwerdeführerin auferlegt.\n"
    assert rx.extract_outcome(text) is Outcome.MOOT


def test_statute_chain_across_line_breaks():
    out = _statutes(
        "offen (\nArt. 72 Abs. 1,\nArt. 74 Abs. 1 lit. b,\nArt. 75 Abs. 1 und\nArt. 90 BGG\n)."
    )
    assert len(out) == 4
    assert out[0][0] == "Art. 72 Abs. 1,\nArt. 74 Abs. 1 lit. b,\nArt. 75 Abs. 1 und\nArt. 90 BGG"
    assert [o[2] for o in out] == ["72", "74", "75", "90"]


def test_statute_ranges_ff_and_ordinal_satz():
    out = _statutes(
        "Art. 121-123 BGG; Art. 95 f. BGG; Art. 319 ff. ZPO; Art. 121 lit. b-d BGG; Art. 66 Abs. 1 zweiter Satz BGG"
    )
    assert [o[0] for o in out] == [
        "Art. 121-123 BGG",
        "Art. 95 f. BGG",
        "Art. 319 ff. ZPO",
        "Art. 121 lit. b-d BGG",
        "Art. 66 Abs. 1 zweiter Satz BGG",
    ]


def test_statute_in_verbindung_mit_and_schlt():
    out = _statutes(
        "Art. 19 Abs. 1 lit. c in Verbindung mit\nArt. 20 Abs. 2 URG und Art. 6b Abs. 2bis SchlT ZGB"
    )
    assert [o[0] for o in out] == [
        "Art. 19 Abs. 1 lit. c in Verbindung mit\nArt. 20 Abs. 2 URG",
        "Art. 19 Abs. 1 lit. c in Verbindung mit\nArt. 20 Abs. 2 URG",
        "Art. 6b Abs. 2bis SchlT ZGB",
    ]
    assert out[2][1] == "SchlT ZGB"


def test_bge_list_across_line_breaks():
    b = rx.extract_bge(
        "(\nBGE 137 III 324\nE. 1.1;\n141 III 80\nE. 1.2;\n141 IV 289\nE. 1.3; je mit Hinweisen)"
    )
    assert [x.key for x in b] == ["BGE 137 III 324", "BGE 141 III 80", "BGE 141 IV 289"]


def test_amounts_with_mio_and_fr_without_dot():
    a = rx.extract_amounts(
        "Betrag von Fr. 3.241 Mio. und EUR 2 Mio. sowie Fr 6'000.-- und Fr. 28 Mio. zuzüglich"
    )
    assert [(x.span.text, x.value) for x in a] == [
        ("Fr. 3.241 Mio.", 3_241_000.0),
        ("EUR 2 Mio.", 2_000_000.0),
        ("Fr 6'000.--", 6000.0),
        ("Fr. 28 Mio.", 28_000_000.0),
    ]


def test_joined_proceedings_both_own_numbers_excluded():
    text = (
        "Bundesgericht\n4A_669/2025, 4A_671/2025\nUrteil vom 25. Februar 2026\n"
        + "x" * 1500
        + " Verfahren 4A_671/2025 und Urteil 4A_12/2016 sowie B.101/1991"
    )
    d = rx.extract_dockets(text, "4A_669/2025")
    assert [x.docket for x in d] == ["4A_12/2016", "B.101/1991"]


def test_outcome_skips_side_requests_and_handles_remand():
    t1 = "Demnach erkennt das Bundesgericht:\n\n1.\nDas Sistierungsgesuch wird abgewiesen.\n\n2.\nAuf die Beschwerde wird nicht eingetreten.\n"
    assert rx.extract_outcome(t1) is Outcome.INADMISSIBLE
    t2 = "Demnach erkennt das Bundesgericht:\n\n1.\nDie Verfügung vom 1. Mai 2020 wird aufgehoben und die Sache an die Vorinstanz zurückgewiesen.\n\n2.\n2.1.\nDas Gesuch um unentgeltliche Rechtspflege wird als gegenstandslos abgeschrieben.\n"
    assert rx.extract_outcome(t2) is Outcome.APPROVED
    t3 = "Demnach erkennt das Bundesgericht:\n\n1.\nDas Urteil 4A_294/2020 wird wie folgt berichtigt: ...\n"
    assert rx.extract_outcome(t3) is Outcome.APPROVED


# --- regex v0.3 (cases reported by the batch-2 labelling agents) ---------------------------------

CM3 = {"BGG": "173.110", "OR": "220", "SchKG": "281.1", "URG": "231.1"}


def test_v03_abs_element_after_separator_is_one_span():
    t = "gemäss Art. 271a Abs. 1 lit. e Ziff. 4 i.V.m. Abs. 2 OR und Art. 51 Abs. 1 Bst. a und Abs. 4 sowie Art. 52 BGG."
    got = [(c.span.text, c.article, c.paragraph) for c in rx.extract_statutes(t, CM3)]
    assert got == [
        ("Art. 271a Abs. 1 lit. e Ziff. 4 i.V.m. Abs. 2 OR", "271a", "1"),
        ("Art. 271a Abs. 1 lit. e Ziff. 4 i.V.m. Abs. 2 OR", "271a", "2"),
        ("Art. 51 Abs. 1 Bst. a und Abs. 4 sowie Art. 52 BGG", "51", "1"),
        ("Art. 51 Abs. 1 Bst. a und Abs. 4 sowie Art. 52 BGG", "51", "4"),
        ("Art. 51 Abs. 1 Bst. a und Abs. 4 sowie Art. 52 BGG", "52", None),
    ]


def test_v03_art_without_dot_and_missing_space():
    assert [c.span.text for c in rx.extract_statutes("(Art 113 BGG) und Art. 17SchKG", CM3)] == [
        "Art 113 BGG",
        "Art. 17SchKG",
    ]
    # the German noun "Art" without a known code is not a citation
    assert rx.extract_statutes("eine Art Vertrag", CM3) == []


def test_v03_lit_item_with_bis_suffix():
    got = rx.extract_statutes("Art. 67 Abs. 1 lit. e, f und gbis URG", CM3)
    assert [c.span.text for c in got] == ["Art. 67 Abs. 1 lit. e, f und gbis URG"]


def test_v03_decimal_comma_before_multiplier():
    got = rx.extract_amounts("Fr. 2,3 Mio. sowie CHF 5,5 Mio. und Fr. 500, und Fr. 1,5 dann")
    assert [(a.span.text, a.value) for a in got] == [
        ("Fr. 2,3 Mio.", 2_300_000.0),
        ("CHF 5,5 Mio.", 5_500_000.0),
        ("Fr. 500", 500.0),
        ("Fr. 1", 1.0),
    ]


def test_v03_docket_with_space_after_slash():
    assert [d.docket for d in rx.extract_dockets("Urteil 4A_174/ 2019 vom", None)] == [
        "4A_174/ 2019"
    ]


def test_v03_header_without_demnach_and_time_limit_side_request():
    t = "x\nDas Bundesgericht erkennt:\n1.\nDie Beschwerde wird abgewiesen, soweit darauf einzutreten ist.\n"
    assert rx.extract_outcome(t) is Outcome.DISMISSED
    t2 = (
        "x\nDemnach erkennt das Bundesgericht:\n1.\nDas Fristwiederherstellungsgesuch wird abgewiesen.\n"
        "2.\nAuf die Beschwerde wird nicht eingetreten.\n"
    )
    assert rx.extract_outcome(t2) is Outcome.INADMISSIBLE


def test_epue_2000_resolves_through_full_form_lookup():
    cm = {"PatG": "232.14", "EPÜ 2000": "0.232.142.2"}
    got = rx.extract_statutes("(Art. 7 Abs. 2 PatG, Art. 54 Abs. 2 EPÜ 2000)", cm)
    assert [(c.span.text, c.sr_number) for c in got] == [
        ("Art. 7 Abs. 2 PatG", "232.14"),
        ("Art. 54 Abs. 2 EPÜ 2000", "0.232.142.2"),
    ]


def test_v04_artikel_written_out_and_short_bge_citations():
    cm = {"BGG": "173.110", "VVG": "221.229.1"}
    got = rx.extract_statutes("nach Artikel 104 BGG und Artikeln 35a und 35b VVG", cm)
    # a chain yields one citation per article, sharing one span
    assert [(c.span.text, c.article) for c in got] == [
        ("Artikel 104 BGG", "104"),
        ("Artikeln 35a und 35b VVG", "35a"),
        ("Artikeln 35a und 35b VVG", "35b"),
    ]
    t = "(BGE 140 III 86 E. 2, 115 E. 2; 264 E. 2.3; 139 III 133 E. 1.1, 334 E. 3 S. 340)"
    bge = rx.extract_bge(t)
    assert [(b.span.text, b.volume, b.part, b.page) for b in bge] == [
        ("BGE 140 III 86", 140, "III", 86),
        ("115", 140, "III", 115),
        ("264", 140, "III", 264),
        ("139 III 133", 139, "III", 133),
        ("334", 139, "III", 334),
    ]
    # a second page of the same decision is not a citation
    assert [b.span.text for b in rx.extract_bge("BGE 133 III 189 E. 5.2.5 S. 197, 201")] == [
        "BGE 133 III 189"
    ]
