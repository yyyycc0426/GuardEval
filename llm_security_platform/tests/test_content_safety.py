import json
import tempfile
import unittest
from pathlib import Path

from llm_security_platform.app.content_safety.classifiers import (
    LlmJudgeClassifier,
    MajorityBaseline,
    TfidfLogRegBaseline,
    build_classifier,
)
from llm_security_platform.app.content_safety.hatexplain_loader import (
    LABELS,
    load_records,
    split_records,
)
from llm_security_platform.app.content_safety.metrics import classification_metrics
from llm_security_platform.app.content_safety.rationale import (
    aggregate_rationale,
    token_overlap,
)
from llm_security_platform.content_safety_gate import evaluate_gate


def _annot(label):
    return {"label": label, "annotator_id": 1, "target": ["African"] if label != "normal" else ["None"]}


def _write_dataset(tmp):
    data = {
        "p_hate": {
            "post_id": "p_hate",
            "annotators": [_annot("hatespeech"), _annot("hatespeech"), _annot("offensive")],
            "rationales": [[1, 0, 1], [1, 0, 0]],
            "post_tokens": ["a", "b", "c"],
        },
        "p_normal": {
            "post_id": "p_normal",
            "annotators": [_annot("normal"), _annot("normal"), _annot("normal")],
            "rationales": [],
            "post_tokens": ["hello", "world"],
        },
        "p_tie": {  # all three differ -> excluded
            "post_id": "p_tie",
            "annotators": [_annot("normal"), _annot("offensive"), _annot("hatespeech")],
            "rationales": [],
            "post_tokens": ["x"],
        },
    }
    dataset_path = Path(tmp) / "dataset.json"
    splits_path = Path(tmp) / "splits.json"
    dataset_path.write_text(json.dumps(data), encoding="utf-8")
    splits_path.write_text(
        json.dumps({"train": ["p_normal"], "test": ["p_hate"]}), encoding="utf-8"
    )
    return dataset_path, splits_path


