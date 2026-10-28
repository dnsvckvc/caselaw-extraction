from caselaw_extraction.negatives import propose

CM = {"BGG": "173.110", "SchKG": "281.1", "EMRK": "0.101", "VVG": "221.229.1"}


def _texts(text, taken=()):
    return [(s["label"], s["text"]) for s in propose(text, list(taken), CM)]


def test_contract_article_and_bare_article():
    t = "Gemäss Art. 13 Ziff. 2 lit. a AVB und Ziff. 6 der AGB gilt; vgl. N. 6 zu Art. 242; Art. 22 des Konsortialvertrags."
    assert _texts(t) == [
        ("CONTRACT_ARTICLE", "Art. 13 Ziff. 2 lit. a AVB"),
        ("CONTRACT_ARTICLE", "Ziff. 6 der AGB"),
        ("BARE_ARTICLE", "Art. 242"),
        ("CONTRACT_ARTICLE", "Art. 22 des Konsortialvertrags"),
    ]


def test_other_law_and_federal_acts_are_skipped():
    t = "BUSCHE, N 8 zu § 133 BGB; § 18 ZPO/ZH; Art. 42 BGG; Art. 6 Ziff. 1 EMRK; Art. 101 AEUV."
    assert _texts(t) == [
        ("OTHER_LAW", "§ 133 BGB"),
        ("OTHER_LAW", "§ 18 ZPO/ZH"),
        ("OTHER_LAW", "Art. 101 AEUV"),
    ]


def test_title_form_is_bare_and_journal_refs():
    t = "nach Art. 19 des Bundesgesetzes über die Arbeitsvermittlung (AVG; SR 823.11), publ. in SVR 1998 IV Nr. 13 und FamPra.ch 2018 S. 595 ff."
    assert _texts(t) == [
        ("BARE_ARTICLE", "Art. 19"),
        ("JOURNAL_REF", "SVR 1998 IV Nr. 13"),
        ("JOURNAL_REF", "FamPra.ch 2018 S. 595"),
    ]


def test_taken_spans_are_respected():
    t = "Art. 13 AVB und Art. 13 AVB"
    taken = [{"start": 0, "end": 11, "label": "STATUTE", "text": "Art. 13 AVB"}]
    assert _texts(t, taken) == [("CONTRACT_ARTICLE", "Art. 13 AVB")]


def test_spelled_out_forms_v03():
    t = "Gemäss Ziffer 9 des Vertrags und Artikel 17 der Vereinbarung; Ziffer 6.7 GT 9 VI; Ziffer 1 Absatz 2 des Vergleichs; N. 3 zu Artikel 242."
    assert _texts(t) == [
        ("CONTRACT_ARTICLE", "Ziffer 9 des Vertrags"),
        ("CONTRACT_ARTICLE", "Artikel 17 der Vereinbarung"),
        ("CONTRACT_ARTICLE", "Ziffer 6.7 GT 9 VI"),
        ("CONTRACT_ARTICLE", "Ziffer 1 Absatz 2 des Vergleichs"),
        ("BARE_ARTICLE", "Artikel 242"),
    ]
