"""Fine-tuned transformer extractors (PyTorch, Hugging Face).

Token classification over the five span labels (BIO tags) and sequence classification for the
outcome over the ruling section. The encoder is a pretrained German model (default
`deepset/gbert-base`); only a linear head is new. Runs on Apple MPS, CUDA or CPU.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader
from transformers import (
    AutoConfig,
    AutoModelForSequenceClassification,
    AutoModelForTokenClassification,
    AutoTokenizer,
    BertConfig,
    BertTokenizerFast,
    get_linear_schedule_with_warmup,
)

from caselaw_extraction.gold import (
    OUTCOMES,
    TAG2ID,
    TAGS,
    Decision,
    char_tags,
    dedupe,
    dispositiv,
    spans_in,
    tags_to_spans,
    windows,
)

MODELS = Path("models")
DEFAULT_MODEL = "deepset/gbert-base"
WINDOW_CHARS = 1200  # ~400 subword pieces; digit-heavy text tokenises into many pieces
MAX_LEN = 512
OUTCOME2ID = {o: i for i, o in enumerate(OUTCOMES)}


def device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def load_tokenizer(model_name: str):
    """transformers 5 cannot convert a vocab.txt-only BERT checkpoint through AutoTokenizer."""
    try:
        return AutoTokenizer.from_pretrained(model_name)
    except ValueError:
        return BertTokenizerFast.from_pretrained(model_name)


def load_config(model_name: str, **kw):
    """Old BERT checkpoints (deepset/gbert-base) have no `model_type` in config.json."""
    try:
        return AutoConfig.from_pretrained(model_name, **kw)
    except ValueError:
        return BertConfig.from_pretrained(model_name, **kw)


def seed_all(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


# --- token classification -------------------------------------------------------------------------


@dataclass
class Window:
    decision_id: str
    offset: int
    text: str


def _encode_window(tok, w: Window, spans: list[dict] | None):
    enc = tok(
        w.text,
        return_offsets_mapping=True,
        truncation=True,
        max_length=MAX_LEN,
    )
    if spans is not None:
        ct = char_tags(w.text, spans)
        labels = []
        for a, b in enc["offset_mapping"]:
            if a == b:
                labels.append(-100)
                continue
            c = a
            while c < b and w.text[c].isspace():
                c += 1
            labels.append(TAG2ID[ct[c]] if c < b else -100)
        enc["labels"] = labels
    enc["truncated"] = int(enc["offset_mapping"][-2][1] < len(w.text.rstrip()))
    return enc


def token_dataset(tok, decisions: list[Decision], with_labels: bool):
    items = []
    n_trunc = 0
    for d in decisions:
        for a, b in windows(d.text, d.spans if with_labels else [], WINDOW_CHARS):
            w = Window(d.decision_id, a, d.text[a:b])
            enc = _encode_window(tok, w, spans_in(d.spans, a, b) if with_labels else None)
            n_trunc += enc.pop("truncated")
            items.append((w, enc))
    return items, n_trunc


def _collate(tok, batch, with_labels: bool):
    feats = [{"input_ids": e["input_ids"], "attention_mask": e["attention_mask"]} for _, e in batch]
    padded = tok.pad(feats, return_tensors="pt")
    if with_labels:
        maxlen = padded["input_ids"].shape[1]
        padded["labels"] = torch.tensor(
            [e["labels"] + [-100] * (maxlen - len(e["labels"])) for _, e in batch]
        )
    return padded


def train_token_classifier(
    train: list[Decision],
    model_name: str = DEFAULT_MODEL,
    epochs: int = 4,
    lr: float = 3e-5,
    batch_size: int = 8,
    seed: int = 0,
) -> tuple[object, object, dict]:
    seed_all(seed)
    tok = load_tokenizer(model_name)
    cfg = load_config(
        model_name, num_labels=len(TAGS), id2label=dict(enumerate(TAGS)), label2id=TAG2ID
    )
    model = AutoModelForTokenClassification.from_pretrained(model_name, config=cfg)
    dev = device()
    model.to(dev)
    items, n_trunc = token_dataset(tok, train, with_labels=True)
    loader = DataLoader(
        items, batch_size=batch_size, shuffle=True, collate_fn=lambda b: _collate(tok, b, True)
    )
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    steps = epochs * len(loader)
    sched = get_linear_schedule_with_warmup(opt, int(0.1 * steps), steps)
    history = []
    model.train()
    for _ in range(epochs):
        tot = 0.0
        for batch in loader:
            batch = {k: v.to(dev) for k, v in batch.items()}
            loss = model(**batch).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad()
            tot += loss.item()
        history.append(tot / max(1, len(loader)))
    info = {"n_windows": len(items), "n_truncated": n_trunc, "loss_history": history}
    return tok, model, info


@torch.no_grad()
def load_saved(model_dir: Path):
    """Tokenizer and token classifier saved by `train_token_classifier`."""
    return load_tokenizer(str(model_dir)), AutoModelForTokenClassification.from_pretrained(
        str(model_dir)
    )


def load_saved_outcome(model_dir: Path):
    """Tokenizer and outcome (sequence) classifier saved by `caselaw train-transformer`."""
    return load_tokenizer(str(model_dir)), AutoModelForSequenceClassification.from_pretrained(
        str(model_dir)
    )


def tag_names_of(model) -> list[str]:
    """The tag set the model was trained with (saved in its config), not the current TAGS."""
    id2label = getattr(model.config, "id2label", None)
    if id2label and len(id2label) == model.config.num_labels:
        return [id2label[i] if i in id2label else id2label[str(i)] for i in range(len(id2label))]
    return TAGS


def bio_transition_mask(tags: list[str]) -> torch.Tensor:
    """allowed[prev, cur] under the BIO scheme: `I-X` may only follow `B-X` or `I-X`.

    Row index len(tags) is the virtual start state (only `O` and `B-*` may begin a sequence)."""
    n = len(tags)
    allowed = torch.ones(n + 1, n, dtype=torch.bool)
    for j, cur in enumerate(tags):
        if not cur.startswith("I-"):
            continue
        lab = cur[2:]
        for i, prev in enumerate(tags):
            allowed[i, j] = prev in (f"B-{lab}", f"I-{lab}")
        allowed[n, j] = False
    return allowed


def viterbi_decode(logprobs: torch.Tensor, allowed: torch.Tensor) -> list[int]:
    """Best tag sequence under hard transition constraints (no learned transition scores).

    `logprobs` is (seq, n_tags). This is constrained decoding, not a CRF: the model's scores are
    unchanged; only sequences that violate BIO are excluded."""
    seq, n = logprobs.shape
    neg = torch.finfo(logprobs.dtype).min
    trans = torch.where(allowed[:n], 0.0, neg)  # (n, n)
    start = torch.where(allowed[n], 0.0, neg)  # (n,)
    score = logprobs[0] + start
    back = []
    for t in range(1, seq):
        cand = score.unsqueeze(1) + trans  # (prev, cur)
        best, idx = cand.max(0)
        score = best + logprobs[t]
        back.append(idx)
    last = int(score.argmax())
    path = [last]
    for idx in reversed(back):
        last = int(idx[last])
        path.append(last)
    return path[::-1]


def predict_token_classifier(
    tok, model, decisions: list[Decision], batch_size: int = 16, decode: str = "argmax"
) -> None:
    """decode: "argmax" (independent per token) or "viterbi" (BIO-constrained best path)."""
    dev = device()
    model.to(dev).eval()
    tags_all = tag_names_of(model)
    allowed = bio_transition_mask(tags_all)
    items, _ = token_dataset(tok, decisions, with_labels=False)
    by_id = {d.decision_id: d for d in decisions}
    for d in decisions:
        d.spans = []
    for i in range(0, len(items), batch_size):
        chunk = items[i : i + batch_size]
        batch = _collate(tok, chunk, False)
        with torch.no_grad():
            logits = model(**{k: v.to(dev) for k, v in batch.items()}).logits
        if decode == "viterbi":
            lp = logits.log_softmax(-1).float().cpu()
            pred = [viterbi_decode(lp[k], allowed) for k in range(lp.shape[0])]
        else:
            pred = logits.argmax(-1).cpu().tolist()
        for (w, enc), tags in zip(chunk, pred, strict=True):
            offsets = enc["offset_mapping"]
            tag_names = [tags_all[t] for t in tags[: len(offsets)]]
            for s in tags_to_spans(w.text, offsets, tag_names):
                by_id[w.decision_id].spans.append(
                    {
                        "start": w.offset + s["start"],
                        "end": w.offset + s["end"],
                        "label": s["label"],
                        "text": s["text"],
                    }
                )
    for d in decisions:
        d.spans = dedupe(d.spans)


# --- outcome classification -----------------------------------------------------------------------


def train_outcome_classifier(
    train: list[Decision],
    model_name: str = DEFAULT_MODEL,
    epochs: int = 12,
    lr: float = 3e-5,
    batch_size: int = 8,
    seed: int = 0,
):
    seed_all(seed)
    tok = load_tokenizer(model_name)
    cfg = load_config(model_name, num_labels=len(OUTCOMES))
    model = AutoModelForSequenceClassification.from_pretrained(model_name, config=cfg)
    dev = device()
    model.to(dev)
    texts = [dispositiv(d.text) for d in train]
    labels = [OUTCOME2ID[d.outcome] for d in train]
    enc = tok(texts, truncation=True, max_length=MAX_LEN)
    items = [
        {
            "input_ids": enc["input_ids"][i],
            "attention_mask": enc["attention_mask"][i],
            "labels": labels[i],
        }
        for i in range(len(texts))
    ]

    def collate(b):
        out = tok.pad(
            [{k: x[k] for k in ("input_ids", "attention_mask")} for x in b], return_tensors="pt"
        )
        out["labels"] = torch.tensor([x["labels"] for x in b])
        return out

    loader = DataLoader(items, batch_size=batch_size, shuffle=True, collate_fn=collate)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    steps = epochs * len(loader)
    sched = get_linear_schedule_with_warmup(opt, int(0.1 * steps), steps)
    model.train()
    for _ in range(epochs):
        for batch in loader:
            batch = {k: v.to(dev) for k, v in batch.items()}
            loss = model(**batch).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad()
    return tok, model


@torch.no_grad()
def predict_outcome(tok, model, decisions: list[Decision], batch_size: int = 16) -> list[str]:
    dev = device()
    model.to(dev).eval()
    out: list[str] = []
    texts = [dispositiv(d.text) for d in decisions]
    for i in range(0, len(texts), batch_size):
        enc = tok(
            texts[i : i + batch_size],
            truncation=True,
            max_length=MAX_LEN,
            padding=True,
            return_tensors="pt",
        )
        logits = model(**{k: v.to(dev) for k, v in enc.items()}).logits
        out += [OUTCOMES[j] for j in logits.argmax(-1).cpu().tolist()]
    for d, o in zip(decisions, out, strict=True):
        d.outcome = o
    return out
