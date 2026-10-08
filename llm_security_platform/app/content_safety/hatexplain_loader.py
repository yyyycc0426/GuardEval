"""Load the HateXplain dataset into unified content-safety records.

HateXplain (https://github.com/hate-alert/HateXplain) ships one ``dataset.json``
keyed by ``post_id``. Each post carries three annotator labels
(``hatespeech`` / ``offensive`` / ``normal``), optional target communities, and
per-annotator token-level ``rationales``. Ground truth is the majority label;
posts without a majority (all three annotators disagree) are dropped, which is
the convention the official 8:1:1 ``post_id_divisions.json`` split already
follows.

The loader is deliberately read-only and deterministic so the benchmark is
reproducible.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
import json

# Three-class scheme from HateXplain's classes.npy.
LABELS: list[str] = ["normal", "offensive", "hatespeech"]
# Two-class scheme from HateXplain's classes_two.npy.
TOXIC_LABELS: list[str] = ["non-toxic", "toxic"]

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "hatexplain"
DEFAULT_DATASET_PATH = DATA_DIR / "dataset.json"
DEFAULT_SPLITS_PATH = DATA_DIR / "post_id_divisions.json"


@dataclass
class ContentSafetyRecord:
    post_id: str
    text: str
    tokens: list[str]
    gold_label: str
    toxic_label: str
    annotator_labels: list[str]
    targets: list[str] = field(default_factory=list)
    # Union of per-annotator token rationale masks (1 = at least one annotator
    # marked the token as part of the reason). Empty for normal posts.
    rationale_mask: list[int] = field(default_factory=list)
    split: str = "unknown"


def _majority_label(labels: list[str]) -> str | None:
    counts = Counter(labels)
    label, count = counts.most_common(1)[0]
    return label if count >= 2 else None


def _union_rationale(rationales: list[list[int]], length: int) -> list[int]:
    if not rationales:
        return []
    mask = [0] * length
    for row in rationales:
        for index, value in enumerate(row[:length]):
            if value:
                mask[index] = 1
    return mask


def _toxic_label(gold_label: str) -> str:
    return "non-toxic" if gold_label == "normal" else "toxic"


def load_records(
    dataset_path: str | Path = DEFAULT_DATASET_PATH,
    splits_path: str | Path = DEFAULT_SPLITS_PATH,
) -> list[ContentSafetyRecord]:
    """Load all majority-labeled posts as unified records, tagged with split."""
    raw = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    split_of: dict[str, str] = {}
    if Path(splits_path).exists():
        divisions = json.loads(Path(splits_path).read_text(encoding="utf-8"))
        for split_name, ids in divisions.items():
            for post_id in ids:
                split_of[post_id] = split_name

    records: list[ContentSafetyRecord] = []
    for post_id, entry in raw.items():
        annotator_labels = [a["label"] for a in entry.get("annotators", [])]
        gold = _majority_label(annotator_labels)
        if gold is None:
            continue  # no majority -> excluded (matches official splits)
        tokens = entry.get("post_tokens", [])
        targets = sorted(
            {
                target
                for annotator in entry.get("annotators", [])
                for target in annotator.get("target", [])
                if target and target != "None"
            }
        )
        records.append(
            ContentSafetyRecord(
                post_id=post_id,
                text=" ".join(tokens),
                tokens=tokens,
                gold_label=gold,
                toxic_label=_toxic_label(gold),
                annotator_labels=annotator_labels,
                targets=targets,
                rationale_mask=_union_rationale(entry.get("rationales", []), len(tokens)),
                split=split_of.get(post_id, "unknown"),
            )
        )
    return records


def split_records(
    records: list[ContentSafetyRecord],
) -> dict[str, list[ContentSafetyRecord]]:
    """Group records by official split name (train / val / test / unknown)."""
    grouped: dict[str, list[ContentSafetyRecord]] = {}
    for record in records:
        grouped.setdefault(record.split, []).append(record)
    return grouped


def label_distribution(records: list[ContentSafetyRecord]) -> dict[str, int]:
    return dict(Counter(record.gold_label for record in records))
