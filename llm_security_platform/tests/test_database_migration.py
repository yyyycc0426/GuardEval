import sqlite3
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from llm_security_platform.app import db


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path("llm_security_platform/.test_artifacts") / str(uuid4())
        self.temp_dir.mkdir(parents=True)
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = self.temp_dir / "legacy.db"

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_adds_stage_two_columns_to_legacy_results_table(self):
        with sqlite3.connect(db.DATABASE_PATH) as connection:
            connection.execute(
                """
                CREATE TABLE evaluation_results (
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
                    error TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
        db.init_db()
        with sqlite3.connect(db.DATABASE_PATH) as connection:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(evaluation_results)").fetchall()
            }
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        self.assertTrue(
            {"token_usage_json", "estimated_cost", "model_call_json"}.issubset(columns)
        )
        self.assertTrue(
            {"evaluation_results", "layered_assessments", "human_review_queue", "defense_audits"}.issubset(tables)
        )


if __name__ == "__main__":
    unittest.main()
