from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import ResumeProjectDescription, User
from app.schemas.resume_project_description import (
    ResumeProjectDescriptionGenerateRequest,
    ResumeProjectDescriptionListResponse,
    ResumeProjectDescriptionResponse,
)
from app.services.resume_generation_service import (
    ResumeGenerationError,
    delete_resume_project_description,
    generate_resume_project_description,
    get_owned_resume_project_description,
    list_resume_project_descriptions,
)

router = APIRouter()


def description_to_response(
    description: ResumeProjectDescription,
) -> ResumeProjectDescriptionResponse:
    return ResumeProjectDescriptionResponse(
        id=description.id,
        session_id=description.session_id,
        target_job_id=description.target_job_id,
        project_file_ids=description.project_file_ids or [],
        project_name=description.project_name,
        one_line_summary=description.one_line_summary,
        concise_bullets=description.concise_bullets or [],
        detailed_description=description.detailed_description,
        technical_stack=description.technical_stack or [],
        responsibilities=description.responsibilities or [],
        challenges=description.challenges or [],
        solutions=description.solutions or [],
        outcomes=description.outcomes or [],
        interview_talking_points=description.interview_talking_points or [],
        warnings=description.warnings or [],
        evidence_source_ids=description.evidence_source_ids or [],
        prompt_version=description.prompt_version,
        created_at=description.created_at,
        updated_at=description.updated_at,
    )


@router.post(
    "/resume-project-descriptions/generate",
    response_model=ResumeProjectDescriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_description(
    request: ResumeProjectDescriptionGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        description = generate_resume_project_description(
            db,
            current_user.id,
            session_id=request.session_id,
            target_job_id=request.target_job_id,
            project_file_ids=request.project_file_ids,
        )
    except ResumeGenerationError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
    return description_to_response(description)


@router.get(
    "/resume-project-descriptions",
    response_model=ResumeProjectDescriptionListResponse,
)
def list_descriptions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    descriptions = list_resume_project_descriptions(db, current_user.id)
    return {
        "descriptions": [
            description_to_response(description) for description in descriptions
        ]
    }


@router.get(
    "/resume-project-descriptions/{description_id}",
    response_model=ResumeProjectDescriptionResponse,
)
def get_description(
    description_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        description = get_owned_resume_project_description(
            db,
            current_user.id,
            description_id,
        )
    except ResumeGenerationError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
    return description_to_response(description)


@router.delete("/resume-project-descriptions/{description_id}")
def delete_description(
    description_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        delete_resume_project_description(
            db,
            current_user.id,
            description_id,
        )
    except ResumeGenerationError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
    return {"success": True, "message": "简历项目描述已删除"}
