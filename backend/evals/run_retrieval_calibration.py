import argparse
import json
import os
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行隔离的真实 BGE / Chroma 检索校准")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-model-cache", action="store_true")
    mode.add_argument("--real-embedding", action="store_true")
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

    output_base = args.output_dir or retrieval_calibration.RESULTS_DIR
    summary, output_dir = retrieval_calibration.run_real_calibration(output_base)
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
