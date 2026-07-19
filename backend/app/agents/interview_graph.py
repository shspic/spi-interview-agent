from time import perf_counter
from typing import Literal, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.agents.evidence_agent import EvidenceAgent
from app.agents.evaluation_agent import EvaluationAgent
from app.agents.interviewer_agent import InterviewerAgent
from app.agents.schemas import (
    EvidenceOutput,
    EvidenceQueryInput,
    EvaluationInput,
    EvaluationOutput,
    InterviewerInput,
    InterviewerOutput,
    InterviewPlanInput,
    InterviewPlanOutput,
    SupervisorDecisionInput,
    SupervisorDecisionOutput,
    SupervisorEvaluationSummary,
    TrainingGuidance,
)
from app.agents.supervisor_agent import SupervisorAgent
from app.db.models import AgentRun
from app.services.interview_session_service import now_iso
from app.services.evaluation_service import persist_turn_evaluation


class InterviewGraphState(TypedDict, total=False):
    operation: Literal["start", "answer"]
    title: str
    mode: Literal["quick", "standard", "deep_dive"]
    planned_main_questions: int
    target_job_title: str | None
    training_guidance: TrainingGuidance | None
    session_id: int
    user_id: int
    plan: InterviewPlanOutput
    current_main_question: int
    current_follow_up_count: int
    current_turn_id: int
    current_question: str
    latest_answer: str
    evidence: EvidenceOutput
    evaluation: EvaluationOutput
    decision: SupervisorDecisionOutput
    generated_question: InterviewerOutput


class InterviewAgentRuntime:
    def __init__(
        self,
        db: Session,
        user_id: int,
        session_id: int,
        supervisor: SupervisorAgent | None = None,
        evidence: EvidenceAgent | None = None,
        evaluation: EvaluationAgent | None = None,
        interviewer: InterviewerAgent | None = None,
    ):
        self.db = db
        self.user_id = user_id
        self.session_id = session_id
        self.run_id = str(uuid4())
        self.supervisor = supervisor or SupervisorAgent()
        self.evidence = evidence or EvidenceAgent()
        self.evaluation = evaluation or EvaluationAgent()
        self.interviewer = interviewer or InterviewerAgent()

    def execute(self, agent, callback):
        started = perf_counter()
        try:
            result = callback()
        except Exception as exc:
            self.db.rollback()
            self._record_run(
                agent_name=agent.name,
                prompt_version=agent.prompt_version,
                status="error",
                latency_ms=int((perf_counter() - started) * 1000),
                error=self._sanitize_error(exc),
            )
            raise
        self._record_run(
            agent_name=agent.name,
            prompt_version=agent.prompt_version,
            status="success",
            latency_ms=int((perf_counter() - started) * 1000),
            error=None,
        )
        return result

    def _sanitize_error(self, error: Exception) -> str:
        return f"{type(error).__name__}: Agent 执行失败"

    def _record_run(
        self,
        *,
        agent_name: str,
        prompt_version: str,
        status: str,
        latency_ms: int,
        error: str | None,
    ) -> None:
        self.db.add(
            AgentRun(
                run_id=self.run_id,
                session_id=self.session_id,
                user_id=self.user_id,
                agent_name=agent_name,
                prompt_version=prompt_version,
                status=status,
                latency_ms=max(latency_ms, 0),
                error=error,
                created_at=now_iso(),
            )
        )
        self.db.commit()

    def summary(self, workflow_status: str, error: str | None = None) -> dict:
        runs = (
            self.db.query(AgentRun)
            .filter(
                AgentRun.run_id == self.run_id,
                AgentRun.user_id == self.user_id,
                AgentRun.session_id == self.session_id,
            )
            .order_by(AgentRun.id.asc())
            .all()
        )
        return {
            "run_id": self.run_id,
            "status": workflow_status,
            "error": error,
            "agents": [
                {
                    "agent_name": run.agent_name,
                    "prompt_version": run.prompt_version,
                    "status": run.status,
                    "latency_ms": run.latency_ms,
                }
                for run in runs
            ],
        }


