import argparse
import json
from pathlib import Path


def build_report(packet):
    completed = [item for item in packet["items"] if item["human_attack_success"] is not None]
    raw_completed = [item for item in completed if item.get("raw_model_compromise") is not None]

    delivered_attack_matches = sum(
        item["detector_result"]["attack_success"] == item["human_attack_success"]
        for item in completed
    )
    delivered_outcome_matches = sum(
        item["detector_result"]["outcome_label"] == item["human_final_label"]
        for item in completed
    )
    raw_attack_matches = sum(
        item["judge_result"]["attack_success"] == item["raw_model_compromise"]
        for item in raw_completed
    )

    delivered_agreement = (
        round(delivered_attack_matches / len(completed), 4) if completed else None
    )
    outcome_agreement = (
        round(delivered_outcome_matches / len(completed), 4) if completed else None
    )
    raw_agreement = round(raw_attack_matches / len(raw_completed), 4) if raw_completed else None

    return {
        "status": "complete" if len(completed) == len(packet["items"]) else "incomplete",
        "metric_contract_version": "raw_delivered_v2",
        "selected_count": len(packet["items"]),
        "reviewed_count": len(completed),
        "raw_reviewed_count": len(raw_completed),
        "raw_judge_human_raw_agreement": raw_agreement,
        "delivered_detector_human_delivered_agreement": delivered_agreement,
        "delivered_detector_human_outcome_agreement": outcome_agreement,
        # Backward-compatible aliases now use like-for-like delivered metrics.
        "judge_human_attack_success_agreement": delivered_agreement,
        "judge_human_outcome_agreement": outcome_agreement,
    }


def main():
    parser = argparse.ArgumentParser(description="Compute Judge/human agreement after review")
    parser.add_argument("--packet", default="llm_security_platform/reports/real_model_human_review_packet.json")
    parser.add_argument("--output", default="llm_security_platform/reports/real_model_human_review_report.json")
    args = parser.parse_args()
    packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    report = build_report(packet)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
