from collections.abc import Callable

from sqlalchemy.orm import Session

from app.agents.prompts.evidence_prompt import (
    EVIDENCE_PROMPT_VERSION,
    build_evidence_query_messages,
)
from app.agents.schemas import (
    EvidenceOutput,
    EvidenceQueryInput,
    EvidenceQueryOutput,
)
from app.agents.structured_llm import invoke_structured
from app.services.evidence_retrieval_service import retrieve_interview_evidence


class EvidenceAgent:
    name = "evidence"
    prompt_version = EVIDENCE_PROMPT_VERSION

    def __init__(self, llm_call: Callable[[list[dict]], str] | None = None):
        self.llm_call = llm_call

    def run(
        self,
        db: Session,
        user_id: int,
        session_id: int,
        payload: EvidenceQueryInput,
    ) -> EvidenceOutput:
        query_plan = invoke_structured(
            build_evidence_query_messages(payload),
            EvidenceQueryOutput,
            self.llm_call,
        )
        return retrieve_interview_evidence(
            db=db,
            user_id=user_id,
            session_id=session_id,
            query=query_plan.query,
        )
