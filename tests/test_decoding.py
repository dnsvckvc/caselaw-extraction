import torch

from caselaw_extraction.transformer_extractor import bio_transition_mask, viterbi_decode

TAGS = ["O", "B-X", "I-X", "B-Y", "I-Y"]


def test_mask_forbids_i_after_o_or_other_label_and_at_start():
    m = bio_transition_mask(TAGS)
    assert not m[0, 2]  # O -> I-X
    assert m[1, 2] and m[2, 2]  # B-X -> I-X, I-X -> I-X
    assert not m[3, 2]  # B-Y -> I-X
    assert m[0, 1] and m[0, 0] and m[2, 0]
    assert not m[len(TAGS), 2] and m[len(TAGS), 1]  # start state


def test_viterbi_repairs_stray_i_tags_and_keeps_valid_paths():
    # token 1 prefers I-X slightly over B-X; argmax gives O, I-X, I-X (invalid); Viterbi B-X, I-X
    lp = torch.log(
        torch.tensor(
            [
                [0.90, 0.04, 0.02, 0.02, 0.02],
                [0.10, 0.40, 0.44, 0.03, 0.03],
                [0.10, 0.05, 0.80, 0.02, 0.03],
            ]
        )
    )
    assert lp.argmax(-1).tolist() == [0, 2, 2]
    assert viterbi_decode(lp, bio_transition_mask(TAGS)) == [0, 1, 2]
    # when the valid path is much worse, O wins over an invalid I-X
    lp2 = torch.log(torch.tensor([[0.9, 0.05, 0.05, 0, 0], [0.45, 0.05, 0.5, 0, 0]]) + 1e-9)
    assert viterbi_decode(lp2, bio_transition_mask(TAGS)) == [0, 0]
