"""FastAPI application: JSON API + static single-page UI."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.analyzer.gcc_sandbox import gcc_available
from app.analyzer.pipeline import run_full_quiz_evaluation
from app.analyzer.zip_ingestor import ZipIngestionError, extract_student_submissions
from app.config import settings
from app.database.hitl_store import get_calibration_examples, get_feedback_stats, init_hitl_db, save_hitl_feedback
from app.jobs import JobStore
from app.schemas import (
    BatchEvaluationResponse,
    HITLFeedbackRequest,
    HITLFeedbackResponse,
    JobCreated,
    JobStatus,
    QuizPaper,
)
from app.security import SlidingWindowRateLimiter, constant_time_equals, harden_process, scrub_secret_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("iiserb.api")

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
SAMPLES_DIR = APP_DIR.parent / "sample_quiz_data"
SAMPLE_NAME_SUFFIX = "_paper.json"

jobs = JobStore(ttl_seconds=settings.job_ttl_seconds, max_jobs=settings.max_stored_jobs)
rate_limiter = SlidingWindowRateLimiter()
_job_slot = asyncio.Semaphore(1)        # one evaluation at a time keeps CPU/RAM predictable on a small instance
_background_tasks: Set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    hardened = harden_process()
    scrub_secret_env()
    init_hitl_db()
    logger.info(
        "Started v%s | gcc=%s | llm=%s (%s) | auth=%s | process_hardened=%s",
        settings.app_version, gcc_available(), settings.llm_available, settings.primary_model,
        "required" if settings.auth_required else "off", hardened,
    )
    if settings.require_auth and not settings.api_auth_token:
        logger.error("REQUIRE_AUTH is set but API_AUTH_TOKEN is empty: all protected endpoints will refuse requests.")
    yield


app = FastAPI(
    title="IISER Bhopal DSE C-Lab Quiz Evaluator",
    version=settings.app_version,
    description="Hybrid GCC-sandbox, static-analysis, plagiarism and advisory-LLM triage for C lab quizzes.",
    lifespan=lifespan,
)

if settings.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.allowed_origins.split(",") if o.strip()],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key", "Authorization"],
    )


@app.middleware("http")
async def guard_and_harden(request: Request, call_next):
    if request.method == "POST":
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > settings.max_upload_bytes + 2 * 1024 * 1024:
            return JSONResponse({"detail": "Upload too large."}, status_code=413)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
    )
    return response


# --------------------------------------------------------------------------- helpers
def require_auth(request: Request, x_api_key: Optional[str] = Header(default=None)) -> None:
    if not settings.auth_required:
        return
    if not settings.api_auth_token:
        raise HTTPException(503, "Authentication is required but API_AUTH_TOKEN is not configured on the server.")
    bearer = request.headers.get("Authorization", "")
    supplied = x_api_key or (bearer[7:].strip() if bearer.lower().startswith("bearer ") else "")
    if not supplied or not constant_time_equals(supplied, settings.api_auth_token):
        raise HTTPException(401, "Missing or invalid access token.", headers={"WWW-Authenticate": "Bearer"})


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _enforce_rate_limit(request: Request, bucket: str, limit: int, window_seconds: int) -> None:
    allowed, retry_after = rate_limiter.check(f"{bucket}:{_client_key(request)}", limit, window_seconds)
    if not allowed:
        raise HTTPException(429, f"Too many requests. Try again in {retry_after}s.", headers={"Retry-After": str(retry_after)})


def parse_question_paper(raw: str) -> QuizPaper:
    """Accepts {"questions": [...]} or a bare list. Raises ValueError with a readable message."""
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"The question paper is not valid JSON: {exc}")
    if isinstance(data, list):
        data = {"questions": data}
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        raise ValueError('Expected an object with a "questions" list.')
    paper = QuizPaper(**data)
    if not paper.questions:
        raise ValueError("The question paper has no questions.")
    if len(paper.questions) > settings.max_questions_per_paper:
        raise ValueError(f"The paper has {len(paper.questions)} questions; the limit is {settings.max_questions_per_paper}.")
    ids = [q.question_id for q in paper.questions]
    if len(set(ids)) != len(ids):
        raise ValueError("Question ids must be unique.")
    return paper


async def _read_uploads(archives: List[UploadFile]) -> List[Tuple[str, bytes]]:
    total = 0
    uploads: List[Tuple[str, bytes]] = []
    for archive in archives:
        data = await archive.read(settings.max_upload_bytes - total + 1)
        total += len(data)
        if total > settings.max_upload_bytes:
            raise HTTPException(413, f"Upload exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB limit.")
        uploads.append((archive.filename or "upload.zip", data))
    return uploads


async def _prepare(question_paper_json: str, archives: List[UploadFile]) -> Tuple[QuizPaper, Dict[str, Any]]:
    try:
        paper = parse_question_paper(question_paper_json)
    except ValueError as exc:
        raise HTTPException(400, f"Invalid question paper: {exc}")
    uploads = await _read_uploads(archives)
    try:
        extracted = await asyncio.to_thread(extract_student_submissions, uploads)
    except ZipIngestionError as exc:
        raise HTTPException(400, str(exc))
    if extracted["total_c_files"] == 0:
        detail = "No C files could be matched to students and questions."
        if extracted["warnings"]:
            detail += " " + " ".join(extracted["warnings"][:3])
        raise HTTPException(400, detail)
    if len(extracted["students"]) > settings.max_students_per_session:
        raise HTTPException(400, f"{len(extracted['students'])} students found; the limit is {settings.max_students_per_session}.")
    return paper, extracted


async def _run_job(job_id: str, paper: QuizPaper, extracted: Dict[str, Any]) -> None:
    async with _job_slot:
        jobs.update(job_id, status="running", stage="Starting", progress=0.01, message="Starting evaluation")

        def on_progress(stage: str, fraction: float, message: str) -> None:
            jobs.update(job_id, stage=stage, progress=round(min(max(fraction, 0.0), 1.0), 3), message=message)

        try:
            result = await run_full_quiz_evaluation(paper, extracted, progress=on_progress)
            jobs.update(job_id, status="done", stage="Done", progress=1.0, message="Evaluation complete", result=result)
        except Exception:
            logger.exception("Evaluation job %s failed", job_id)
            jobs.update(job_id, status="error", error="The evaluation failed unexpectedly. See the server log for details.")


# --------------------------------------------------------------------------- pages and public info
@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "version": settings.app_version, "gcc": gcc_available()}


@app.get("/api/config")
def public_config() -> Dict[str, Any]:
    return {
        "version": settings.app_version,
        "auth_required": settings.auth_required,
        "sandbox": settings.enable_gcc_sandbox and gcc_available(),
        "llm": {"available": settings.llm_available, "model": settings.primary_model},
        "clone_threshold_percent": settings.clone_threshold_percent,
        "limits": {
            "max_upload_mb": settings.max_upload_bytes // (1024 * 1024),
            "max_students": settings.max_students_per_session,
            "max_questions": settings.max_questions_per_paper,
            "test_timeout_seconds": settings.test_timeout_seconds,
        },
    }


# --------------------------------------------------------------------------- sample papers
def _sample_files() -> List[Path]:
    return sorted(SAMPLES_DIR.glob(f"*{SAMPLE_NAME_SUFFIX}")) if SAMPLES_DIR.is_dir() else []


@app.get("/api/samples")
def list_samples() -> List[Dict[str, Any]]:
    out = []
    for path in _sample_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out.append({"name": path.name, "title": data.get("quiz_title", path.stem), "questions": len(data.get("questions", []))})
        except (OSError, ValueError):
            continue
    return out


@app.get("/api/samples/{name}")
def get_sample(name: str) -> JSONResponse:
    for path in _sample_files():
        if path.name == name:
            return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
    raise HTTPException(404, "Unknown sample paper.")


# --------------------------------------------------------------------------- evaluation
@app.post("/api/jobs", response_model=JobCreated, status_code=202)
async def create_job(
    request: Request,
    question_paper_json: str = Form(..., description="Question paper as JSON"),
    archives: List[UploadFile] = File(..., description="Student ZIPs, a master ZIP, or .c files"),
    _auth: Any = Depends(require_auth),
) -> JobCreated:
    _enforce_rate_limit(request, "jobs", settings.rate_limit_jobs_per_window, settings.rate_limit_window_seconds)
    if jobs.active_count() >= 3:
        raise HTTPException(503, "The server is busy with other evaluations. Try again in a few minutes.")
    paper, extracted = await _prepare(question_paper_json, archives)
    job = jobs.create(owner=_client_key(request))
    task = asyncio.create_task(_run_job(job.id, paper, extracted))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return JobCreated(job_id=job.id, status=job.status)


@app.get("/api/jobs/{job_id}", response_model=JobStatus)
def job_status(job_id: str, _auth: Any = Depends(require_auth)) -> JobStatus:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown or expired job.")
    return JobStatus(job_id=job.id, status=job.status, stage=job.stage, progress=job.progress, message=job.message, error=job.error)


@app.get("/api/jobs/{job_id}/result")
def job_result(job_id: str, _auth: Any = Depends(require_auth)) -> JSONResponse:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown or expired job.")
    if job.status != "done" or job.result is None:
        raise HTTPException(409, f"Job is {job.status}.")
    return JSONResponse(job.result)


@app.post("/api/evaluate-batch", response_model=BatchEvaluationResponse)
async def evaluate_batch(
    request: Request,
    question_paper_json: str = Form(...),
    archives: List[UploadFile] = File(...),
    _auth: Any = Depends(require_auth),
) -> BatchEvaluationResponse:
    """Synchronous variant for scripts. The UI uses /api/jobs (progress + no long-held connection)."""
    _enforce_rate_limit(request, "jobs", settings.rate_limit_jobs_per_window, settings.rate_limit_window_seconds)
    paper, extracted = await _prepare(question_paper_json, archives)
    async with _job_slot:
        result = await run_full_quiz_evaluation(paper, extracted)
    return BatchEvaluationResponse(**result)


# --------------------------------------------------------------------------- TA calibration memory
@app.get("/api/hitl-examples")
def hitl_examples(_auth: Any = Depends(require_auth)) -> Dict[str, Any]:
    return {"examples": get_calibration_examples(limit=25), "stats": get_feedback_stats()}


@app.post("/api/hitl-feedback", response_model=HITLFeedbackResponse)
def hitl_feedback(request: Request, req: HITLFeedbackRequest, _auth: Any = Depends(require_auth)) -> HITLFeedbackResponse:
    _enforce_rate_limit(request, "feedback", settings.rate_limit_feedback_per_minute, 60)
    record_id = save_hitl_feedback(req)
    return HITLFeedbackResponse(
        status="recorded",
        record_id=record_id,
        message=f"Saved TA decision for {req.roll_no} / {req.question_id}.",
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
