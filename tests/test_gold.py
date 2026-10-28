from caselaw_extraction.gold import char_tags, dedupe, dispositiv, spans_in, tags_to_spans, windows

TEXT = "Nach Art. 8 ZGB gilt.\nSiehe BGE 140 III 86 E. 2; 139 III 133.\nFr. 500.-- sind streitig.\n"
SPANS = [
    {"start": 5, "end": 15, "label": "STATUTE", "text": "Art. 8 ZGB"},
    {"start": 28, "end": 42, "label": "BGE", "text": "BGE 140 III 86"},
    {"start": 49, "end": 60, "label": "BGE", "text": "139 III 133"},
    {"start": 62, "end": 72, "label": "AMOUNT", "text": "Fr. 500.--"},
]


def test_span_texts_match_fixture():
    for s in SPANS:
        assert TEXT[s["start"] : s["end"]] == s["text"]


def test_windows_cover_text_and_never_cut_spans():
    wins = windows(TEXT, SPANS, max_chars=30)
    assert wins[0][0] == 0 and wins[-1][1] == len(TEXT)
    for (_a, b), (c, _d) in zip(wins, wins[1:], strict=False):
        assert b == c
    for s in SPANS:
        assert any(a <= s["start"] and s["end"] <= b for a, b in wins)


def test_spans_in_shifts_to_window_coordinates():
    inside = spans_in(SPANS, 22, 61)
    assert [s["text"] for s in inside] == ["BGE 140 III 86", "139 III 133"]
    assert inside[0]["start"] == 6
    assert TEXT[22:61][inside[0]["start"] : inside[0]["end"]] == "BGE 140 III 86"


def test_char_tags_and_back_to_spans_roundtrip():
    ct = char_tags(TEXT, SPANS)
    assert ct[5] == "B-STATUTE" and ct[6] == "I-STATUTE" and ct[0] == "O"
    # whitespace tokenisation: one tag per token, taken from its first character
    offsets, tags = [], []
    pos = 0
    for tok in TEXT.split():
        a = TEXT.index(tok, pos)
        offsets.append((a, a + len(tok)))
        tags.append(ct[a])
        pos = a + len(tok)
    out = tags_to_spans(TEXT, offsets, tags)
    got = {(s["start"], s["end"], s["label"]) for s in out}
    # "Fr. 500.--" ends the token; "139 III 133." carries the final full stop into the token,
    # so that span grows by one character: a known boundary effect of coarse tokens
    assert (5, 15, "STATUTE") in got
    assert (28, 42, "BGE") in got
    assert (62, 72, "AMOUNT") in got
    assert any(s["label"] == "BGE" and s["start"] == 49 for s in out)


def test_tags_to_spans_stray_i_tag_starts_span():
    text = "a b c"
    out = tags_to_spans(text, [(0, 1), (2, 3), (4, 5)], ["O", "I-BGE", "I-BGE"])
    assert out == [{"start": 2, "end": 5, "label": "BGE", "text": "b c"}]


def test_dedupe_keeps_one_per_key_sorted():
    d = dedupe([SPANS[1], SPANS[0], dict(SPANS[0])])
    assert [s["start"] for s in d] == [5, 28]


def test_dispositiv_takes_last_header_or_tail():
    t = "Erwägungen ... Demnach erkennt das Bundesgericht:\n1.\nDie Beschwerde wird abgewiesen.\n"
    assert dispositiv(t).startswith("Demnach erkennt das Bundesgericht:")
    assert dispositiv("kein Dispositiv " * 200, length=50) == ("kein Dispositiv " * 200)[-50:]
