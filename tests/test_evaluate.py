from caselaw_extraction.evaluate import Scores, score_decision


def test_exact_and_overlap():
    s = Scores()
    gold = [(0, 10, "STATUTE"), (20, 30, "BGE"), (40, 50, "AMOUNT")]
    pred = [(0, 10, "STATUTE"), (22, 30, "BGE"), (60, 70, "AMOUNT")]
    score_decision(s, pred, gold, "dismissed", "dismissed")
    assert (s.exact["STATUTE"].tp, s.exact["BGE"].tp, s.exact["BGE"].fp, s.exact["BGE"].fn) == (
        1,
        0,
        1,
        1,
    )
    assert (s.overlap["BGE"].tp, s.overlap["BGE"].fp) == (1, 0)
    assert (s.exact["AMOUNT"].fp, s.exact["AMOUNT"].fn) == (1, 1)
    assert s.micro("exact").f1 == 2 * (1 / 3) * (1 / 3) / (2 / 3)
    assert s.outcome["correct"] == 1


def test_label_mismatch_is_not_overlap_match():
    s = Scores()
    score_decision(s, [(0, 10, "BGE")], [(0, 10, "STATUTE")])
    assert s.overlap["BGE"].fp == 1 and s.overlap["STATUTE"].fn == 1
