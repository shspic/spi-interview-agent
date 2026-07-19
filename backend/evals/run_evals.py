import argparse
import os
import tempfile
from pathlib import Path

from evals.config import (
    GROUPS,
    MAX_REAL_MODEL_CALLS,
    MAX_REAL_MODEL_CASES,
    RESULTS_DIR,
    configure_isolated_environment,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行 SPI 面试 Agent 离线评估")
    parser.add_argument("--group", action="append", choices=GROUPS)
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--real-model", action="store_true")
    parser.add_argument("--max-cases", type=int, default=MAX_REAL_MODEL_CASES)
    parser.add_argument("--max-model-calls", type=int, default=MAX_REAL_MODEL_CALLS)
    return parser


def validate_real_model_args(args: argparse.Namespace) -> None:
    if not args.real_model:
        return
    if os.getenv("EVAL_REAL_MODEL_ENABLED") != "1":
        raise SystemExit("真实模型模式必须显式设置 EVAL_REAL_MODEL_ENABLED=1")
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("真实模型模式缺少 DEEPSEEK_API_KEY")
    if not 1 <= args.max_cases <= MAX_REAL_MODEL_CASES:
        raise SystemExit(f"真实模型最多运行 {MAX_REAL_MODEL_CASES} 个 case")
    if not 1 <= args.max_model_calls <= MAX_REAL_MODEL_CALLS:
        raise SystemExit(f"真实模型最多调用 {MAX_REAL_MODEL_CALLS} 次")
    raise SystemExit("真实模型执行器尚未启用；本阶段只提供显式门禁和调用上限")


def main() -> int:
    args = build_parser().parse_args()
    validate_real_model_args(args)
    with tempfile.TemporaryDirectory(prefix="spi-evals-") as temp_dir:
        configure_isolated_environment(Path(temp_dir))
        from evals.runner import run_evaluations

        summary, _, output_dir = run_evaluations(
            set(args.group) if args.group else None,
            args.output_dir,
        )
    print(
        f"评估完成：{summary.passed}/{summary.total} 通过，"
        f"基线门槛={'通过' if summary.baseline_passed else '未通过'}"
    )
    print(f"报告目录：{output_dir}")
    return 0 if summary.failed == 0 and summary.baseline_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
