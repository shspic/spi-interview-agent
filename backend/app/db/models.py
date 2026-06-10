from sqlalchemy import Column, Integer, Text

from app.db.database import Base


class FileRecord(Base):
    __tablename__ = "files"

    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(Text, unique=True, index=True, nullable=False)
    filename = Column(Text, nullable=False)
    file_type = Column(Text, nullable=False)
    file_path = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="uploaded")
    error_message = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)


class HistoryRecord(Base):
    __tablename__ = "history_records"

    id = Column(Integer, primary_key=True, index=True)
    record_id = Column(Text, unique=True, index=True, nullable=False)
    mode = Column(Text, nullable=False)
    user_input = Column(Text, nullable=False)
    ai_output = Column(Text, nullable=False)
    sources = Column(Text, nullable=True)
    used_web_search = Column(Integer, nullable=False, default=0)
    web_sources = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)


class InterviewRecord(Base):
    __tablename__ = "interview_records"

    id = Column(Integer, primary_key=True, index=True)
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