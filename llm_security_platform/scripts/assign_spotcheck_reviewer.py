import argparse
import json
from pathlib import Path


def assign_reviewer(packet: dict, reviewer: str) -> dict:
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("reviewer must not be empty")

    updated = dict(packet)
    updated["human_reviewer"] = reviewer
    updated["status"] = "human_spot_check_in_progress"
    updated_items = []
    for item in packet["items"]:
        updated_item = dict(item)
        updated_item["reviewer"] = reviewer
        updated_item["review_status"] = "awaiting_human_confirmation"
        updated_items.append(updated_item)
    updated["items"] = updated_items
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assign one human reviewer to an assisted-review spot-check packet."
    )
    parser.add_argument("--reviewer", required=True, help="Reviewer name or stable identifier")
    parser.add_argument(
        "--packet",
        default="llm_security_platform/.test_artifacts/codex_assisted_review_spotcheck.json",
    )
    args = parser.parse_args()

    path = Path(args.packet)
    packet = json.loads(path.read_text(encoding="utf-8"))
    updated = assign_reviewer(packet, args.reviewer)
    path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "packet": str(path),
                "reviewer": args.reviewer.strip(),
                "assigned_count": len(updated["items"]),
                "status": updated["status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
