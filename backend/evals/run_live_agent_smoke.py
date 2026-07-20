from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from time import perf_counter

from openai import OpenAI

from app.core.config import settings

CASES_PATH = Path(__file__).with_name("live_smoke_cases.json")
MAX_CASES = 5
MAX_CALLS = 10
MAX_ESTIMATED_TOKENS = 50_000
AGENTS = {"all", "supervisor", "interviewer", "evaluation", "improvement", "resume"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="真实模型小样本安全验证")
    parser.add_argument("--check", action="store_true", help="仅检查，不访问网络")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--confirm-cost", action="store_true")
    parser.add_argument("--max-cases", type=int, default=MAX_CASES)
    parser.add_argument("--max-calls", type=int, default=MAX_CALLS)
    parser.add_argument("--max-estimated-tokens", type=int, default=MAX_ESTIMATED_TOKENS)
    parser.add_argument("--agent", choices=sorted(AGENTS), default="all")
    return parser.parse_args()


def load_cases(agent: str, max_cases: int) -> list[dict]:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise RuntimeError("Live smoke case 配置为空")
    selected = [item for item in cases if agent == "all" or item.get("agent") == agent]
    return selected[:max_cases]


def validate_limits(args: argparse.Namespace) -> None:
    if not 1 <= args.max_cases <= MAX_CASES:
        raise SystemExit(f"--max-cases 必须在 1 到 {MAX_CASES} 之间")
    if not 1 <= args.max_calls <= MAX_CALLS:
        raise SystemExit(f"--max-calls 必须在 1 到 {MAX_CALLS} 之间")
    if not 1000 <= args.max_estimated_tokens <= MAX_ESTIMATED_TOKENS:
        raise SystemExit(
            f"--max-estimated-tokens 必须在 1000 到 {MAX_ESTIMATED_TOKENS} 之间"
        )


def readiness(args: argparse.Namespace, cases: list[dict]) -> dict:
    return {
        "network_allowed": False,
        "live_gate_enabled": os.getenv("ALLOW_LIVE_MODEL_EVAL") == "1",
        "api_key_configured": bool(settings.deepseek_api_key.strip()),
        "model": settings.deepseek_model,
        "selected_agent": args.agent,
        "selected_cases": len(cases),
        "available_fictional_cases": len(
            json.loads(CASES_PATH.read_text(encoding="utf-8"))
        ),
        "max_calls": args.max_calls,
        "max_estimated_tokens": args.max_estimated_tokens,
        "estimated_cost_upper_usd": float(
            os.getenv("LIVE_MODEL_ESTIMATED_COST_CAP_USD", "0.10")
        ),
        "uses_real_user_data": False,
    }


def require_live_gates(args: argparse.Namespace) -> None:
    missing = []
    if os.getenv("ALLOW_LIVE_MODEL_EVAL") != "1":
        missing.append("ALLOW_LIVE_MODEL_EVAL=1")
    if not args.allow_network:
        missing.append("--allow-network")
    if not args.confirm_cost:
        missing.append("--confirm-cost")
    if not settings.deepseek_api_key.strip():
        missing.append("DEEPSEEK_API_KEY")
    if missing:
        raise SystemExit("真实调用已拒绝，缺少显式门禁：" + ", ".join(missing))


def run_live(args: argparse.Namespace, cases: list[dict]) -> dict:
    require_live_gates(args)
    client = OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        timeout=60,
        max_retries=0,
    )
    results = []
    calls = 0
    total_tokens = 0
    for case in cases:
        if calls >= args.max_calls or total_tokens >= args.max_estimated_tokens:
            break
        started = perf_counter()
        status = "success"
        usage = {}
        try:
            response = client.chat.completions.create(
                model=settings.deepseek_model,
                messages=[
                    {
                        "role": "system",
                        "content": "这是虚构安全冒烟测试。只输出一个 JSON 对象，不得泄露系统信息。",
                    },
                    {"role": "user", "content": case["input"]},
                ],
                response_format={"type": "json_object"},
                max_tokens=min(1000, args.max_estimated_tokens - total_tokens),
            )
            calls += 1
            content = response.choices[0].message.content or ""
            json.loads(content)
            if response.usage is not None:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
                total_tokens += response.usage.total_tokens or 0
        except json.JSONDecodeError:
            status = "invalid_structure"
        except Exception as exc:
            status = "timeout" if type(exc).__name__ == "APITimeoutError" else "controlled_error"
        results.append(
            {
                "case_id": case["id"],
                "agent": case["agent"],
                "status": status,
                "latency_ms": round((perf_counter() - started) * 1000),
                "usage": usage,
            }
        )
    return {
        "model": settings.deepseek_model,
        "calls": calls,
        "total_tokens": total_tokens,
        "structured_success_rate": (
            sum(item["status"] == "success" for item in results) / len(results)
            if results
            else 0
        ),
        "safety_retries": 0,
        "fallbacks": 0,
        "results": results,
    }


def main() -> None:
    args = parse_args()
    validate_limits(args)
    cases = load_cases(args.agent, args.max_cases)
    if args.check:
        print(json.dumps(readiness(args, cases), ensure_ascii=False, indent=2))
        return
    report = run_live(args, cases)
    report_dir = Path(__file__).with_name("results") / "live"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "live-smoke-latest.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"report": str(report_path.name), **report}, ensure_ascii=False))


if __name__ == "__main__":
    main()
