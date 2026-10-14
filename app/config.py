"""Runtime configuration. Everything comes from environment variables (see .env.example)."""
import os
from dataclasses import dataclass


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


@dataclass
class Settings:
    app_version: str = "3.0.0"

    # ---- LLM (advisory layer only; deterministic results are authoritative)
    anthropic_api_key: str = _env_str("ANTHROPIC_API_KEY")
    primary_model: str = _env_str("ANTHROPIC_MODEL", "claude-haiku-5-5")
    fallback_model: str = _env_str("FALLBACK_MODEL", "claude-haiku-4-5-20251001")
    llm_enabled: bool = _env_bool("LLM_ENABLED", True)
    llm_batch_size: int = _env_int("LLM_BATCH_SIZE", 8)
    llm_concurrency: int = _env_int("LLM_CONCURRENCY", 3)
    llm_timeout_seconds: float = _env_float("LLM_TIMEOUT_SECONDS", 60.0)
    llm_max_retries: int = _env_int("LLM_MAX_RETRIES", 2)

    # ---- sandbox
    enable_gcc_sandbox: bool = _env_bool("ENABLE_GCC_SANDBOX", True)
    test_timeout_seconds: float = _env_float("GCC_TIMEOUT_SECONDS", 3.0)       # wall clock per test case
    compile_timeout_seconds: float = _env_float("COMPILE_TIMEOUT_SECONDS", 10.0)
    rlimit_cpu_seconds: int = _env_int("RLIMIT_CPU_SECONDS", 5)
    rlimit_as_bytes: int = _env_int("RLIMIT_AS_BYTES", 128 * 1024 * 1024)
    rlimit_fsize_bytes: int = _env_int("RLIMIT_FSIZE_BYTES", 0)
    rlimit_nproc: int = _env_int("RLIMIT_NPROC", 1)
    max_output_bytes: int = _env_int("MAX_OUTPUT_BYTES", 65536)
    sandbox_parallelism: int = _env_int("SANDBOX_PARALLELISM", 2)
    sandbox_test_workers: int = _env_int("SANDBOX_TEST_WORKERS", 4)       # test cases run at once per submission

    # ---- plagiarism
    clone_threshold_percent: float = _env_float("CLONE_THRESHOLD_PERCENT", 88.0)
    clone_near_exact_percent: float = _env_float("CLONE_NEAR_EXACT_PERCENT", 97.0)
    clone_min_tokens: int = _env_int("CLONE_MIN_TOKENS", 30)
    clone_exclusive_min_percent: float = _env_float("CLONE_EXCLUSIVE_MIN_PERCENT", 20.0)
    collusion_min_questions: int = _env_int("COLLUSION_MIN_QUESTIONS", 2)

    # ---- upload limits
    max_upload_bytes: int = _env_int("MAX_UPLOAD_BYTES", 25 * 1024 * 1024)
    max_uncompressed_bytes: int = _env_int("MAX_UNCOMPRESSED_BYTES", 50 * 1024 * 1024)
    max_single_file_bytes: int = _env_int("MAX_SINGLE_FILE_BYTES", 2 * 1024 * 1024)
    max_file_count: int = _env_int("MAX_FILE_COUNT", 1000)
    max_nesting_depth: int = _env_int("MAX_NESTING_DEPTH", 3)
    max_students_per_session: int = _env_int("MAX_STUDENTS_PER_SESSION", 60)
    max_questions_per_paper: int = _env_int("MAX_QUESTIONS_PER_PAPER", 10)

    # ---- access control
    api_auth_token: str = _env_str("API_AUTH_TOKEN")
    require_auth: bool = _env_bool("REQUIRE_AUTH", False)
    allowed_origins: str = _env_str("ALLOWED_ORIGINS", "")
    rate_limit_jobs_per_window: int = _env_int("RATE_LIMIT_JOBS_PER_WINDOW", 10)
    rate_limit_window_seconds: int = _env_int("RATE_LIMIT_WINDOW_SECONDS", 600)
    rate_limit_feedback_per_minute: int = _env_int("RATE_LIMIT_FEEDBACK_PER_MIN", 60)

    # ---- storage / jobs
    sqlite_db_path: str = _env_str("SQLITE_DB_PATH", "./data/hitl_calibration.db")
    job_ttl_seconds: int = _env_int("JOB_TTL_SECONDS", 7200)
    max_stored_jobs: int = _env_int("MAX_STORED_JOBS", 6)

    @property
    def auth_required(self) -> bool:
        return self.require_auth or bool(self.api_auth_token)

    @property
    def llm_available(self) -> bool:
        return self.llm_enabled and bool(self.anthropic_api_key)


settings = Settings()
