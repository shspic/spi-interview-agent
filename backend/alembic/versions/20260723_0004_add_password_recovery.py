"""add admin-approved password recovery

Revision ID: 20260723_0004
Revises: 20260722_0003
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_0004"
down_revision: Union[str, Sequence[str], None] = "20260722_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("temporary_password_expires_at", sa.Text(), nullable=True),
    )
    op.create_table(
        "password_reset_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("request_note", sa.Text(), server_default="", nullable=False),
        sa.Column("admin_note", sa.Text(), server_default="", nullable=False),
        sa.Column("requested_at", sa.Text(), nullable=False),
        sa.Column("processed_at", sa.Text(), nullable=True),
        sa.Column("processed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name="ck_password_reset_requests_status",
        ),
        sa.ForeignKeyConstraint(["processed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_password_reset_requests_id",
        "password_reset_requests",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_password_reset_requests_user_id",
        "password_reset_requests",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_password_reset_requests_requested_at",
        "password_reset_requests",
        ["requested_at"],
        unique=False,
    )
    op.create_index(
        "ix_password_reset_requests_processed_by_user_id",
        "password_reset_requests",
        ["processed_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_password_reset_requests_status_requested",
        "password_reset_requests",
        ["status", "requested_at"],
        unique=False,
    )
    op.create_index(
        "ix_password_reset_requests_processed_by",
        "password_reset_requests",
        ["processed_by_user_id", "processed_at"],
        unique=False,
    )
    op.create_index(
        "ux_password_reset_requests_pending_user",
        "password_reset_requests",
        ["user_id"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_password_reset_requests_pending_user",
        table_name="password_reset_requests",
    )
    op.drop_index(
        "ix_password_reset_requests_processed_by",
        table_name="password_reset_requests",
    )
    op.drop_index(
        "ix_password_reset_requests_status_requested",
        table_name="password_reset_requests",
    )
    op.drop_index(
        "ix_password_reset_requests_processed_by_user_id",
        table_name="password_reset_requests",
    )
    op.drop_index(
        "ix_password_reset_requests_requested_at",
        table_name="password_reset_requests",
    )
    op.drop_index(
        "ix_password_reset_requests_user_id",
        table_name="password_reset_requests",
    )
    op.drop_index(
        "ix_password_reset_requests_id",
        table_name="password_reset_requests",
    )
    op.drop_table("password_reset_requests")
    op.drop_column("users", "temporary_password_expires_at")
    op.drop_column("users", "must_change_password")
