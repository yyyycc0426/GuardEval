import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime

from llm_security_platform.app.config import DATABASE_PATH


def now_iso():
    return datetime.now(UTC).isoformat()


_db_initialized = False


@contextmanager
def connection():
    global _db_initialized
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _db_initialized:
        _db_initialized = True
        try:
            init_db()
        except Exception:
            _db_initialized = False
            raise
    conn = sqlite3.connect(DATABASE_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
    except Exception:
        pass
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS attack_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                name TEXT NOT NULL,
                risk_type TEXT NOT NULL,
                prompt TEXT NOT NULL,
                system_prompt TEXT NOT NULL,
                success_indicators_json TEXT NOT NULL,
                safe_response_indicators_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(case_id, tenant_id)
            );

            CREATE TABLE IF NOT EXISTS evaluation_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                defense_policy TEXT NOT NULL,
                status TEXT NOT NULL,
                case_count INTEGER NOT NULL,
                run_metadata_json TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT NOT NULL DEFAULT 'default',
                created_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS evaluation_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                case_id TEXT NOT NULL,
                risk_type TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                defense_policy TEXT NOT NULL,
                status TEXT NOT NULL,
                original_prompt TEXT NOT NULL,
                effective_prompt TEXT NOT NULL,
                response_text TEXT NOT NULL,
                detector_json TEXT NOT NULL,
                latency_ms REAL NOT NULL,
                token_usage_json TEXT NOT NULL DEFAULT '{}',
                estimated_cost REAL NOT NULL DEFAULT 0,
                model_call_json TEXT NOT NULL DEFAULT '{}',
                defense_json TEXT NOT NULL DEFAULT '[]',
                raw_response_text TEXT NOT NULL DEFAULT '',
                review_required INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES evaluation_runs(id)
            );

            CREATE INDEX IF NOT EXISTS idx_security_results_run_id
                ON evaluation_results(run_id);
            CREATE INDEX IF NOT EXISTS idx_security_results_risk_type
                ON evaluation_results(risk_type);

            CREATE TABLE IF NOT EXISTS layered_assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                model_response TEXT NOT NULL,
                assessment_json TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS human_review_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id INTEGER NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                review_reasons_json TEXT NOT NULL,
                human_final_label TEXT,
                human_attack_success INTEGER,
                reviewer_note TEXT,
                reviewer TEXT,
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                FOREIGN KEY(assessment_id) REFERENCES layered_assessments(id)
            );

            CREATE INDEX IF NOT EXISTS idx_human_review_status
                ON human_review_queue(status);

            CREATE TABLE IF NOT EXISTS defense_audits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                audit_id TEXT NOT NULL UNIQUE,
                run_id INTEGER,
                case_id TEXT NOT NULL,
                policy_name TEXT NOT NULL,
                action TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES evaluation_runs(id)
            );

            CREATE INDEX IF NOT EXISTS idx_defense_audits_run_id
                ON defense_audits(run_id);
            CREATE INDEX IF NOT EXISTS idx_defense_audits_case_id
                ON defense_audits(case_id);

            CREATE TABLE IF NOT EXISTS defense_policies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                version TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                description TEXT,
                config_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(name, version, tenant_id)
            );
            """
        )

        # Apply schema migrations dynamically for SQLite
        # Migrate attack_cases
        case_table_exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='attack_cases'").fetchone()
        if case_table_exists:
            case_columns = {row["name"] for row in conn.execute("PRAGMA table_info(attack_cases)").fetchall()}
            if "tenant_id" not in case_columns:
                conn.execute("ALTER TABLE attack_cases RENAME TO attack_cases_old")
                conn.execute(
                    """
                    CREATE TABLE attack_cases (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        case_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL DEFAULT 'default',
                        name TEXT NOT NULL,
                        risk_type TEXT NOT NULL,
                        prompt TEXT NOT NULL,
                        system_prompt TEXT NOT NULL,
                        success_indicators_json TEXT NOT NULL,
                        safe_response_indicators_json TEXT NOT NULL,
                        metadata_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(case_id, tenant_id)
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO attack_cases (id, case_id, tenant_id, name, risk_type, prompt, system_prompt,
                                              success_indicators_json, safe_response_indicators_json, metadata_json, created_at)
                    SELECT id, case_id, 'default', name, risk_type, prompt, system_prompt,
                           success_indicators_json, safe_response_indicators_json, metadata_json, created_at FROM attack_cases_old
                    """
                )
                conn.execute("DROP TABLE attack_cases_old")

        # Migrate evaluation_runs
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(evaluation_runs)").fetchall()}
        if "tenant_id" not in columns:
            conn.execute("ALTER TABLE evaluation_runs ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'")
        if "run_metadata_json" not in columns:
            conn.execute("ALTER TABLE evaluation_runs ADD COLUMN run_metadata_json TEXT NOT NULL DEFAULT '{}'")

        # Migrate evaluation_results
        result_columns = {row["name"] for row in conn.execute("PRAGMA table_info(evaluation_results)").fetchall()}
        if "tenant_id" not in result_columns:
            conn.execute("ALTER TABLE evaluation_results ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'")
        for column_name, definition in (
            ("token_usage_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("estimated_cost", "REAL NOT NULL DEFAULT 0"),
            ("model_call_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("defense_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("raw_response_text", "TEXT NOT NULL DEFAULT ''"),
            ("review_required", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if column_name not in result_columns:
                conn.execute(f"ALTER TABLE evaluation_results ADD COLUMN {column_name} {definition}")

        # Migrate defense_audits
        audit_columns = {row["name"] for row in conn.execute("PRAGMA table_info(defense_audits)").fetchall()}
        if "tenant_id" not in audit_columns:
            conn.execute("ALTER TABLE defense_audits ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'")

        # Migrate layered_assessments
        assess_columns = {row["name"] for row in conn.execute("PRAGMA table_info(layered_assessments)").fetchall()}
        if "tenant_id" not in assess_columns:
            conn.execute("ALTER TABLE layered_assessments ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'")

        # Migrate defense_policies unique constraint if exists but lacks tenant_id
        policy_table_exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='defense_policies'").fetchone()
        if policy_table_exists:
            policy_columns = {row["name"] for row in conn.execute("PRAGMA table_info(defense_policies)").fetchall()}
            if "tenant_id" not in policy_columns:
                conn.execute("ALTER TABLE defense_policies RENAME TO defense_policies_old")
                conn.execute(
                    """
                    CREATE TABLE defense_policies (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        version TEXT NOT NULL,
                        tenant_id TEXT NOT NULL DEFAULT 'default',
                        description TEXT,
                        config_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        UNIQUE(name, version, tenant_id)
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO defense_policies (id, name, version, tenant_id, description, config_json, created_at)
                    SELECT id, name, version, 'default', description, config_json, created_at FROM defense_policies_old
                    """
                )
                conn.execute("DROP TABLE defense_policies_old")

        # Seed default policies if none exist
        count = conn.execute("SELECT COUNT(*) FROM defense_policies").fetchone()[0]
        if count == 0:
            default_policies = [
                ("input_defense", "input_v1", "Default input scanning defense policy", "{}"),
                ("rag_defense", "rag_v1", "Default RAG data isolation and sanitize policy", "{}"),
                ("output_defense", "output_v1", "Default output redaction policy", "{}"),
                ("baseline", "baseline_v1", "Default baseline policy", "{}"),
            ]
            conn.executemany(
                """
                INSERT INTO defense_policies (name, version, tenant_id, description, config_json, created_at)
                VALUES (?, ?, 'default', ?, ?, ?)
                """,
                [(name, version, desc, config, now_iso()) for name, version, desc, config in default_policies]
            )


def save_attack_case(case, tenant_id="default"):
    values = (
        case.case_id,
        tenant_id,
        case.name,
        case.risk_type,
        case.prompt,
        case.system_prompt,
        json.dumps(case.success_indicators, ensure_ascii=False),
        json.dumps(case.safe_response_indicators, ensure_ascii=False),
        json.dumps(case.metadata, ensure_ascii=False),
        now_iso(),
    )
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO attack_cases (
                case_id, tenant_id, name, risk_type, prompt, system_prompt,
                success_indicators_json, safe_response_indicators_json,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(case_id, tenant_id) DO UPDATE SET
                name = excluded.name,
                risk_type = excluded.risk_type,
                prompt = excluded.prompt,
                system_prompt = excluded.system_prompt,
                success_indicators_json = excluded.success_indicators_json,
                safe_response_indicators_json = excluded.safe_response_indicators_json,
                metadata_json = excluded.metadata_json
            """,
            values,
        )


def _decode_case(row):
    item = dict(row)
    item["success_indicators"] = json.loads(item.pop("success_indicators_json"))
    item["safe_response_indicators"] = json.loads(item.pop("safe_response_indicators_json"))
    item["metadata"] = json.loads(item.pop("metadata_json"))
    return item


def list_attack_cases(case_ids=None, tenant_id="default"):
    with connection() as conn:
        if case_ids:
            placeholders = ",".join("?" for _ in case_ids)
            query = f"""
                SELECT * FROM attack_cases 
                WHERE case_id IN ({placeholders}) 
                  AND (tenant_id = ? OR tenant_id = 'default') 
                ORDER BY id
            """
            params = tuple(case_ids) + (tenant_id,)
            rows = conn.execute(query, params).fetchall()
        else:
            query = """
                SELECT * FROM attack_cases 
                WHERE tenant_id = ? OR tenant_id = 'default' 
                ORDER BY id
            """
            rows = conn.execute(query, (tenant_id,)).fetchall()
    return [_decode_case(row) for row in rows]


def create_run(name, provider, model, defense_policy, case_count, run_metadata, tenant_id="default"):
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO evaluation_runs (
                name, provider, model, defense_policy, status, case_count,
                run_metadata_json, tenant_id, created_at
            ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?)
            """,
            (
                name,
                provider,
                model,
                defense_policy,
                case_count,
                json.dumps(run_metadata, ensure_ascii=False),
                tenant_id,
                now_iso(),
            ),
        )
        return cursor.lastrowid


def complete_run(run_id, status="completed"):
    with connection() as conn:
        conn.execute(
            "UPDATE evaluation_runs SET status = ?, completed_at = ? WHERE id = ?",
            (status, now_iso(), run_id),
        )


def get_run(run_id, tenant_id="default"):
    with connection() as conn:
        row = conn.execute("SELECT * FROM evaluation_runs WHERE id = ? AND tenant_id = ?", (run_id, tenant_id)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["run_metadata"] = json.loads(item.pop("run_metadata_json") or "{}")
    return item


def save_result(result, tenant_id="default"):
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO evaluation_results (
                run_id, case_id, risk_type, provider, model, defense_policy,
                status, original_prompt, effective_prompt, response_text,
                detector_json, latency_ms, token_usage_json, estimated_cost,
                model_call_json, defense_json, raw_response_text, review_required,
                error, tenant_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.run_id,
                result.case_id,
                result.risk_type,
                result.provider,
                result.model,
                result.defense_policy,
                result.status,
                result.original_prompt,
                result.effective_prompt,
                result.response_text,
                result.detector.model_dump_json(),
                result.latency_ms,
                json.dumps(result.token_usage, ensure_ascii=False),
                result.estimated_cost,
                json.dumps(result.model_call, ensure_ascii=False),
                json.dumps(
                    [decision.model_dump() for decision in result.defense_decisions],
                    ensure_ascii=False,
                ),
                result.raw_response_text,
                int(result.review_required),
                result.error,
                tenant_id,
                result.created_at,
            ),
        )
        return cursor.lastrowid


def list_results(run_id, tenant_id="default"):
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM evaluation_results WHERE run_id = ? AND tenant_id = ? ORDER BY id",
            (run_id, tenant_id),
        ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        item["detector"] = json.loads(item.pop("detector_json"))
        item["token_usage"] = json.loads(item.pop("token_usage_json") or "{}")
        item["model_call"] = json.loads(item.pop("model_call_json") or "{}")
        item["defense_decisions"] = json.loads(item.pop("defense_json") or "[]")
        item["review_required"] = bool(item["review_required"])
        results.append(item)
    return results


def save_layered_assessment(assessment, model_response, tenant_id="default"):
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO layered_assessments (case_id, model_response, assessment_json, tenant_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (assessment.case_id, model_response, assessment.model_dump_json(), tenant_id, now_iso()),
        )
        return cursor.lastrowid


def create_review_item(assessment_id, assessment):
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO human_review_queue (
                assessment_id, status, review_reasons_json, created_at
            ) VALUES (?, 'pending', ?, ?)
            ON CONFLICT(assessment_id) DO NOTHING
            """,
            (assessment_id, json.dumps(assessment.review_reasons, ensure_ascii=False), now_iso()),
        )
        return cursor.lastrowid


