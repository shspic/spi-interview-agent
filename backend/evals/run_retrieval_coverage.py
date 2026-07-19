import argparse
import json
import os
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="离线运行 coverage evidence set 评估")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-model-cache", action="store_true")
    mode.add_argument("--check-datasets", action="store_true")
    mode.add_argument("--verify-production-freeze", action="store_true")
    mode.add_argument("--real-embedding", action="store_true")
    parser.add_argument(
        "--dataset",
        choices=("development", "validation", "holdout"),
        default="development",
    )
    parser.add_argument("--final-holdout", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    return parser


def main() -> int:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["ANONYMIZED_TELEMETRY"] = "False"
    args = _parser().parse_args()

    from evals import retrieval_calibration, retrieval_coverage

    if args.check_model_cache:
        print(
            json.dumps(
                retrieval_calibration.model_cache_status(),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.check_datasets:
        print(
            json.dumps(
                retrieval_coverage.verify_dataset_discipline(),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.verify_production_freeze:
        freeze = retrieval_coverage.verify_coverage_production_freeze()
        print(
            json.dumps(
                {
                    "final_holdout_frozen": freeze["final_holdout_frozen"],
                    "formal_run_completed": freeze["formal_run_completed"],
                    "network_disabled": freeze["network_disabled"],
                    "freeze_sha256": freeze["freeze_sha256"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.final_holdout and args.dataset != "holdout":
        raise SystemExit("--final-holdout 只能用于 holdout 数据集")
    if args.dataset == "holdout" and not args.final_holdout:
        raise SystemExit("coverage holdout 只能在生产冻结后正式运行")
    summary, output_dir = retrieval_coverage.run_coverage_evaluation(
        dataset_name=args.dataset,
        output_base=args.output_dir or retrieval_coverage.RESULTS_DIR,
        final_holdout=args.final_holdout,
    )
    final_metrics = summary["strategies"][retrieval_coverage.FINAL_STRATEGY]["metrics"]
    print(
        "Coverage 评估完成："
        f"{summary['query_count']} 个 query / {summary['chunk_count']} 个 chunk；"
        f"方案 D Recall@3={final_metrics['recall_at_3']:.2%}，"
        f"Facet@3={final_metrics['facet_coverage_at_3']:.2%}"
    )
    print(f"报告目录：{output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
