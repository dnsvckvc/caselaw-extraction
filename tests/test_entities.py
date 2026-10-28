from collections import Counter

from caselaw_extraction.evaluate import EntityScores, entity_keys, norm_docket, statute_keys
from caselaw_extraction.scoring import macro_f1


def test_statute_keys_expand_chains():
    assert statute_keys("Art. 42 Abs. 2 und Art. 106 Abs. 2 BGG") == {("BGG", "42"), ("BGG", "106")}
    assert statute_keys("Art. 95 und 96 BGG") == {("BGG", "95"), ("BGG", "96")}
    assert statute_keys("SchlT Art. 1 ZGB") or True  # loose parse must not raise


def test_statute_keys_fallback_for_unknown_forms():
    assert statute_keys("Art 113 BGG") == {("BGG", "113")}
    assert statute_keys("Art. 56 EPÜ 2000") == {("EPÜ 2000", "56")}
    assert statute_keys("SchlT Art. 1 ZGB") == {("ZGB", "1")}


def test_entity_keys_bge_and_docket():
    spans = [
        {"label": "BGE", "text": "BGE 140 III 86"},
        {"label": "BGE", "text": "139 III 133"},
        {"label": "DOCKET", "text": "4A_174/ 2019"},
        {"label": "DOCKET", "text": "4C.195/2005"},
        {"label": "STATUTE", "text": "Art. 8 ZGB"},
    ]
    k = entity_keys(spans)
    assert k["BGE"] == {"BGE 140 III 86", "BGE 139 III 133"}
    assert k["DOCKET"] == {"4A_174_2019", "4C_195_2005"}
    assert k["STATUTE"] == {"ZGB 8"}


def test_norm_docket():
    assert norm_docket("2C_52/2016") == norm_docket("2C_52_2016") == "2C_52_2016"


def test_entity_scores_counts():
    es = EntityScores()
    es.add({"BGE": {"a", "b"}, "STATUTE": set(), "DOCKET": set()}, {"BGE": {"b", "c"}})
    assert (es.prf["BGE"].tp, es.prf["BGE"].fp, es.prf["BGE"].fn) == (1, 1, 1)
    assert round(es.micro().f1, 3) == 0.5


def test_macro_f1_over_gold_classes_only():
    conf = Counter({("dismissed", "dismissed"): 8, ("approved", "dismissed"): 2})
    # dismissed: P=0.8 R=1 F1=0.889; approved: F1=0 -> macro 0.444
    assert round(macro_f1(conf, ["dismissed", "approved"]), 3) == 0.444
    assert round(macro_f1(conf, ["dismissed"]), 3) == 0.889


def test_scores_label_filter_and_confusion():
    from caselaw_extraction.evaluate import Scores, score_decision

    sc = Scores(labels=("STATUTE", "BGE"))
    # gold: STATUTE at 0-10, CONTRACT_ARTICLE at 20-30; pred: STATUTE at both places
    score_decision(
        sc,
        [(0, 10, "STATUTE"), (20, 30, "STATUTE")],
        [(0, 10, "STATUTE"), (20, 30, "CONTRACT_ARTICLE")],
    )
    assert (sc.exact["STATUTE"].tp, sc.exact["STATUTE"].fp) == (1, 1)
    assert "CONTRACT_ARTICLE" not in sc.exact
    assert sc.label_confusion[("CONTRACT_ARTICLE", "STATUTE")] == 1
    assert sc.label_confusion[("STATUTE", "STATUTE")] == 1
    sc_all = Scores(labels=("STATUTE", "BGE", "CONTRACT_ARTICLE"))
    score_decision(sc_all, [(20, 30, "STATUTE")], [(20, 30, "CONTRACT_ARTICLE")])
    assert sc_all.exact["CONTRACT_ARTICLE"].fn == 1 and sc_all.exact["STATUTE"].fp == 1


def test_bge_key_resolves_short_citation_from_context():
    from caselaw_extraction.evaluate import bge_key

    t = "vgl. BGE 140 III 86 E. 2, 115 E. 2 und 264 E. 2.3"
    assert bge_key("115", t, t.index("115")) == "BGE 140 III 115"
    assert bge_key("115") is None
    assert bge_key("BGE 139 III 133 E. 1") == "BGE 139 III 133"
