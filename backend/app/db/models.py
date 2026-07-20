from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Float,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from app.db.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(Text, unique=True, index=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    is_admin = Column(Boolean, nullable=False, default=False)
    created_at = Column(Text, nullable=False)
    last_login_at = Column(Text, nullable=True)
    profile = relationship(
        "UserProfile",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    target_jobs = relationship(
        "TargetJob",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    auth_sessions = relationship(
        "AuthSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    display_name = Column(Text, nullable=False, default="")
    target_direction = Column(Text, nullable=False, default="")
    self_introduction = Column(Text, nullable=False, default="")
    technical_skills = Column(Text, nullable=False, default="[]")
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)
    user = relationship("User", back_populates="profile")


class TargetJob(Base):
    __tablename__ = "target_jobs"
    __table_args__ = (
        Index(
            "ux_target_jobs_active_user",
            "user_id",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active IS TRUE"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_title = Column(Text, nullable=False)
    company_name = Column(Text, nullable=False, default="")
    jd_text = Column(Text, nullable=False)
    notes = Column(Text, nullable=False, default="")
    is_active = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)
    user = relationship("User", back_populates="target_jobs")


class FileRecord(Base):
    __tablename__ = "files"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="ck_files_size_bytes"),
        Index(
            "ux_files_user_upload_idempotency",
            "user_id",
            "upload_idempotency_key_hash",
            unique=True,
            sqlite_where=text("upload_idempotency_key_hash IS NOT NULL"),
            postgresql_where=text("upload_idempotency_key_hash IS NOT NULL"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    file_id = Column(Text, unique=True, index=True, nullable=False)
    filename = Column(Text, nullable=False)
    file_type = Column(Text, nullable=False)
    file_path = Column(Text, nullable=False)
    size_bytes = Column(Integer, nullable=False, default=0, server_default="0")
    content_sha256 = Column(Text, nullable=True)
    upload_idempotency_key_hash = Column(Text, nullable=True)
    category = Column(Text, nullable=False, default="other", server_default="other")
    status = Column(Text, nullable=False, default="uploaded")
    error_message = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)


class HistoryRecord(Base):
    __tablename__ = "history_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    record_id = Column(Text, unique=True, index=True, nullable=False)
    mode = Column(Text, nullable=False)
    user_input = Column(Text, nullable=False)
    ai_output = Column(Text, nullable=False)
    sources = Column(Text, nullable=True)
    used_web_search = Column(Integer, nullable=False, default=0)
    web_sources = Column(Text, nullable=True)
    route_reason = Column(Text, default="")
    execution_steps = Column(Text, default="")
    created_at = Column(Text, nullable=False)


class InterviewRecord(Base):
    __tablename__ = "interview_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    session_id = Column(Text, index=True, nullable=False)
    interview_type = Column(Text, nullable=False)
    job_description = Column(Text, nullable=True)
    question_index = Column(Integer, nullable=False)
    question = Column(Text, nullable=False)
    user_answer = Column(Text, nullable=False)
    score_total = Column(Integer, nullable=False)
    content_relevance = Column(Integer, nullable=False)
    personal_match = Column(Integer, nullable=False)
    technical_accuracy = Column(Integer, nullable=False)
    structure_score = Column(Integer, nullable=False)
    risk_control = Column(Integer, nullable=False)
    main_problems = Column(Text, nullable=True)
    suggestions = Column(Text, nullable=True)
    reference_answer = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)


class InterviewSession(Base):
    __tablename__ = "interview_sessions"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('quick', 'standard', 'deep_dive')",
            name="ck_interview_sessions_mode",
        ),
        CheckConstraint(
            "status IN ('draft', 'in_progress', 'completed', 'cancelled')",
            name="ck_interview_sessions_status",
        ),
        CheckConstraint(
            "planned_main_questions > 0",
            name="ck_interview_sessions_planned_questions",
        ),
        CheckConstraint(
            "current_main_question >= 0",
            name="ck_interview_sessions_current_question",
        ),
        CheckConstraint(
            "overall_score IS NULL OR (overall_score >= 0 AND overall_score <= 100)",
            name="ck_interview_sessions_overall_score",
        ),
        CheckConstraint(
            "improvement_status IN ('pending', 'generating', 'completed', 'failed')",
            name="ck_interview_sessions_improvement_status",
        ),
        Index("ix_interview_sessions_user_status", "user_id", "status"),
        Index("ix_interview_sessions_user_mode", "user_id", "mode"),
        Index("ix_interview_sessions_user_created", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_job_id = Column(
        Integer,
        ForeignKey("target_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    previous_session_id = Column(
        Integer,
        ForeignKey("interview_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title = Column(Text, nullable=False)
    mode = Column(Text, nullable=False, index=True)
    status = Column(Text, nullable=False, default="draft", index=True)
    planned_main_questions = Column(Integer, nullable=False)
    current_main_question = Column(Integer, nullable=False, default=0)
    selected_project_file_ids = Column(JSON, nullable=False, default=list)
    interview_plan = Column(JSON, nullable=True)
    agent_execution_summary = Column(JSON, nullable=True)
    overall_score = Column(Float, nullable=True)
    dimension_scores = Column(JSON, nullable=True)
    summary = Column(Text, nullable=True)
    improvement_status = Column(
        Text,
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
    )
    improvement_summary = Column(Text, nullable=True)
    next_round_strategy = Column(Text, nullable=True)
    improvement_generated_at = Column(Text, nullable=True)
    improvement_error = Column(Text, nullable=True)
    started_at = Column(Text, nullable=True)
    completed_at = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False, index=True)
    updated_at = Column(Text, nullable=False)

    previous_session = relationship(
        "InterviewSession",
        remote_side=[id],
        foreign_keys=[previous_session_id],
    )
    turns = relationship(
        "InterviewTurn",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="InterviewTurn.sequence_number",
    )
    improvement_tasks = relationship(
        "ImprovementTask",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ImprovementTask.id",
    )
    agent_runs = relationship(
        "AgentRun",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="AgentRun.id",
    )


class InterviewTurn(Base):
    __tablename__ = "interview_turns"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "sequence_number",
            name="uq_interview_turns_session_sequence",
        ),
        UniqueConstraint(
            "session_id",
            "main_question_number",
            "follow_up_number",
            name="uq_interview_turns_question_follow_up",
        ),
        CheckConstraint(
            "main_question_number > 0",
            name="ck_interview_turns_main_question",
        ),
        CheckConstraint(
            "follow_up_number >= 0 AND follow_up_number <= 2",
            name="ck_interview_turns_follow_up_number",
        ),
        CheckConstraint(
            "question_type IN ('main', 'follow_up')",
            name="ck_interview_turns_question_type",
        ),
        CheckConstraint(
            "technical_accuracy_score IS NULL OR "
            "(technical_accuracy_score >= 0 AND technical_accuracy_score <= 100)",
            name="ck_interview_turns_technical_accuracy_score",
        ),
        CheckConstraint(
            "evidence_consistency_score IS NULL OR "
            "(evidence_consistency_score >= 0 AND evidence_consistency_score <= 100)",
            name="ck_interview_turns_evidence_consistency_score",
        ),
        CheckConstraint(
            "answer_depth_score IS NULL OR "
            "(answer_depth_score >= 0 AND answer_depth_score <= 100)",
            name="ck_interview_turns_answer_depth_score",
        ),
        CheckConstraint(
            "expression_structure_score IS NULL OR "
            "(expression_structure_score >= 0 AND expression_structure_score <= 100)",
            name="ck_interview_turns_expression_structure_score",
        ),
        CheckConstraint(
            "job_match_score IS NULL OR "
            "(job_match_score >= 0 AND job_match_score <= 100)",
            name="ck_interview_turns_job_match_score",
        ),
        CheckConstraint(
            "total_score IS NULL OR (total_score >= 0 AND total_score <= 100)",
            name="ck_interview_turns_total_score",
        ),
        Index("ix_interview_turns_session_main", "session_id", "main_question_number"),
        Index("ix_interview_turns_user_created", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(
        Integer,
        ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_number = Column(Integer, nullable=False)
    main_question_number = Column(Integer, nullable=False)
    follow_up_number = Column(Integer, nullable=False, default=0)
    parent_turn_id = Column(
        Integer,
        ForeignKey("interview_turns.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    question = Column(Text, nullable=False)
    question_type = Column(Text, nullable=False)
    user_answer = Column(Text, nullable=True)
    technical_accuracy_score = Column(Integer, nullable=True)
    evidence_consistency_score = Column(Integer, nullable=True)
    answer_depth_score = Column(Integer, nullable=True)
    expression_structure_score = Column(Integer, nullable=True)
    job_match_score = Column(Integer, nullable=True)
    total_score = Column(Integer, nullable=True)
    evaluation_summary = Column(Text, nullable=True)
    problems = Column(JSON, nullable=True)
    optimized_answer = Column(Text, nullable=True)
    modification_reason = Column(Text, nullable=True)
    has_evidence_conflict = Column(Boolean, nullable=False, default=False)
    evidence_conflicts = Column(JSON, nullable=True)
    evidence_sources = Column(JSON, nullable=True)
    evaluation_source_ids = Column(JSON, nullable=True)
    unsupported_claims = Column(JSON, nullable=True)
    strengths = Column(JSON, nullable=True)
    answered_at = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)

    session = relationship("InterviewSession", back_populates="turns")
    parent_turn = relationship(
        "InterviewTurn",
        remote_side=[id],
        foreign_keys=[parent_turn_id],
    )
    improvement_tasks = relationship(
        "ImprovementTask",
        back_populates="turn",
    )


class ImprovementTask(Base):
    __tablename__ = "improvement_tasks"
    __table_args__ = (
        CheckConstraint(
            "category IN ('technical', 'project_evidence', 'answer_depth', "
            "'expression', 'job_match', 'resume')",
            name="ck_improvement_tasks_category",
        ),
        CheckConstraint(
            "priority IN ('low', 'medium', 'high')",
            name="ck_improvement_tasks_priority",
        ),
        CheckConstraint(
            "status IN ('pending', 'completed')",
            name="ck_improvement_tasks_status",
        ),
        Index("ix_improvement_tasks_user_status", "user_id", "status"),
        Index("ix_improvement_tasks_user_category", "user_id", "category"),
        Index("ix_improvement_tasks_session_status", "session_id", "status"),
        Index("ix_improvement_tasks_user_created", "user_id", "created_at"),
        Index(
            "ux_improvement_tasks_session_dedupe",
            "session_id",
            "dedupe_key",
            unique=True,
            sqlite_where=text("dedupe_key IS NOT NULL"),
            postgresql_where=text("dedupe_key IS NOT NULL"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id = Column(
        Integer,
        ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    turn_id = Column(
        Integer,
        ForeignKey("interview_turns.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    completion_criteria = Column(Text, nullable=False, default="", server_default="")
    category = Column(Text, nullable=False, index=True)
    priority = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="pending", index=True)
    dedupe_key = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False, index=True)
    completed_at = Column(Text, nullable=True)
    updated_at = Column(Text, nullable=False)

    session = relationship("InterviewSession", back_populates="improvement_tasks")
    turn = relationship("InterviewTurn", back_populates="improvement_tasks")


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "agent_name IN ('supervisor', 'evidence', 'evaluation', "
            "'interviewer', 'improvement', 'resume')",
            name="ck_agent_runs_agent_name",
        ),
        CheckConstraint(
            "status IN ('success', 'error')",
            name="ck_agent_runs_status",
        ),
        CheckConstraint(
            "latency_ms >= 0",
            name="ck_agent_runs_latency",
        ),
        Index("ix_agent_runs_session_created", "session_id", "created_at"),
        Index("ix_agent_runs_user_created", "user_id", "created_at"),
        Index("ix_agent_runs_run_id", "run_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Text, nullable=False)
    request_id = Column(Text, nullable=True, index=True)
    session_id = Column(
        Integer,
        ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_name = Column(Text, nullable=False, index=True)
    prompt_version = Column(Text, nullable=False)
    status = Column(Text, nullable=False, index=True)
    latency_ms = Column(Integer, nullable=False)
    error = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False, index=True)

    session = relationship("InterviewSession", back_populates="agent_runs")


class BackgroundJobArtifact(Base):
    __tablename__ = "background_job_artifacts"
    __table_args__ = (
        Index("ix_background_job_artifacts_user_created", "user_id", "created_at"),
        Index("ix_background_job_artifacts_expires_at", "expires_at"),
    )

    id = Column(Text, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artifact_type = Column(Text, nullable=False)
    input_data = Column(JSON, nullable=True)
    result_data = Column(JSON, nullable=True)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)
    expires_at = Column(Text, nullable=False)


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "task_type",
            "idempotency_key_hash",
            name="uq_background_jobs_user_type_idempotency",
        ),
        CheckConstraint(
            "task_type IN ('knowledge_rebuild', 'agent_ask', 'job_analysis', "
            "'interview_start', 'interview_evaluation', "
            "'improvement_generation', 'resume_generation', "
            "'data_retention_cleanup')",
            name="ck_background_jobs_task_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', "
            "'cancel_requested', 'cancelled', 'timed_out', 'retry_wait')",
            name="ck_background_jobs_status",
        ),
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_background_jobs_progress",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0 "
            "AND attempt_count <= max_attempts",
            name="ck_background_jobs_attempts",
        ),
        CheckConstraint("timeout_seconds > 0", name="ck_background_jobs_timeout"),
        Index("ix_background_jobs_status_available", "status", "available_at"),
        Index("ix_background_jobs_status_lease", "status", "lease_expires_at"),
        Index("ix_background_jobs_user_created", "user_id", "created_at"),
    )

    id = Column(Text, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_type = Column(Text, nullable=False, index=True)
    status = Column(Text, nullable=False, default="queued", index=True)
    progress_percent = Column(Integer, nullable=False, default=0)
    phase = Column(Text, nullable=False, default="queued")
    message_code = Column(Text, nullable=False, default="job_queued")
    idempotency_key_hash = Column(Text, nullable=False)
    input_reference = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)
    available_at = Column(Text, nullable=False)
    started_at = Column(Text, nullable=True)
    completed_at = Column(Text, nullable=True)
    heartbeat_at = Column(Text, nullable=True)
    lease_expires_at = Column(Text, nullable=True)
    cancel_requested_at = Column(Text, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    timeout_seconds = Column(Integer, nullable=False, default=900)
    error_code = Column(Text, nullable=True)
    error_summary = Column(Text, nullable=True)
    result_reference = Column(Text, nullable=True)
    quota_usage_type = Column(Text, nullable=True)
    quota_event_id = Column(
        Integer,
        ForeignKey("usage_events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    worker_id = Column(Text, nullable=True)

    events = relationship(
        "BackgroundJobEvent",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="BackgroundJobEvent.id",
    )


class BackgroundJobEvent(Base):
    __tablename__ = "background_job_events"
    __table_args__ = (
        Index("ix_background_job_events_job_created", "job_id", "created_at"),
        Index("ix_background_job_events_user_created", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(
        Text,
        ForeignKey("background_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status = Column(Text, nullable=True)
    to_status = Column(Text, nullable=False)
    phase = Column(Text, nullable=False)
    message_code = Column(Text, nullable=False)
    attempt_count = Column(Integer, nullable=False)
    created_at = Column(Text, nullable=False)

    job = relationship("BackgroundJob", back_populates="events")


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    __table_args__ = (Index("ix_worker_heartbeats_heartbeat_at", "heartbeat_at"),)

    worker_id = Column(Text, primary_key=True)
    database_dialect = Column(Text, nullable=False)
    started_at = Column(Text, nullable=False)
    heartbeat_at = Column(Text, nullable=False)
    stopped_at = Column(Text, nullable=True)


class MaintenanceState(Base):
    __tablename__ = "maintenance_states"

    key = Column(Text, primary_key=True)
    last_run_at = Column(Text, nullable=True)
    updated_at = Column(Text, nullable=False)


class ResumeProjectDescription(Base):
    __tablename__ = "resume_project_descriptions"
    __table_args__ = (
        Index(
            "ix_resume_project_descriptions_user_created",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_resume_project_descriptions_user_session",
            "user_id",
            "session_id",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    source_job_id = Column(Text, nullable=True, unique=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id = Column(
        Integer,
        ForeignKey("interview_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    target_job_id = Column(
        Integer,
        ForeignKey("target_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_file_ids = Column(JSON, nullable=False, default=list)
    project_name = Column(Text, nullable=False)
    one_line_summary = Column(Text, nullable=False)
    concise_bullets = Column(JSON, nullable=False, default=list)
    detailed_description = Column(Text, nullable=False)
    technical_stack = Column(JSON, nullable=False, default=list)
    responsibilities = Column(JSON, nullable=False, default=list)
    challenges = Column(JSON, nullable=False, default=list)
    solutions = Column(JSON, nullable=False, default=list)
    outcomes = Column(JSON, nullable=False, default=list)
    interview_talking_points = Column(JSON, nullable=False, default=list)
    warnings = Column(JSON, nullable=False, default=list)
    evidence_source_ids = Column(JSON, nullable=False, default=list)
    prompt_version = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False, index=True)
    updated_at = Column(Text, nullable=False)


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "usage_type",
            "idempotency_key",
            name="uq_usage_events_user_type_key",
        ),
        CheckConstraint(
            "usage_type IN ('chat', 'job_analysis', 'interview_evaluation', "
            "'multi_agent_task', 'resume_generation', 'llm_call', "
            "'embedding_call', 'web_search')",
            name="ck_usage_events_type",
        ),
        CheckConstraint(
            "status IN ('reserved', 'succeeded', 'released', 'failed')",
            name="ck_usage_events_status",
        ),
        CheckConstraint("amount > 0", name="ck_usage_events_amount"),
        Index(
            "ix_usage_events_user_date_type_status",
            "user_id",
            "usage_date",
            "usage_type",
            "status",
        ),
        Index("ix_usage_events_date_type", "usage_date", "usage_type"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    usage_type = Column(Text, nullable=False, index=True)
    usage_date = Column(Text, nullable=False, index=True)
    idempotency_key = Column(Text, nullable=False)
    status = Column(Text, nullable=False, index=True)
    amount = Column(Integer, nullable=False, default=1)
    related_resource_type = Column(Text, nullable=True)
    related_resource_id = Column(Text, nullable=True)
    error_type = Column(Text, nullable=True)
    reserved_at = Column(Text, nullable=False)
    completed_at = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_user_revoked", "user_id", "revoked_at"),
        Index("ix_auth_sessions_expires_at", "expires_at"),
        Index("ix_auth_sessions_revoked_at", "revoked_at"),
    )

    id = Column(Text, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    refresh_token_hash = Column(Text, nullable=False)
    csrf_token_hash = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)
    last_seen_at = Column(Text, nullable=False)
    expires_at = Column(Text, nullable=False)
    revoked_at = Column(Text, nullable=True)
    revoke_reason = Column(Text, nullable=True)
    token_version = Column(Integer, nullable=False, default=1, server_default="1")
    user_agent_hash = Column(Text, nullable=True)
    user = relationship("User", back_populates="auth_sessions")


class AuthSecurityEvent(Base):
    __tablename__ = "auth_security_events"
    __table_args__ = (
        Index("ix_auth_security_events_user_created", "user_id", "created_at"),
        Index("ix_auth_security_events_type_created", "event_type", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type = Column(Text, nullable=False, index=True)
    status = Column(Text, nullable=False)
    session_ref = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False, index=True)


class RateLimitBucket(Base):
    __tablename__ = "rate_limit_buckets"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "subject_type",
            "subject_hash",
            "window_started_at",
            name="uq_rate_limit_bucket_subject_window",
        ),
        CheckConstraint("attempts > 0", name="ck_rate_limit_bucket_attempts"),
        Index("ix_rate_limit_buckets_expires_at", "expires_at"),
        Index(
            "ix_rate_limit_buckets_subject",
            "scope",
            "subject_type",
            "subject_hash",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    scope = Column(Text, nullable=False)
    subject_type = Column(Text, nullable=False)
    subject_hash = Column(Text, nullable=False)
    window_started_at = Column(Integer, nullable=False)
    expires_at = Column(Integer, nullable=False)
    attempts = Column(Integer, nullable=False, default=1)
    updated_at = Column(Text, nullable=False)


class UploadReservation(Base):
    __tablename__ = "upload_reservations"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_upload_reservation_size"),
        Index(
            "ix_upload_reservations_user_expires",
            "user_id",
            "expires_at",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    reservation_id = Column(Text, unique=True, nullable=False, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    size_bytes = Column(Integer, nullable=False)
    expires_at = Column(Integer, nullable=False)
    created_at = Column(Text, nullable=False)


class DailyUsageCounter(Base):
    __tablename__ = "daily_usage_counters"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "usage_type",
            "usage_date",
            name="uq_daily_usage_counters_user_type_date",
        ),
        CheckConstraint("used >= 0", name="ck_daily_usage_counters_used"),
        CheckConstraint(
            "reserved >= 0",
            name="ck_daily_usage_counters_reserved",
        ),
        Index(
            "ix_daily_usage_counters_date_type",
            "usage_date",
            "usage_type",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    usage_type = Column(Text, nullable=False, index=True)
    usage_date = Column(Text, nullable=False, index=True)
    used = Column(Integer, nullable=False, default=0)
    reserved = Column(Integer, nullable=False, default=0)
    updated_at = Column(Text, nullable=False)


class RegistrationSetting(Base):
    __tablename__ = "registration_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_registration_settings_singleton"),
    )

    id = Column(Integer, primary_key=True)
    invite_code_hash = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)
    updated_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('success', 'failed')",
            name="ck_admin_audit_logs_status",
        ),
        Index("ix_admin_audit_logs_admin_created", "admin_user_id", "created_at"),
        Index("ix_admin_audit_logs_target_created", "target_user_id", "created_at"),
        Index("ix_admin_audit_logs_action_created", "action", "created_at"),
        Index("ix_admin_audit_logs_status_created", "status", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    admin_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action = Column(Text, nullable=False, index=True)
    target_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resource_type = Column(Text, nullable=False)
    resource_id = Column(Text, nullable=True)
    status = Column(Text, nullable=False, index=True)
    detail_summary = Column(Text, nullable=False, default="")
    created_at = Column(Text, nullable=False, index=True)


class UserDataDeletionLog(Base):
    __tablename__ = "user_data_deletion_logs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('success', 'failed')",
            name="ck_user_data_deletion_logs_status",
        ),
        Index(
            "ix_user_data_deletion_logs_user_created",
            "user_id",
            "created_at",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(Text, nullable=False, index=True)
    deleted_counts = Column(JSON, nullable=False, default=dict)
    failure_count = Column(Integer, nullable=False, default=0)
    detail_summary = Column(Text, nullable=False, default="")
    created_at = Column(Text, nullable=False, index=True)
