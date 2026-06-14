"""stage five production control plane"""

from alembic import op
import sqlalchemy as sa


revision = "20260613_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "async_evaluation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("defense_policy", sa.String(200), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("run_metadata_json", sa.JSON(), nullable=False),
        sa.Column("total_cases", sa.Integer(), nullable=False),
        sa.Column("completed_cases", sa.Integer(), nullable=False),
        sa.Column("success_cases", sa.Integer(), nullable=False),
        sa.Column("failed_cases", sa.Integer(), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("error_summary", sa.Text()),
        sa.Column("celery_task_id", sa.String(100)),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_async_evaluation_runs_status", "async_evaluation_runs", ["status"])
    op.create_table(
        "async_case_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("async_evaluation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_id", sa.String(100), nullable=False),
        sa.Column("case_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("result_json", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("run_id", "case_id", name="uq_async_run_case"),
    )
    op.create_index("ix_async_case_results_run_id", "async_case_results", ["run_id"])
    op.create_table(
        "operation_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(100), nullable=False),
        sa.Column("request_id", sa.String(100), nullable=False),
        sa.Column("run_id", sa.String(36)),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_operation_audit_logs_action", "operation_audit_logs", ["action"])
    op.create_index("ix_operation_audit_logs_run_id", "operation_audit_logs", ["run_id"])


def downgrade():
    op.drop_table("operation_audit_logs")
    op.drop_table("async_case_results")
    op.drop_table("async_evaluation_runs")
