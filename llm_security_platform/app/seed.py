import json
from pathlib import Path

from llm_security_platform.app import db
from llm_security_platform.app.schemas import AttackCaseCreate


DEFAULT_CASES_PATH = Path(__file__).resolve().parents[1] / "data" / "attack_cases_v2.json"


def seed_cases(path=DEFAULT_CASES_PATH, tenant_id="default"):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    for item in payload:
        db.save_attack_case(AttackCaseCreate(**item), tenant_id=tenant_id)
    return len(payload)
