from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import FileRecord, InterviewSession, InterviewTurn, TargetJob

MODE_MAIN_QUESTION_COUNTS = {
    "quick": 3,
    "standard": 5,
    "deep_dive": 1,
}


class InterviewTrainingServiceError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_owned_session(
    db: Session,
    user_id: int,
    session_id: int,
) -> InterviewSession:
    interview_session = (
        db.query(InterviewSession)
        .filter(
            InterviewSession.id == session_id,
            InterviewSession.user_id == user_id,
        )
        .first()
    )
    if interview_session is None:
        raise InterviewTrainingServiceError(404, "面试会话不存在")
    return interview_session


def validate_target_job(
    db: Session,
    user_id: int,
    target_job_id: int | None,
) -> None:
    if target_job_id is None:
        return
    exists = (
        db.query(TargetJob.id)
        .filter(
            TargetJob.id == target_job_id,
            TargetJob.user_id == user_id,
        )
        .first()
    )
    if exists is None:
        raise InterviewTrainingServiceError(404, "目标岗位不存在")


def validate_project_files(
    db: Session,
    user_id: int,
    file_ids: list[str],
    mode: str,
) -> list[str]:
    normalized_ids = list(dict.fromkeys(file_ids))
    if mode == "deep_dive" and not normalized_ids:
        raise InterviewTrainingServiceError(
            400,
            "专项深挖至少需要选择一个项目文件",
        )
    if not normalized_ids:
        return []

    valid_ids = {
        item.file_id
        for item in db.query(FileRecord.file_id)
        .filter(
            FileRecord.file_id.in_(normalized_ids),
            FileRecord.user_id == user_id,
            FileRecord.category == "project",
        )
        .all()
    }
    if valid_ids != set(normalized_ids):
        raise InterviewTrainingServiceError(404, "项目文件不存在")
    return normalized_ids


def validate_previous_session(
    db: Session,
    user_id: int,
    previous_session_id: int | None,
    current_session_id: int | None = None,
) -> None:
    if previous_session_id is None:
        return
    if previous_session_id == current_session_id:
        raise InterviewTrainingServiceError(400, "上一轮会话不能引用自身")

    previous_session = (
        db.query(InterviewSession)
        .filter(
            InterviewSession.id == previous_session_id,
            InterviewSession.user_id == user_id,
            InterviewSession.status == "completed",
        )
        .first()
    )
    if previous_session is None:
        raise InterviewTrainingServiceError(
            404,
            "上一轮会话不存在或尚未完成",
        )


def create_interview_session(
    db: Session,
    user_id: int,
    *,
    title: str,
    mode: str,
    target_job_id: int | None,
    selected_project_file_ids: list[str],
    previous_session_id: int | None,
) -> InterviewSession:
    validate_target_job(db, user_id, target_job_id)
    project_file_ids = validate_project_files(
        db,
        user_id,
        selected_project_file_ids,
        mode,
    )
    validate_previous_session(db, user_id, previous_session_id)
    now = now_iso()
    interview_session = InterviewSession(
        user_id=user_id,
        target_job_id=target_job_id,
        previous_session_id=previous_session_id,
        title=title.strip(),
        mode=mode,
        status="draft",
        planned_main_questions=MODE_MAIN_QUESTION_COUNTS[mode],
        current_main_question=0,
        selected_project_file_ids=project_file_ids,
        created_at=now,
        updated_at=now,
    )
    db.add(interview_session)
    db.commit()
    db.refresh(interview_session)
    return interview_session


def list_interview_sessions(
    db: Session,
    user_id: int,
    *,
    status: str | None = None,
    mode: str | None = None,
) -> list[InterviewSession]:
    query = db.query(InterviewSession).filter(InterviewSession.user_id == user_id)
    if status is not None:
        query = query.filter(InterviewSession.status == status)
    if mode is not None:
        query = query.filter(InterviewSession.mode == mode)
    return query.order_by(InterviewSession.id.desc()).all()