def list_review_items(status="pending", tenant_id="default"):
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT q.*, a.case_id, a.model_response, a.assessment_json
            FROM human_review_queue q
            JOIN layered_assessments a ON a.id = q.assessment_id
            WHERE (? IS NULL OR q.status = ?) AND a.tenant_id = ?
            ORDER BY q.id
            """,
            (status, status, tenant_id),
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["review_reasons"] = json.loads(item.pop("review_reasons_json"))
        item["assessment"] = json.loads(item.pop("assessment_json"))
        if item["human_attack_success"] is not None:
            item["human_attack_success"] = bool(item["human_attack_success"])
        items.append(item)
    return items


def complete_review(review_id, update, tenant_id="default"):
    with connection() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM human_review_queue q
            JOIN layered_assessments a ON a.id = q.assessment_id
            WHERE q.id = ? AND a.tenant_id = ?
            """,
            (review_id, tenant_id)
        ).fetchone()
        if not row:
            return False
        cursor = conn.execute(
            """
            UPDATE human_review_queue
            SET status = 'completed', human_final_label = ?, human_attack_success = ?,
                reviewer_note = ?, reviewer = ?, reviewed_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (
                update.human_final_label,
                int(update.human_attack_success),
                update.reviewer_note,
                update.reviewer,
                now_iso(),
                review_id,
            ),
        )
        return cursor.rowcount == 1


def human_review_metrics(tenant_id="default"):
    completed = list_review_items("completed", tenant_id=tenant_id)
    if not completed:
        return {
            "completed_reviews": 0,
            "judge_human_attack_success_agreement": 0.0,
            "judge_human_outcome_agreement": 0.0,
            "attack_success_conflicts": 0,
            "outcome_conflicts": 0,
        }
    attack_matches = 0
    outcome_matches = 0
    for item in completed:
        judge = item["assessment"]["judge_decision"]
        attack_matches += judge["attack_success"] == item["human_attack_success"]
        outcome_matches += judge["outcome"] == item["human_final_label"]
    total = len(completed)
    return {
        "completed_reviews": total,
        "judge_human_attack_success_agreement": round(attack_matches / total, 4),
        "judge_human_outcome_agreement": round(outcome_matches / total, 4),
        "attack_success_conflicts": total - attack_matches,
        "outcome_conflicts": total - outcome_matches,
    }


def save_defense_audit(run_id, case_id, decision, tenant_id="default"):
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO defense_audits (
                audit_id, run_id, case_id, policy_name, action,
                risk_level, decision_json, tenant_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.audit_id,
                run_id,
                case_id,
                decision.policy_name,
                decision.action,
                decision.risk_level,
                decision.model_dump_json(),
                tenant_id,
                now_iso(),
            ),
        )


def list_defense_audits(run_id=None, tenant_id="default"):
    with connection() as conn:
        if run_id is None:
            rows = conn.execute("SELECT * FROM defense_audits WHERE tenant_id = ? ORDER BY id", (tenant_id,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM defense_audits WHERE run_id = ? AND tenant_id = ? ORDER BY id",
                (run_id, tenant_id),
            ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["decision"] = json.loads(item.pop("decision_json"))
        items.append(item)
    return items


def save_defense_policy(name: str, version: str, description: str | None, config: dict, tenant_id: str = "default"):
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO defense_policies (name, version, tenant_id, description, config_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(name, version, tenant_id) DO UPDATE SET
                description = excluded.description,
                config_json = excluded.config_json
            """,
            (name, version, tenant_id, description, json.dumps(config, ensure_ascii=False), now_iso())
        )


