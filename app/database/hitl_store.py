"""TA calibration memory (SQLite). One store, one code path.

TA corrections are shown to the LLM as few-shot examples when it judges *approach* (standard vs
creative). They can never change a test-based verdict, so a poisoned or mistaken example cannot turn a
failing submission green or erase a plagiarism flag.
"""
import json
import logging
import re
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.analyzer.c_static_analyzer import PROMPT_INJECTION_PATTERNS
from app.config import settings
from app.schemas import HITLFeedbackRequest

logger = logging.getLogger("iiserb.hitl")

_LOCK = threading.Lock()
_READY: Dict[str, Path] = {}      # configured path -> resolved, initialised path

SEED_EXAMPLES = [
    {
        "question_id": "Q1", "topic_tags": ["bitwise", "loops", "number-theory"],
        "problem_summary": "Count set bits of N",
        "code_snippet": "while (n) { n &= (n - 1); count++; }",
        "original_category": "GREEN", "override_category": "BLUE",
        "ta_explanation": "Kernighan's n &= (n-1) clears the lowest set bit: a creative O(set bits) approach worth a quick look.",
    },
    {
        "question_id": "Q3", "topic_tags": ["loops", "series", "math"],
        "problem_summary": "Sum of multiples below N",
        "code_snippet": "long long s3 = 3 * p3 * (p3 + 1) / 2;",
        "original_category": "GREEN", "override_category": "BLUE",
        "ta_explanation": "Closed-form arithmetic-series sums replace the loop: valid and creative.",
    },
    {
        "question_id": "Q2", "topic_tags": ["arrays", "pointers", "reversal"],
        "problem_summary": "Print an array reversed",
        "code_snippet": 'printf("%d%s", a[i], (i == n - 1) ? "\\n" : " ");',
        "original_category": "BLUE", "override_category": "GREEN",
        "ta_explanation": "Using ?: only to print separators is ordinary style, not a creative approach.",
    },
    {
        "question_id": "Q1", "topic_tags": ["recursion", "number-theory", "loops"],
        "problem_summary": "Greatest common divisor",
        "code_snippet": "return b ? gcd(b, a % b) : a;",
        "original_category": "BLUE", "override_category": "GREEN",
        "ta_explanation": "Recursive Euclid is the standard answer when the topic is recursion.",
    },
]


def sanitize_ta_text(text: str, max_len: int = 400) -> str:
    """Plain-text only: no control characters, no angle brackets, instruction-like phrases removed."""
    if not text:
        return ""
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", text).replace("<", " ").replace(">", " ")
    for pattern in PROMPT_INJECTION_PATTERNS:
        text = re.sub(pattern, "[removed]", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()[:max_len]


def _writable(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=5.0)
        conn.execute("CREATE TABLE IF NOT EXISTS _probe (id INTEGER)")
        conn.execute("DROP TABLE IF EXISTS _probe")
        conn.commit()
        conn.close()
        return True
    except (OSError, sqlite3.Error):
        return False


def _db_path() -> Path:
    configured = settings.sqlite_db_path
    if configured in _READY:
        return _READY[configured]
    target = Path(configured).resolve()
    if not _writable(target):
        fallback = Path(tempfile.gettempdir()) / "iiserb_hitl_calibration.db"
        logger.warning("SQLite path %s is not writable; using %s (data will not persist across restarts)", target, fallback)
        target = fallback
    _READY[configured] = target
    return target


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_hitl_db() -> None:
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS hitl_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    course_code TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    topic_tags TEXT NOT NULL,
                    problem_summary TEXT NOT NULL,
                    roll_no TEXT NOT NULL,
                    code_snippet TEXT NOT NULL,
                    original_category TEXT NOT NULL,
                    original_cheat_type TEXT NOT NULL,
                    ta_decision TEXT NOT NULL,
                    override_category TEXT NOT NULL,
                    ta_explanation TEXT NOT NULL
                )
                """
            )
            if conn.execute("SELECT COUNT(*) FROM hitl_feedback").fetchone()[0] == 0:
                now = datetime.now(timezone.utc).isoformat()
                for ex in SEED_EXAMPLES:
                    conn.execute(
                        "INSERT INTO hitl_feedback (created_at, course_code, question_id, topic_tags, problem_summary, roll_no,"
                        " code_snippet, original_category, original_cheat_type, ta_decision, override_category, ta_explanation)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (now, "DSE-101", ex["question_id"], json.dumps(ex["topic_tags"]), ex["problem_summary"], "seed",
                         ex["code_snippet"], ex["original_category"], "NONE", "DISAGREE", ex["override_category"], ex["ta_explanation"]),
                    )
            conn.commit()
        finally:
            conn.close()


def save_hitl_feedback(req: HITLFeedbackRequest) -> int:
    init_hitl_db()
    row: Tuple[Any, ...] = (
        datetime.now(timezone.utc).isoformat(),
        req.course_code,
        req.question_id,
        json.dumps([t[:40] for t in req.topic_tags[:10]]),
        sanitize_ta_text(req.problem_summary, 300),
        req.roll_no[:80],
        sanitize_ta_text(req.raw_code, 800),
        req.original_category,
        req.original_cheat_type[:60],
        req.ta_decision,
        req.override_category,
        sanitize_ta_text(req.ta_explanation, 400),
    )
    with _LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                "INSERT INTO hitl_feedback (created_at, course_code, question_id, topic_tags, problem_summary, roll_no,"
                " code_snippet, original_category, original_cheat_type, ta_decision, override_category, ta_explanation)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                row,
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def get_calibration_examples(topic_tags: Optional[List[str]] = None, limit: int = 5) -> List[Dict[str, Any]]:
    """Most relevant TA corrections (DISAGREE rows), preferring matching topic tags, then recency."""
    init_hitl_db()
    with _LOCK:
        conn = _connect()
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM hitl_feedback WHERE ta_decision = 'DISAGREE' ORDER BY id DESC LIMIT 200").fetchall()]
        finally:
            conn.close()
    if not topic_tags:
        return rows[:limit]
    wanted = {t.lower() for t in topic_tags}
    scored = []
    for r in rows:
        try:
            have = {t.lower() for t in json.loads(r.get("topic_tags") or "[]")}
        except (ValueError, TypeError):
            have = set()
        scored.append((len(wanted & have), r["id"], r))
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    return [s[2] for s in scored[:limit]]


def get_feedback_stats() -> Dict[str, int]:
    """TA agreement with automatic verdicts (seed rows excluded): a live accuracy signal."""
    init_hitl_db()
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT ta_decision, COUNT(*) AS n FROM hitl_feedback WHERE roll_no != 'seed' GROUP BY ta_decision").fetchall()
        finally:
            conn.close()
    counts = {r["ta_decision"]: r["n"] for r in rows}
    agree, disagree = counts.get("AGREE", 0), counts.get("DISAGREE", 0)
    return {"agree": agree, "disagree": disagree, "total": agree + disagree}
