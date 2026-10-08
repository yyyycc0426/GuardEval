"""LoRA fine-tuned content-safety judge (HateXplain) with quantized inference.

Follow-up to the content-safety track: zero-shot LLM judges (local qwen3:8b,
cloud Gemini 2.5) over-flag 53-70% of benign posts. This runner fine-tunes a
small open model (Qwen3-1.7B) with LoRA as a 3-class sequence classifier on
the HateXplain train split, then evaluates it on the *same* seeded stratified
test sample used by the earlier judge reports, plus the full test split.

It also benchmarks inference of the same adapter under bf16 and 4-bit NF4
(bitsandbytes) weights: macro-F1, batch-1 latency, batched throughput and peak
GPU memory, so the quality / latency / memory trade-off is measured rather
than assumed.

Requires the optional fine-tuning environment (CUDA torch, transformers, peft,
accelerate, bitsandbytes). Example (from the repository root):

    python -m llm_security_platform.run_lora_safety_judge
    python -m llm_security_platform.run_lora_safety_judge --limit-train 256 --epochs 1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import statistics
from pathlib import Path
from time import perf_counter

import torch

from llm_security_platform.app.content_safety.classifiers import TfidfLogRegBaseline
from llm_security_platform.app.content_safety.hatexplain_loader import (
    DEFAULT_DATASET_PATH,
    LABELS,
    ContentSafetyRecord,
    label_distribution,
    load_records,
    split_records,
)
from llm_security_platform.app.content_safety.metrics import classification_metrics

ROOT = Path(__file__).resolve().parent
SEED = 20260628
LABEL2ID = {label: index for index, label in enumerate(LABELS)}


def stratified_sample(
    records: list[ContentSafetyRecord], per_class: int, seed: int = SEED
) -> list[ContentSafetyRecord]:
    """Same procedure as run_content_safety_benchmark, so samples are identical."""
    rng = random.Random(seed)
    balanced: list[ContentSafetyRecord] = []
    for label in LABELS:
        pool = [record for record in records if record.gold_label == label]
        rng.shuffle(pool)
        balanced.extend(pool[:per_class])
    rng.shuffle(balanced)
    return balanced


def load_tokenizer(model_id: str):
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    return tokenizer


def load_base_model(model_id: str, quantization: str):
    from transformers import AutoModelForSequenceClassification, BitsAndBytesConfig

    kwargs: dict = {
        "num_labels": len(LABELS),
        "id2label": dict(enumerate(LABELS)),
        "label2id": LABEL2ID,
    }
    if quantization == "nf4":
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
        kwargs["device_map"] = {"": 0}
    else:
        kwargs["dtype"] = torch.bfloat16
    model = AutoModelForSequenceClassification.from_pretrained(model_id, **kwargs)
    if quantization != "nf4":
        model.to("cuda")
    return model


def batches(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


@torch.no_grad()
def predict(model, tokenizer, texts: list[str], batch_size: int, max_len: int) -> list[str]:
    model.eval()
    predicted: list[str] = []
    for chunk in batches(texts, batch_size):
        encoded = tokenizer(
            chunk, truncation=True, max_length=max_len, padding=True, return_tensors="pt"
        ).to("cuda")
        with torch.autocast("cuda", dtype=torch.bfloat16):
            logits = model(**encoded).logits
        predicted.extend(LABELS[i] for i in logits.argmax(dim=-1).tolist())
    return predicted


def evaluate(model, tokenizer, records: list[ContentSafetyRecord], batch_size: int, max_len: int) -> dict:
    predicted = predict(model, tokenizer, [r.text for r in records], batch_size, max_len)
    return classification_metrics([r.gold_label for r in records], predicted)


def train(args, train_records, val_records) -> dict:
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import get_linear_schedule_with_warmup

    torch.manual_seed(SEED)
    rng = random.Random(SEED)
    tokenizer = load_tokenizer(args.model)
    model = load_base_model(args.model, "bf16")
    model.config.pad_token_id = tokenizer.pad_token_id
    lora = LoraConfig(
        task_type=TaskType.SEQ_CLS,
        r=args.rank,
        lora_alpha=args.rank * 2,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    )
    model = get_peft_model(model, lora)
    # Keep trainable LoRA / head weights in fp32; the frozen base stays bf16.
    for param in model.parameters():
        if param.requires_grad:
            param.data = param.data.float()
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())

    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad], lr=args.lr, weight_decay=0.0
    )
    steps_per_epoch = (len(train_records) + args.batch_size - 1) // args.batch_size
    scheduler = get_linear_schedule_with_warmup(
        optimizer, int(0.05 * steps_per_epoch * args.epochs), steps_per_epoch * args.epochs
    )

    history = []
    best_f1, best_epoch = -1.0, 0
    started = perf_counter()
    for epoch in range(1, args.epochs + 1):
        model.train()
        order = list(train_records)
        rng.shuffle(order)
        losses = []
        for chunk in batches(order, args.batch_size):
            encoded = tokenizer(
                [r.text for r in chunk],
                truncation=True,
                max_length=args.max_len,
                padding=True,
                return_tensors="pt",
            ).to("cuda")
            labels = torch.tensor([LABEL2ID[r.gold_label] for r in chunk], device="cuda")
            with torch.autocast("cuda", dtype=torch.bfloat16):
                loss = model(**encoded, labels=labels).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [p for p in model.parameters() if p.requires_grad], 1.0
            )
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            losses.append(loss.item())
        val_metrics = evaluate(model, tokenizer, val_records, 64, args.max_len)
        val_f1 = val_metrics["three_class"]["macro_f1"]
        history.append(
            {"epoch": epoch, "train_loss": round(statistics.mean(losses), 4), "val_macro_f1": val_f1}
        )
        print(json.dumps(history[-1]), flush=True)
        # Model selection uses the validation split only; the test split stays untouched.
        if val_f1 > best_f1:
            best_f1, best_epoch = val_f1, epoch
            model.save_pretrained(args.adapter_dir)
    tokenizer.save_pretrained(args.adapter_dir)
    del model
    torch.cuda.empty_cache()
    return {
        "trainable_params": trainable,
        "total_params": total,
        "trainable_ratio": round(trainable / total, 6),
        "epochs": args.epochs,
        "best_epoch": best_epoch,
        "best_val_macro_f1": best_f1,
        "history": history,
        "train_seconds": round(perf_counter() - started, 1),
    }


def benchmark_inference(args, quantization: str, sample, test_records) -> dict:
    from peft import PeftModel

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    tokenizer = load_tokenizer(args.adapter_dir)
    base = load_base_model(args.model, quantization)
    base.config.pad_token_id = tokenizer.pad_token_id
    model = PeftModel.from_pretrained(base, args.adapter_dir)
    model.eval()
    texts = [r.text for r in sample]

    predict(model, tokenizer, texts[:8], 8, args.max_len)  # warm-up
    torch.cuda.synchronize()
    single_ms = []
    for text in texts:
        started = perf_counter()
        predict(model, tokenizer, [text], 1, args.max_len)
        torch.cuda.synchronize()
        single_ms.append((perf_counter() - started) * 1000)

    started = perf_counter()
    predict(model, tokenizer, [r.text for r in test_records], 32, args.max_len)
    torch.cuda.synchronize()
    batched_seconds = perf_counter() - started

    result = {
        "quantization": quantization,
        "sample_metrics": evaluate(model, tokenizer, sample, 32, args.max_len),
        "full_test_metrics": evaluate(model, tokenizer, test_records, 32, args.max_len),
        "latency_bs1_ms_mean": round(statistics.mean(single_ms), 2),
        "latency_bs1_ms_p95": round(sorted(single_ms)[int(0.95 * len(single_ms)) - 1], 2),
        "throughput_bs32_posts_per_s": round(len(test_records) / batched_seconds, 1),
        "peak_gpu_memory_mb": round(torch.cuda.max_memory_allocated() / 2**20, 1),
    }
    del model, base
    torch.cuda.empty_cache()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="LoRA content-safety judge on HateXplain.")
    parser.add_argument("--model", default="Qwen/Qwen3-1.7B")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-len", type=int, default=128)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--limit-train", type=int, default=None, help="smoke-test subset")
    parser.add_argument("--skip-train", action="store_true", help="reuse saved adapter")
    parser.add_argument(
        "--adapter-dir", default=str(ROOT / "artifacts" / "lora_safety_judge_qwen3_1.7b")
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "reports" / "content_safety_hatexplain_lora_qwen3_1.7b.json"),
    )
    args = parser.parse_args()

    grouped = split_records(load_records())
    train_records, val_records, test_records = grouped["train"], grouped["val"], grouped["test"]
    if args.limit_train:
        train_records = train_records[: args.limit_train]
    sample = stratified_sample(test_records, 100)
    subset_90 = stratified_sample(test_records, 30)  # matches the Gemini 2.5 report

    training = None
    if not args.skip_train:
        training = train(args, train_records, val_records)

    inference = []
    for quantization in ("bf16", "nf4"):
        try:
            inference.append(benchmark_inference(args, quantization, sample, test_records))
        except Exception as exc:  # e.g. bitsandbytes unsupported on this GPU/OS
            inference.append({"quantization": quantization, "error": f"{type(exc).__name__}: {exc}"})
        print(json.dumps({k: v for k, v in inference[-1].items() if "metrics" not in k}), flush=True)

    # Re-score the bf16 model on the 90-post subset used by the Gemini report.
    from peft import PeftModel

    tokenizer = load_tokenizer(args.adapter_dir)
    base = load_base_model(args.model, "bf16")
    base.config.pad_token_id = tokenizer.pad_token_id
    model = PeftModel.from_pretrained(base, args.adapter_dir)
    subset_90_metrics = evaluate(model, tokenizer, subset_90, 32, args.max_len)

    tfidf = TfidfLogRegBaseline().fit(grouped["train"])
    tfidf_full = classification_metrics(
        [r.gold_label for r in test_records], tfidf.predict_batch([r.text for r in test_records])
    )

    report = {
        "dataset": "hatexplain",
        "dataset_sha256": hashlib.sha256(DEFAULT_DATASET_PATH.read_bytes()).hexdigest(),
        "splits": {name: len(items) for name, items in grouped.items()},
        "train_label_distribution": label_distribution(train_records),
        "classifier": "lora_seq_cls",
        "base_model": args.model,
        "lora": {"rank": args.rank, "alpha": args.rank * 2, "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"]},
        "hyperparameters": {
            "epochs": args.epochs,
            "lr": args.lr,
            "batch_size": args.batch_size,
            "max_len": args.max_len,
            "seed": SEED,
            "limit_train": args.limit_train,
        },
        "sampling": f"stratified_100_per_class_seed_{SEED}",
        "environment": {
            "gpu": torch.cuda.get_device_name(0),
            "torch": torch.__version__,
            "python": platform.python_version(),
        },
        "training": training,
        "inference": inference,
        "subset_90_metrics_bf16": subset_90_metrics,
        "tfidf_full_test_metrics": tfidf_full,
    }
    output = Path(args.output)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"report written to {output}")


if __name__ == "__main__":
    main()