class LoaderTests(unittest.TestCase):
    def test_majority_vote_exclusion_and_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset_path, splits_path = _write_dataset(tmp)
            records = load_records(dataset_path, splits_path)
            by_id = {r.post_id: r for r in records}
            self.assertNotIn("p_tie", by_id)  # no majority -> dropped
            self.assertEqual(by_id["p_hate"].gold_label, "hatespeech")
            self.assertEqual(by_id["p_hate"].toxic_label, "toxic")
            self.assertEqual(by_id["p_normal"].toxic_label, "non-toxic")
            self.assertEqual(by_id["p_hate"].rationale_mask, [1, 0, 1])  # union
            self.assertEqual(by_id["p_hate"].targets, ["African"])
            self.assertEqual(by_id["p_hate"].text, "a b c")

    def test_split_grouping(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset_path, splits_path = _write_dataset(tmp)
            grouped = split_records(load_records(dataset_path, splits_path))
            self.assertEqual([r.post_id for r in grouped["train"]], ["p_normal"])
            self.assertEqual([r.post_id for r in grouped["test"]], ["p_hate"])


class MetricsTests(unittest.TestCase):
    def test_perfect_prediction(self):
        expected = ["normal", "offensive", "hatespeech"]
        metrics = classification_metrics(expected, list(expected))
        self.assertEqual(metrics["three_class"]["accuracy"], 1.0)
        self.assertEqual(metrics["three_class"]["macro_f1"], 1.0)
        self.assertEqual(metrics["binary_toxic"]["accuracy"], 1.0)

    def test_confusion_matrix_shape(self):
        metrics = classification_metrics(["normal", "hatespeech"], ["offensive", "hatespeech"])
        matrix = metrics["three_class"]["confusion_matrix"]
        self.assertEqual(matrix["labels"], LABELS)
        self.assertEqual(len(matrix["matrix"]), len(LABELS))


class ClassifierTests(unittest.TestCase):
    def _train(self):
        return [
            type("R", (), {"text": "i love sunny days", "gold_label": "normal"})(),
            type("R", (), {"text": "great weather today friend", "gold_label": "normal"})(),
            type("R", (), {"text": "you are a stupid idiot", "gold_label": "offensive"})(),
            type("R", (), {"text": "what an idiot moron", "gold_label": "offensive"})(),
            type("R", (), {"text": "i hate that ethnic group", "gold_label": "hatespeech"})(),
            type("R", (), {"text": "those people are subhuman", "gold_label": "hatespeech"})(),
        ]

    def test_majority_baseline(self):
        clf = MajorityBaseline().fit(self._train())
        self.assertIn(clf.predict("anything"), LABELS)

    def test_tfidf_baseline_predicts_valid_labels(self):
        clf = TfidfLogRegBaseline().fit(self._train())
        for label in clf.predict_batch(["sunny friend", "stupid idiot", "subhuman people"]):
            self.assertIn(label, LABELS)

    def test_tfidf_requires_fit(self):
        with self.assertRaises(RuntimeError):
            TfidfLogRegBaseline().predict("text")

    def test_llm_mock_returns_valid_label(self):
        clf = build_classifier("llm", provider="mock")
        self.assertIsInstance(clf, LlmJudgeClassifier)
        self.assertIn(clf.predict("you are an idiot"), LABELS)

    def test_unknown_classifier_raises(self):
        with self.assertRaises(ValueError):
            build_classifier("does_not_exist")


class RationaleTests(unittest.TestCase):
    def test_token_overlap_perfect_and_partial(self):
        perfect = token_overlap([1, 0, 1], [1, 0, 1])
        self.assertEqual(perfect["f1"], 1.0)
        self.assertEqual(perfect["iou"], 1.0)
        partial = token_overlap([1, 1, 0], [1, 0, 1])  # tp1 fp1 fn1
        self.assertEqual((partial["tp"], partial["fp"], partial["fn"]), (1, 1, 1))
        self.assertEqual(partial["iou"], round(1 / 3, 4))

    def test_token_overlap_length_mismatch(self):
        with self.assertRaises(ValueError):
            token_overlap([1, 0], [1])

    def test_aggregate(self):
        agg = aggregate_rationale([([1, 0], [1, 0]), ([1, 1], [1, 0])])
        self.assertEqual(agg["evaluated_posts"], 2)
        self.assertIn("macro_f1", agg)
        self.assertEqual(aggregate_rationale([])["evaluated_posts"], 0)

    def test_explain_tokens_aligns_and_is_binary(self):
        clf = TfidfLogRegBaseline().fit(
            [
                type("R", (), {"text": "i love sunny days friend", "gold_label": "normal"})(),
                type("R", (), {"text": "happy bright morning friend", "gold_label": "normal"})(),
                type("R", (), {"text": "you stupid idiot moron", "gold_label": "offensive"})(),
                type("R", (), {"text": "what an idiot stupid", "gold_label": "offensive"})(),
                type("R", (), {"text": "those people are subhuman vermin", "gold_label": "hatespeech"})(),
                type("R", (), {"text": "subhuman vermin group", "gold_label": "hatespeech"})(),
            ]
        )
        tokens = ["you", "stupid", "idiot"]
        mask = clf.explain_tokens(tokens, "offensive")
        self.assertEqual(len(mask), len(tokens))
        self.assertTrue(all(v in (0, 1) for v in mask))


class GateTests(unittest.TestCase):
    def _report(self, macro_f1):
        return {"metrics": {"three_class": {"macro_f1": macro_f1}}}

    def test_gate_passes(self):
        self.assertEqual(
            evaluate_gate(self._report(0.65), self._report(0.19)), []
        )

    def test_gate_flags_low_f1_and_margin(self):
        failures = evaluate_gate(self._report(0.30), self._report(0.19))
        self.assertEqual(len(failures), 2)


if __name__ == "__main__":
    unittest.main()