def get_defense_policy(name: str, version: str, tenant_id: str = "default") -> dict | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM defense_policies WHERE name = ? AND version = ? AND tenant_id = ?",
            (name, version, tenant_id),
        ).fetchone()
    if not row:
        # Fall back to 'default' tenant's policy version if custom tenant version doesn't exist
        with connection() as conn:
            row = conn.execute(
                "SELECT * FROM defense_policies WHERE name = ? AND version = ? AND tenant_id = 'default'",
                (name, version),
            ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["config"] = json.loads(item.pop("config_json") or "{}")
    return item


def list_defense_policies(tenant_id: str = "default"):
    with connection() as conn:
        # List both tenant policies and default policies
        rows = conn.execute(
            """
            SELECT * FROM defense_policies 
            WHERE tenant_id = ? OR tenant_id = 'default' 
            ORDER BY name, version, tenant_id DESC
            """,
            (tenant_id,),
        ).fetchall()
    items = []
    seen = set()
    for row in rows:
        key = (row["name"], row["version"])
        if key in seen:
            continue
        seen.add(key)
        item = dict(row)
        item["config"] = json.loads(item.pop("config_json") or "{}")
        items.append(item)
    return items


def promote_review_to_case(review_id: int, tenant_id: str = "default") -> str | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT hr.human_final_label, hr.human_attack_success, hr.reviewer_note, hr.reviewer,
                   la.case_id, la.model_response
            FROM human_review_queue hr
            JOIN layered_assessments la ON hr.assessment_id = la.id
            WHERE hr.id = ? AND hr.status = 'completed' AND la.tenant_id = ?
            """,
            (review_id, tenant_id)
        ).fetchone()
        if not row:
            return None
            
        orig_case_id = row["case_id"]
        reviewer_note = row["reviewer_note"]
        
        # Fetch original case
        orig_case = conn.execute(
            "SELECT name, prompt, system_prompt, risk_type, success_indicators_json, safe_response_indicators_json, metadata_json FROM attack_cases WHERE case_id = ?",
            (orig_case_id,)
        ).fetchone()
        
        if not orig_case:
            return None
            
        new_case_id = f"ret-{orig_case_id}-{review_id}"
        
        # Construct new attack case with provenance metadata
        metadata = json.loads(orig_case["metadata_json"] or "{}")
        metadata["source"] = "human_review"
        metadata["parent_case_id"] = orig_case_id
        metadata["reviewer_note"] = reviewer_note
        metadata["promoted_from_review_id"] = review_id
        
        conn.execute(
            """
            INSERT OR REPLACE INTO attack_cases (
                case_id, name, risk_type, prompt, system_prompt, success_indicators_json, safe_response_indicators_json, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_case_id,
                f"Promoted Case from Review #{review_id} ({orig_case['name']})",
                orig_case["risk_type"],
                orig_case["prompt"],
                orig_case["system_prompt"],
                orig_case["success_indicators_json"],
                orig_case["safe_response_indicators_json"],
                json.dumps(metadata, ensure_ascii=False),
                now_iso()
            )
        )
        return new_case_id
