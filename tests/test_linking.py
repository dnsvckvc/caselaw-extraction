from caselaw_extraction.fedlex import resolve_code
from caselaw_extraction.linking import docket_of, link_spans

KNOWN = {"BGG": "173.110", "VVG": "221.229.1", "ZGB": "210", "EPÜ 2000": "0.232.142.2"}


def test_resolve_code_order_full_form_then_base_then_old_prefix():
    assert resolve_code("BGG", KNOWN) == ("BGG", "173.110")
    assert resolve_code("EPÜ 2000", KNOWN) == ("EPÜ 2000", "0.232.142.2")
    assert resolve_code("aVVG", KNOWN) == ("VVG", "221.229.1")
    assert resolve_code("SchlT ZGB", KNOWN) == ("ZGB", "210")
    assert resolve_code("AVB", KNOWN) is None
    assert resolve_code("BGB", KNOWN) is None


def test_docket_of():
    assert docket_of("bger_4A_12_2020") == "4A_12/2020"
    assert docket_of("bge_140_III_86") is None


TEXT = (
    "Bundesgericht\n4A_12/2020, 4A_13/2020\nUrteil vom 1. Januar 2021\n"
    "Im Verfahren 4A_12/2020 (vgl. 4A_99/2019) gilt Art. 42 BGG und Art. 13 Ziff. 2 AVB; "
    "BUSCHE, N 8 zu § 133 BGB; BGE 140 III 86 E. 2; SVR 1998 IV Nr. 13; Fr. 500.--.\n"
)


def _span(text, needle, label, occurrence=1):
    start = -1
    for _ in range(occurrence):
        start = text.index(needle, start + 1)
    return {"start": start, "end": start + len(needle), "label": label, "text": needle}


def test_link_spans_keeps_linkable_and_drops_the_rest():
    spans = [
        _span(TEXT, "4A_12/2020", "DOCKET", occurrence=2),
        _span(TEXT, "4A_99/2019", "DOCKET"),
        _span(TEXT, "Art. 42 BGG", "STATUTE"),
        _span(TEXT, "Art. 13 Ziff. 2 AVB", "STATUTE"),
        _span(TEXT, "133", "STATUTE"),
        _span(TEXT, "Art", "STATUTE"),
        _span(TEXT, "BGE 140 III 86", "BGE"),
        _span(TEXT, "SVR", "BGE"),
        _span(TEXT, "Fr. 500.--", "AMOUNT"),
    ]
    kept, dropped = link_spans(TEXT, "bger_4A_12_2020", spans, KNOWN)
    texts = [s["text"] for s in kept]
    assert texts == ["4A_99/2019", "Art. 42 BGG", "BGE 140 III 86", "Fr. 500.--"]
    assert dict(dropped) == {"own_docket": 1, "unknown_code": 2, "no_article": 1, "no_bge_key": 1}
    assert kept[0]["link"] == "4A_99_2019"
    assert kept[1]["link"] == [{"code": "BGG", "sr": "173.110", "article": "42"}]
    assert kept[2]["link"] == "BGE 140 III 86"
    assert "link" not in kept[3]


def test_link_spans_never_changes_boundaries_or_adds():
    spans = [_span(TEXT, "Art. 42 BGG", "STATUTE")]
    kept, _ = link_spans(TEXT, "bger_4A_12_2020", spans, KNOWN)
    assert [(s["start"], s["end"]) for s in kept] == [(spans[0]["start"], spans[0]["end"])]
