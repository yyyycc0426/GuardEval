"""Rationale / explainability evaluation for the content-safety track.

HateXplain ships per-annotator token-level rationales (which tokens make a post
hateful/offensive). This module scores whether a classifier "looks at" the same
tokens a human would: it compares a model's predicted token-importance mask
against the human rationale mask with token-level precision / recall / F1 and IoU.

This directly extends the platform's stage-3 "evidence-citing judge" idea from
the attack pipeline into the content-safety track, and is the standout signal
HateXplain offers over label-only datasets (e.g. Davidson).
"""

from __future__ import annotations


def token_overlap(pred_mask: list[int], gold_mask: list[int]) -> dict:
    """Token-level overlap between a predicted and a human rationale mask.

    Both masks are 0/1 lists aligned to the same token sequence.
    """
    if len(pred_mask) != len(gold_mask):
        raise ValueError("pred_mask and gold_mask must be the same length")
    tp = sum(1 for p, g in zip(pred_mask, gold_mask) if p and g)
    fp = sum(1 for p, g in zip(pred_mask, gold_mask) if p and not g)
    fn = sum(1 for p, g in zip(pred_mask, gold_mask) if not p and g)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    iou = tp / (tp + fp + fn) if (tp + fp + fn) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "iou": round(iou, 4),
    }


def aggregate_rationale(pairs: list[tuple[list[int], list[int]]]) -> dict:
    """Macro-average token-overlap metrics over many (pred, gold) mask pairs.

    Only call with posts that actually have a human rationale (non-empty gold).
    """
    if not pairs:
        return {"evaluated_posts": 0}
    per_post = [token_overlap(pred, gold) for pred, gold in pairs]
    keys = ("precision", "recall", "f1", "iou")
    macro = {f"macro_{k}": round(sum(p[k] for p in per_post) / len(per_post), 4) for k in keys}
    macro["evaluated_posts"] = len(per_post)
    return macro
