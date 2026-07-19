import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CASE_DIR = BASE_DIR / "cases"
FIXTURE_DIR = BASE_DIR / "fixtures"
RESULTS_DIR = BASE_DIR / "results"

GROUPS = (
    "retrieval",
    "evidence",
    "evaluation",
    "supervisor",
    "improvement",
    "resume",
    "security",
    "reliability",
)

BASELINE_THRESHOLDS = {
    "cross_user_leakage_count": ("max", 0),
    "invalid_evidence_source_count": ("max", 0),
    "total_score_error_count": ("max", 0),
    "follow_up_limit_violation_count": ("max", 0),
    "duplicate_charge_count": ("max", 0),
    "orphan_record_count": ("max", 0),
    "uncaught_exception_count": ("max", 0),
    "structured_output_success_rate": ("min", 0.95),
    "retrieval_recall_at_3": ("min", 0.80),
    "evidence_sufficiency_accuracy": ("min", 0.80),
    "supervisor_decision_accuracy": ("min", 0.80),
    "conflict_detection_accuracy": ("min", 0.75),
    "unsupported_number_block_rate": ("min", 0.90),
    "unsupported_technology_block_rate": ("min", 0.90),
}

UNCONDITIONAL_BASELINE_METRICS = {
    "cross_user_leakage_count",
    "invalid_evidence_source_count",
    "uncaught_exception_count",
}

BASELINE_METRIC_GROUPS = {
    "total_score_error_count": {"evaluation", "reliability"},
    "follow_up_limit_violation_count": {"supervisor"},
    "duplicate_charge_count": {"reliability"},
    "orphan_record_count": {"reliability"},
    "structured_output_success_rate": {
        "evaluation",
        "improvement",
        "resume",
        "reliability",
    },
    "retrieval_recall_at_3": {"retrieval"},
    "evidence_sufficiency_accuracy": {"evidence"},
    "supervisor_decision_accuracy": {"supervisor"},
    "conflict_detection_accuracy": {"evaluation"},
    "unsupported_number_block_rate": {"security"},
    "unsupported_technology_block_rate": {"security"},
}

MAX_REAL_MODEL_CASES = 5
MAX_REAL_MODEL_CALLS = 10


def configure_isolated_environment(work_dir: Path) -> None:
    """在导入生产配置前屏蔽本地 .env 并绑定临时数据路径。"""
    os.environ["SKIP_DOTENV"] = "1"
    os.environ["SQLITE_DB_PATH"] = str(work_dir / "eval.sqlite3")
    os.environ["UPLOAD_DIR"] = str(work_dir / "uploads")
    os.environ["CHROMA_PERSIST_DIR"] = str(work_dir / "chroma")
    os.environ["DEEPSEEK_API_KEY"] = ""
    os.environ["TAVILY_API_KEY"] = ""
    os.environ["REGISTRATION_INVITE_CODE"] = "eval-placeholder"
    os.environ["JWT_SECRET_KEY"] = "eval-placeholder-secret-not-for-production"
