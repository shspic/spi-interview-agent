from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, Text, text
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