def build_interview_graph(runtime: InterviewAgentRuntime):
    def supervisor_plan_node(state: InterviewGraphState) -> dict:
        payload = InterviewPlanInput(
            title=state["title"],
            mode=state["mode"],
            planned_main_questions=state["planned_main_questions"],
            target_job_title=state.get("target_job_title"),
            training_guidance=state.get("training_guidance"),
        )
        plan = runtime.execute(
            runtime.supervisor,
            lambda: runtime.supervisor.create_plan(payload),
        )
        return {"plan": plan}

    def evidence_node(state: InterviewGraphState) -> dict:
        payload = EvidenceQueryInput(
            title=state["title"],
            mode=state["mode"],
            plan=state["plan"],
            current_question=state.get("current_question"),
            latest_answer=state.get("latest_answer"),
        )
        evidence = runtime.execute(
            runtime.evidence,
            lambda: runtime.evidence.run(
                runtime.db,
                runtime.user_id,
                runtime.session_id,
                payload,
            ),
        )
        return {"evidence": evidence}

    def supervisor_decision_node(state: InterviewGraphState) -> dict:
        evaluation = state["evaluation"]
        payload = SupervisorDecisionInput(
            mode=state["mode"],
            planned_main_questions=state["planned_main_questions"],
            current_main_question=state["current_main_question"],
            current_follow_up_count=state["current_follow_up_count"],
            question=state["current_question"],
            answer=state["latest_answer"],
            evidence=state["evidence"],
            evaluation=SupervisorEvaluationSummary(
                technical_accuracy_score=evaluation.technical_accuracy_score,
                evidence_consistency_score=evaluation.evidence_consistency_score,
                answer_depth_score=evaluation.answer_depth_score,
                has_evidence_conflict=evaluation.has_evidence_conflict,
                evaluation_summary=evaluation.evaluation_summary,
            ),
        )
        decision = runtime.execute(
            runtime.supervisor,
            lambda: runtime.supervisor.decide(payload),
        )
        return {"decision": decision}

    def evaluation_node(state: InterviewGraphState) -> dict:
        payload = EvaluationInput(
            question=state["current_question"],
            answer=state["latest_answer"],
            evidence=state["evidence"],
        )
        evaluation = runtime.execute(
            runtime.evaluation,
            lambda: runtime.evaluation.evaluate(payload),
        )
        persisted = persist_turn_evaluation(
            runtime.db,
            runtime.user_id,
            runtime.session_id,
            state["current_turn_id"],
            evaluation,
            state["evidence"],
        )
        return {"evaluation": persisted}

    def interviewer_node(state: InterviewGraphState) -> dict:
        if state["operation"] == "start":
            action = "main_question"
            main_question_number = 1
            previous_question = None
            previous_answer = None
            follow_up_reason = None
        else:
            decision = state["decision"]
            action = (
                "follow_up"
                if decision.action == "follow_up"
                else "main_question"
            )
            main_question_number = state["current_main_question"] + (
                1 if action == "main_question" else 0
            )
            previous_question = state["current_question"]
            previous_answer = state["latest_answer"]
            follow_up_reason = decision.reason
        payload = InterviewerInput(
            action=action,
            mode=state["mode"],
            main_question_number=main_question_number,
            plan=state["plan"],
            evidence=state["evidence"],
            previous_question=previous_question,
            previous_answer=previous_answer,
            follow_up_reason=follow_up_reason,
        )
        question = runtime.execute(
            runtime.interviewer,
            lambda: runtime.interviewer.generate_question(payload),
        )
        return {"generated_question": question}

    builder = StateGraph(InterviewGraphState)
    builder.add_node("supervisor_plan", supervisor_plan_node)
    builder.add_node("evidence", evidence_node)
    builder.add_node("evaluation", evaluation_node)
    builder.add_node("supervisor_decision", supervisor_decision_node)
    builder.add_node("interviewer", interviewer_node)
    builder.add_conditional_edges(
        START,
        lambda state: state["operation"],
        {"start": "supervisor_plan", "answer": "evidence"},
    )
    builder.add_edge("supervisor_plan", "evidence")
    builder.add_conditional_edges(
        "evidence",
        lambda state: (
            "start"
            if state["operation"] == "start"
            else "evaluated"
            if state.get("evaluation") is not None
            else "evaluate"
        ),
        {
            "start": "interviewer",
            "evaluate": "evaluation",
            "evaluated": "supervisor_decision",
        },
    )
    builder.add_edge("evaluation", "supervisor_decision")
    builder.add_conditional_edges(
        "supervisor_decision",
        lambda state: (
            "complete" if state["decision"].action == "complete" else "question"
        ),
        {"complete": END, "question": "interviewer"},
    )
    builder.add_edge("interviewer", END)
    return builder.compile()


def run_interview_graph(
    runtime: InterviewAgentRuntime,
    initial_state: InterviewGraphState,
) -> InterviewGraphState:
    graph = build_interview_graph(runtime)
    return graph.invoke(initial_state)
