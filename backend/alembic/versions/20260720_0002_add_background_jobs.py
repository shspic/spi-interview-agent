"""add production background jobs

Revision ID: 20260720_0002
Revises: 20260720_0001
Create Date: 2026-07-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260720_0002"
down_revision: Union[str, Sequence[str], None] = "20260720_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_index("ux_target_jobs_active_user", table_name="target_jobs")
        op.create_index(
            "ux_target_jobs_active_user",
            "target_jobs",
            ["user_id"],
            unique=True,
            postgresql_where=sa.text("is_active IS TRUE"),
        )

    op.add_column(
        "resume_project_descriptions",
        sa.Column("source_job_id", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_resume_project_descriptions_source_job_id",
        "resume_project_descriptions",
        ["source_job_id"],
        unique=True,
    )

    op.create_table(
        "background_job_artifacts",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("artifact_type", sa.Text(), nullable=False),
        sa.Column("input_data", sa.JSON(), nullable=True),
        sa.Column("result_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_background_job_artifacts_user_id",
        "background_job_artifacts",
        ["user_id"],
    )
    op.create_index(
        "ix_background_job_artifacts_user_created",
        "background_job_artifacts",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_background_job_artifacts_expires_at",
        "background_job_artifacts",
        ["expires_at"],
    )

    op.create_table(
        "background_jobs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("progress_percent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("phase", sa.Text(), server_default="queued", nullable=False),
        sa.Column("message_code", sa.Text(), server_default="job_queued", nullable=False),
        sa.Column("idempotency_key_hash", sa.Text(), nullable=False),
        sa.Column("input_reference", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("available_at", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.Text(), nullable=True),
        sa.Column("heartbeat_at", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.Text(), nullable=True),
        sa.Column("cancel_requested_at", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), server_default="900", nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("result_reference", sa.Text(), nullable=True),
        sa.Column("quota_usage_type", sa.Text(), nullable=True),
        sa.Column("quota_event_id", sa.Integer(), nullable=True),
        sa.Column("worker_id", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "task_type IN ('knowledge_rebuild', 'agent_ask', 'job_analysis', "
            "'interview_start', 'interview_evaluation', 'improvement_generation', "
            "'resume_generation', 'data_retention_cleanup')",
            name="ck_background_jobs_task_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', "
            "'cancel_requested', 'cancelled', 'timed_out', 'retry_wait')",
            name="ck_background_jobs_status",
        ),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_background_jobs_progress",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts",
            name="ck_background_jobs_attempts",
        ),
        sa.CheckConstraint("timeout_seconds > 0", name="ck_background_jobs_timeout"),
        sa.ForeignKeyConstraint(["quota_event_id"], ["usage_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "task_type",
            "idempotency_key_hash",
            name="uq_background_jobs_user_type_idempotency",
        ),
    )
    op.create_index("ix_background_jobs_user_id", "background_jobs", ["user_id"])
    op.create_index("ix_background_jobs_task_type", "background_jobs", ["task_type"])
    op.create_index("ix_background_jobs_status", "background_jobs", ["status"])
    op.create_index("ix_background_jobs_quota_event_id", "background_jobs", ["quota_event_id"])
    op.create_index(
        "ix_background_jobs_status_available",
        "background_jobs",
        ["status", "available_at"],
    )
    op.create_index(
        "ix_background_jobs_status_lease",
        "background_jobs",
        ["status", "lease_expires_at"],
    )
    op.create_index(
        "ix_background_jobs_user_created",
        "background_jobs",
        ["user_id", "created_at"],
    )

    op.create_table(
        "background_job_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("message_code", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["background_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_background_job_events_id", "background_job_events", ["id"])
    op.create_index("ix_background_job_events_job_id", "background_job_events", ["job_id"])
    op.create_index("ix_background_job_events_user_id", "background_job_events", ["user_id"])
    op.create_index(
        "ix_background_job_events_job_created",
        "background_job_events",
        ["job_id", "created_at"],
    )
    op.create_index(
        "ix_background_job_events_user_created",
        "background_job_events",
        ["user_id", "created_at"],
    )

    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.Text(), nullable=False),
        sa.Column("database_dialect", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=False),
        sa.Column("heartbeat_at", sa.Text(), nullable=False),
        sa.Column("stopped_at", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("worker_id"),
    )
    op.create_index(
        "ix_worker_heartbeats_heartbeat_at",
        "worker_heartbeats",
        ["heartbeat_at"],
    )
    op.create_table(
        "maintenance_states",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("last_run_at", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("maintenance_states")
    op.drop_index("ix_worker_heartbeats_heartbeat_at", table_name="worker_heartbeats")
    op.drop_table("worker_heartbeats")
    op.drop_index("ix_background_job_events_user_created", table_name="background_job_events")
    op.drop_index("ix_background_job_events_job_created", table_name="background_job_events")
    op.drop_index("ix_background_job_events_user_id", table_name="background_job_events")
    op.drop_index("ix_background_job_events_job_id", table_name="background_job_events")
    op.drop_index("ix_background_job_events_id", table_name="background_job_events")
    op.drop_table("background_job_events")
    op.drop_index("ix_background_jobs_user_created", table_name="background_jobs")
    op.drop_index("ix_background_jobs_status_lease", table_name="background_jobs")
    op.drop_index("ix_background_jobs_status_available", table_name="background_jobs")
    op.drop_index("ix_background_jobs_quota_event_id", table_name="background_jobs")
    op.drop_index("ix_background_jobs_status", table_name="background_jobs")
    op.drop_index("ix_background_jobs_task_type", table_name="background_jobs")
    op.drop_index("ix_background_jobs_user_id", table_name="background_jobs")
    op.drop_table("background_jobs")
    op.drop_index("ix_background_job_artifacts_expires_at", table_name="background_job_artifacts")
    op.drop_index("ix_background_job_artifacts_user_created", table_name="background_job_artifacts")
    op.drop_index("ix_background_job_artifacts_user_id", table_name="background_job_artifacts")
    op.drop_table("background_job_artifacts")
    op.drop_index(
        "ix_resume_project_descriptions_source_job_id",
        table_name="resume_project_descriptions",
    )
    op.drop_column("resume_project_descriptions", "source_job_id")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_index("ux_target_jobs_active_user", table_name="target_jobs")
        op.create_index(
            "ux_target_jobs_active_user",
            "target_jobs",
            ["user_id"],
            unique=True,
        )
