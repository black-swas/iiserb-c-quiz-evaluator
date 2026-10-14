"""Evaluate one quiz: ingested submissions + question paper -> full report."""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from app.analyzer.c_static_analyzer import analyze_c_submission
from app.analyzer.gcc_sandbox import gcc_available, run_gcc_verification
from app.analyzer.llm_evaluator import annotate_question, new_llm_report
from app.analyzer.plagiarism_engine import (
    apply_collusion_corroboration,
    detect_cross_question_collusion,
    run_question_plagiarism_matrix,
)
from app.analyzer.triage import deterministic_triage
from app.config import settings
from app.schemas import CloneMatch, QuizPaper, SubmissionEvaluation

logger = logging.getLogger("iiserb.pipeline")

ProgressFn = Callable[[str, float, str], None]


def ist_timestamp() -> str:
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d %H:%M:%S IST")


def _matrix_cell(ev: SubmissionEvaluation) -> Dict[str, Any]:
    g = ev.gcc_result
    return {
        "submitted": True,
        "tab_category": ev.tab_category,
        "verdict_badge": ev.verdict_badge,
        "cheat_type": ev.cheat_type,
        "confidence_score": ev.confidence_score,
        "max_clone_similarity": ev.max_clone_similarity,
        "passed_tests": f"{g.passed_count}/{g.total_count}" if g and g.total_count else "-",
        "passed": g.passed_count if g else 0,
        "total": g.total_count if g else 0,
    }


async def run_full_quiz_evaluation(
    quiz_paper: QuizPaper,
    extracted: Dict[str, Any],
    progress: Optional[ProgressFn] = None,
) -> Dict[str, Any]:
    started = time.time()
    notify: ProgressFn = progress or (lambda stage, fraction, message: None)
    students: Dict[str, Dict[str, Dict[str, str]]] = extracted["students"]
    rolls = sorted(students)
    warnings: List[str] = list(extracted["warnings"])
    questions = quiz_paper.questions
    n_q = max(1, len(questions))

    unknown_questions = sorted({qid for files in students.values() for qid in files} - {q.question_id for q in questions})
    if unknown_questions:
        warnings.append(f"Files for {', '.join(unknown_questions)} were ignored: the question paper does not define them.")

    sandbox_on = settings.enable_gcc_sandbox and gcc_available()
    if not sandbox_on:
        warnings.append("The gcc sandbox is not available, so no tests were run. Every submission is reported as unverified.")

    # ---- pass 1: plagiarism per question, then cross-question corroboration
    clones_by_q: Dict[str, Dict[str, List[CloneMatch]]] = {}
    previews_by_q: Dict[str, Dict[str, str]] = {}
    for qi, q in enumerate(questions):
        notify("Comparing submissions", 0.02 + 0.08 * qi / n_q, f"{q.question_id}: pairwise structural comparison")
        submissions = {r: students[r][q.question_id]["code"] for r in rolls if q.question_id in students[r]}
        clone_map, preview_map = await asyncio.to_thread(run_question_plagiarism_matrix, q.question_id, submissions)
        clones_by_q[q.question_id], previews_by_q[q.question_id] = clone_map, preview_map
    corroborated_pairs = apply_collusion_corroboration(clones_by_q, len(rolls))
    collusion_pairs = detect_cross_question_collusion(clones_by_q)

    # ---- pass 2: static analysis + sandbox + triage + advisory LLM, question by question
    llm_report = new_llm_report()
    semaphore = asyncio.Semaphore(max(1, settings.sandbox_parallelism))
    evaluations: Dict[str, List[SubmissionEvaluation]] = {}

    for qi, q in enumerate(questions):
        base, span = 0.10 + 0.88 * qi / n_q, 0.88 / n_q
        todo = [(r, students[r][q.question_id]) for r in rolls if q.question_id in students[r]]

        async def evaluate_one(roll: str, meta: Dict[str, str], q=q) -> SubmissionEvaluation:
            code = meta["code"]
            static = await asyncio.to_thread(analyze_c_submission, code, q)
            gcc = None
            if sandbox_on and not static.is_empty_or_stub and not static.security_violations:
                async with semaphore:
                    gcc = await asyncio.to_thread(run_gcc_verification, code, q.test_cases)
            return deterministic_triage(
                roll, q, meta["filename"], code, static, gcc,
                clones_by_q[q.question_id].get(roll, []), previews_by_q[q.question_id].get(roll, ""),
            )

        results: List[SubmissionEvaluation] = []
        for finished, coro in enumerate(asyncio.as_completed([evaluate_one(r, m) for r, m in todo]), start=1):
            results.append(await coro)
            notify("Running tests", base + span * 0.8 * finished / max(1, len(todo)),
                   f"{q.question_id}: {finished}/{len(todo)} submissions")
        results.sort(key=lambda e: e.roll_no)

        if settings.llm_available:
            notify("Reviewing approach with the LLM", base + span * 0.85, f"{q.question_id}: reviewing {len(results)} submissions")
        await annotate_question(q, results, llm_report)
        evaluations[q.question_id] = results

    # ---- assemble
    matrix: Dict[str, Dict[str, Dict[str, Any]]] = {r: {} for r in rolls}
    counts = {"GREEN": 0, "BLUE": 0, "RED": 0, "GRAY": 0, "NOT_SUBMITTED": 0}
    for q in questions:
        for ev in evaluations[q.question_id]:
            matrix[ev.roll_no][q.question_id] = _matrix_cell(ev)
            counts[ev.tab_category] += 1
        for r in rolls:
            if q.question_id not in students[r]:
                counts["NOT_SUBMITTED"] += 1
                warnings.append(f"Student '{r}' did not submit {q.question_id}.")
                matrix[r][q.question_id] = {
                    "submitted": False, "tab_category": "GRAY", "verdict_badge": "Not submitted", "cheat_type": "NONE",
                    "confidence_score": 100, "max_clone_similarity": 0.0, "passed_tests": "-", "passed": 0, "total": 0,
                }
    counts["COLLUSION_PAIRS"] = len(collusion_pairs)

    report = {k: v for k, v in llm_report.items() if k != "fatal"}
    notify("Done", 1.0, "Evaluation complete")
    return {
        "course_code": quiz_paper.course_code,
        "quiz_title": quiz_paper.quiz_title,
        "evaluated_at": ist_timestamp(),
        "elapsed_seconds": round(time.time() - started, 1),
        "student_count": len(rolls),
        "total_c_files": extracted["total_c_files"],
        "summary_counts": counts,
        "questions": [q.model_dump() for q in questions],
        "evaluations_by_question": {qid: [e.model_dump() for e in evs] for qid, evs in evaluations.items()},
        "student_matrix": matrix,
        "collusion_pairs": [c.model_dump() for c in collusion_pairs],
        "ingestion_warnings": warnings,
        "ignored_binaries": extracted["ignored_binaries"],
        "engine": {
            "version": settings.app_version,
            "sandbox": sandbox_on,
            "llm": report,
            "clone_threshold_percent": settings.clone_threshold_percent,
            "corroborated_pairs": corroborated_pairs,
        },
    }