def update_interview_session(
    db: Session,
    user_id: int,
    session_id: int,
    changes: dict,
) -> InterviewSession:
    interview_session = get_owned_session(db, user_id, session_id)
    if not changes:
        raise InterviewTrainingServiceError(400, "至少需要提交一个可修改字段")

    if "target_job_id" in changes:
        validate_target_job(db, user_id, changes["target_job_id"])
        interview_session.target_job_id = changes["target_job_id"]
    if "selected_project_file_ids" in changes:
        file_ids = changes["selected_project_file_ids"]
        if file_ids is None:
            file_ids = []
        interview_session.selected_project_file_ids = validate_project_files(
            db,
            user_id,
            file_ids,
            interview_session.mode,
        )
    if "previous_session_id" in changes:
        validate_previous_session(
            db,
            user_id,
            changes["previous_session_id"],
            current_session_id=session_id,
        )
        interview_session.previous_session_id = changes["previous_session_id"]
    if "title" in changes:
        if changes["title"] is None:
            raise InterviewTrainingServiceError(422, "面试标题不能为空")
        interview_session.title = changes["title"].strip()

    interview_session.updated_at = now_iso()
    db.commit()
    db.refresh(interview_session)
    return interview_session


def start_interview_session(
    db: Session,
    user_id: int,
    session_id: int,
) -> InterviewSession:
    interview_session = get_owned_session(db, user_id, session_id)
    if interview_session.status != "draft":
        raise InterviewTrainingServiceError(409, "只有草稿会话可以开始")
    now = now_iso()
    interview_session.status = "in_progress"
    interview_session.started_at = now
    interview_session.updated_at = now
    db.commit()
    db.refresh(interview_session)
    return interview_session


def cancel_interview_session(
    db: Session,
    user_id: int,
    session_id: int,
) -> InterviewSession:
    interview_session = get_owned_session(db, user_id, session_id)
    if interview_session.status == "completed":
        raise InterviewTrainingServiceError(409, "已完成的会话不能取消")
    if interview_session.status != "cancelled":
        interview_session.status = "cancelled"
        interview_session.updated_at = now_iso()
        db.commit()
        db.refresh(interview_session)
    return interview_session


def delete_interview_session(
    db: Session,
    user_id: int,
    session_id: int,
) -> None:
    interview_session = get_owned_session(db, user_id, session_id)
    db.delete(interview_session)
    db.commit()


def create_interview_turn(
    db: Session,
    user_id: int,
    session_id: int,
    *,
    question: str,
    main_question_number: int | None = None,
    parent_turn_id: int | None = None,
) -> InterviewTurn:
    interview_session = get_owned_session(db, user_id, session_id)
    normalized_question = question.strip()
    if not normalized_question:
        raise InterviewTrainingServiceError(400, "题目内容不能为空")

    follow_up_number = 0
    question_type = "main"
    if parent_turn_id is None:
        if main_question_number is None or main_question_number <= 0:
            raise InterviewTrainingServiceError(400, "主问题序号必须大于 0")
        if main_question_number > interview_session.planned_main_questions:
            raise InterviewTrainingServiceError(400, "主问题序号超过会话计划")
        existing_main_question = (
            db.query(InterviewTurn.id)
            .filter(
                InterviewTurn.session_id == session_id,
                InterviewTurn.main_question_number == main_question_number,
                InterviewTurn.follow_up_number == 0,
            )
            .first()
        )
        if existing_main_question is not None:
            raise InterviewTrainingServiceError(409, "该主问题序号已存在")
    else:
        parent_turn = (
            db.query(InterviewTurn)
            .filter(
                InterviewTurn.id == parent_turn_id,
                InterviewTurn.user_id == user_id,
            )
            .first()
        )
        if parent_turn is None or parent_turn.session_id != session_id:
            raise InterviewTrainingServiceError(400, "父题目必须属于同一面试会话")
        main_question_number = parent_turn.main_question_number
        follow_up_count = (
            db.query(InterviewTurn)
            .filter(
                InterviewTurn.session_id == session_id,
                InterviewTurn.main_question_number == main_question_number,
                InterviewTurn.follow_up_number > 0,
            )
            .count()
        )
        if follow_up_count >= 2:
            raise InterviewTrainingServiceError(409, "每个主问题最多只能追问两次")
        follow_up_number = follow_up_count + 1
        question_type = "follow_up"

    max_sequence = (
        db.query(func.max(InterviewTurn.sequence_number))
        .filter(InterviewTurn.session_id == session_id)
        .scalar()
    )
    now = now_iso()
    turn = InterviewTurn(
        session_id=session_id,
        user_id=user_id,
        sequence_number=(max_sequence or 0) + 1,
        main_question_number=main_question_number,
        follow_up_number=follow_up_number,
        parent_turn_id=parent_turn_id,
        question=normalized_question,
        question_type=question_type,
        has_evidence_conflict=False,
        created_at=now,
        updated_at=now,
    )
    db.add(turn)
    db.commit()
    db.refresh(turn)
    return turn
