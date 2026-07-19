import argparse
import json
import os
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行隔离的真实 BGE / Chroma 检索校准")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-model-cache", action="store_true")
    mode.add_argument("--real-embedding", action="store_true")
    parser.add_argument(
        "--dataset",
        choices=("development", "validation", "holdout"),
        default="development",
    )
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--final-holdout", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    os.environ["SKIP_DOTENV"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["ANONYMIZED_TELEMETRY"] = "False"
    os.environ["DEEPSEEK_API_KEY"] = ""
    os.environ["TAVILY_API_KEY"] = ""

    from evals import retrieval_calibration

    if args.check_model_cache:
        print(json.dumps(retrieval_calibration.model_cache_status(), ensure_ascii=False, indent=2))
        return 0
    if not args.real_embedding:
        print("真实 Embedding 校准默认关闭；请显式使用 --real-embedding。")
        return 0
    if args.baseline_only and args.final_holdout:
        raise SystemExit("--baseline-only 与 --final-holdout 不能同时使用")
    if args.final_holdout and args.dataset != "holdout":
        raise SystemExit("--final-holdout 只能用于 holdout 数据集")
    if args.dataset == "holdout" and not (args.baseline_only or args.final_holdout):
        raise SystemExit("holdout 只能用于修改前基线或冻结后的最终验证")
    freeze = (
        retrieval_calibration.verify_production_freeze()
        if args.final_holdout
        else None
    )

    output_base = args.output_dir or retrieval_calibration.RESULTS_DIR
    summary, output_dir = retrieval_calibration.run_real_calibration(
        output_base,
        dataset_name=args.dataset,
        evaluation_stage=(
            "pre_change_baseline"
            if args.baseline_only
            else "final_frozen_holdout"
            if args.final_holdout
            else "calibration"
        ),
        suppress_case_details=(args.dataset == "holdout" and args.baseline_only),
        final_holdout_frozen=args.final_holdout,
        production_freeze_sha256=(freeze or {}).get("freeze_sha256"),
    )
    if summary["status"] == "skipped_model_cache_missing":
        print("本地未发现所需 Embedding 模型缓存，校准未执行。未发起网络下载。")
        print(f"报告目录：{output_dir}")
        return 0
    print(
        f"真实 Embedding 校准完成：{summary['query_count']} 个 query / "
        f"{summary['chunk_count']} 个 chunk"
    )
    print(f"报告目录：{output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
