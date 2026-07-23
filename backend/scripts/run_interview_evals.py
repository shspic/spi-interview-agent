import argparse
import json
import os
import sys
from pathlib import Path

from app.agents.evaluation_agent import EvaluationAgent
from app.agents.schemas import EvaluationInput, EvidenceItem, EvidenceOutput
from app.services.llm_service import chat_with_messages
from evals.interview_core_cases import INTERVIEW_CORE_CASES
from evals.interview_core_runner import run_offline_evaluations

MAX_ONLINE_CASES = 4
MAX_MODEL_CALLS = 8
ONLINE_CASE_IDS = (
    "eval_high_quality_star",
    "eval_exaggerated_responsibility",
    "eval_profile_conflict",
    "eval_insufficient_evidence",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行面试核心链路评测")
    parser.add_argument("--online", action="store_true", help="启用受限 DeepSeek 验证")
    parser.add_argument("--max-online-cases", type=int, default=MAX_ONLINE_CASES)
    parser.add_argument("--max-model-calls", type=int, default=MAX_MODEL_CALLS)
    parser.add_argument("--online-case-id", choices=ONLINE_CASE_IDS)
    parser.add_argument("--output", type=Path)
    return parser


def validate_online_args(args: argparse.Namespace) -> None:
    if not args.online:
        return
    if os.getenv("EVAL_REAL_MODEL_ENABLED") != "1":
        raise SystemExit("在线模式必须显式设置 EVAL_REAL_MODEL_ENABLED=1")
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("在线模式缺少 DEEPSEEK_API_KEY")
    if not 1 <= args.max_online_cases <= MAX_ONLINE_CASES:
        raise SystemExit(f"在线模式最多运行 {MAX_ONLINE_CASES} 个案例")
    if not 1 <= args.max_model_calls <= MAX_MODEL_CALLS:
        raise SystemExit(f"在线模式最多调用 {MAX_MODEL_CALLS} 次")
    if args.max_model_calls < args.max_online_cases:
        raise SystemExit("模型调用上限不能小于在线案例数")


def _online_input(case: dict) -> EvaluationInput:
    data = case["input_context"]
    evidence_text = data.get("evidence", "")
    project = []
    if evidence_text:
        project.append(
            EvidenceItem(
                evidence_type="project",
                source_id=f"synthetic:{case['id']}",
                content=evidence_text,
            )
        )
    evidence = EvidenceOutput(
        is_sufficient=bool(project),
        reason="合成在线评测证据" if project else "未找到支持证据",
        best_distance=0.2 if project else None,
        sources=project,
        context=evidence_text,
        profile_evidence=[],
        project_evidence=project,
        resume_evidence=[],
        job_requirements=[],
    )
    return EvaluationInput(
        question=data.get("question", "请基于真实经历回答。"),
        answer=data["answer"],
        evidence=evidence,
    )


def run_online(args: argparse.Namespace) -> dict:
    selected = [
        case
        for case in INTERVIEW_CORE_CASES
        if case["id"] in ONLINE_CASE_IDS
        and (args.online_case_id is None or case["id"] == args.online_case_id)
    ][: args.max_online_cases]
    call_count = 0
    results = []

    def limited_call(messages: list[dict]) -> str:
        nonlocal call_count
        if call_count >= args.max_model_calls:
            raise ValueError("已达到在线模型调用上限")
        call_count += 1
        return chat_with_messages(messages)

    print(
        f"在线评测预计运行 {len(selected)} 个案例；"
        f"每个案例最多重试一次，模型调用硬上限 {args.max_model_calls} 次。"
    )
    for case in selected:
        try:
            result = EvaluationAgent(llm_call=limited_call).evaluate(_online_input(case))
            passed = True
            reason = "结构与生产语义校验通过"
            if case["assertions"].get("has_conflict") and not result.has_evidence_conflict:
                passed = False
                reason = "未识别预期证据冲突"
            if case["assertions"].get("conservative"):
                combined = result.evaluation_summary + result.optimized_answer
                if not any(word in combined for word in ("证据", "核实", "不足", "无法确认")):
                    passed = False
                    reason = "资料不足时缺少保守表达"
            results.append({"id": case["id"], "passed": passed, "reason": reason})
        except Exception as exc:
            results.append(
                {"id": case["id"], "passed": False, "reason": f"{type(exc).__name__}: {exc}"}
            )
    return {
        "case_count": len(selected),
        "passed": sum(item["passed"] for item in results),
        "failed": sum(not item["passed"] for item in results),
        "model_calls": call_count,
        "results": results,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    validate_online_args(args)
    offline = run_offline_evaluations().as_dict()
    report = {"mode": "online" if args.online else "offline", "offline": offline}
    if args.online:
        report["online"] = run_online(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    online_failed = report.get("online", {}).get("failed", 0)
    return 0 if offline["failed"] == 0 and online_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
