"""Turn uploaded ZIPs / loose .c files into {student: {question: code}} with strict resource limits."""
import io
import os
import re
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings

GENERIC_DIR_NAMES = {
    "src", "code", "submission", "submissions", "all", "batch", "class", "quiz", "lab",
    "master", "files", "student", "students", "output", "input", "__macosx",
}
IGNORED_EXTENSIONS = {
    ".out", ".exe", ".o", ".obj", ".dll", ".so", ".dylib", ".png", ".jpg", ".jpeg", ".pdf", ".ds_store", ".git",
}
QUESTION_PART = r"(?:que|ques|question|q|prob|p)[_\-\s]*(\d{1,2})"
# "student7_que_paper2" -> "student7"; "26416_quiz3" -> "26416"
ROLL_SUFFIX_RE = re.compile(r"[_\-](?:que|quiz|paper|set|batch|lab)[_\-\w]*$", re.IGNORECASE)


class ZipIngestionError(Exception):
    pass


def _is_generic(name: str) -> bool:
    low = name.lower()
    return low in GENERIC_DIR_NAMES or bool(re.match(r"^(?:batch|quiz|lab|set)\d*$", low))


def _clean_roll(name: str) -> str:
    cleaned = ROLL_SUFFIX_RE.sub("", name)
    return cleaned or name


def parse_roll_and_question(path_hint: str, zip_context: str = "") -> Tuple[Optional[str], Optional[str]]:
    """Student identifier and question id (Q1..Qn) from a path inside an archive.

    Handles 25104_que1.c, alice-q2.c, batch/25104/que1.c, alice/que1.c and per-student zips
    (25104.zip containing que1.c).
    """
    parts = path_hint.replace("\\", "/").strip("/").split("/")
    fname, dir_parts = parts[-1], parts[:-1]

    m_full = re.match(rf"^([a-zA-Z0-9_-]+?)[_\-\s]+{QUESTION_PART}\.c$", fname, re.IGNORECASE)
    if m_full:
        return m_full.group(1), f"Q{int(m_full.group(2))}"

    m_numeric = re.match(r"^([A-Za-z0-9]+)[-_](\d{1,2})\.c$", fname)          # 25104_1.c
    if m_numeric and m_numeric.group(1).lower() not in {"que", "ques", "question", "q", "prob", "p"}:
        return m_numeric.group(1), f"Q{int(m_numeric.group(2))}"
    m_q = re.search(rf"{QUESTION_PART}\.c$", fname, re.IGNORECASE)
    if not m_q:
        return None, None
    q_id = f"Q{int(m_q.group(1))}"

    for folder in reversed(dir_parts):                       # innermost folder first
        if not _is_generic(folder) and re.match(r"^[a-zA-Z0-9_-]{2,40}$", folder):
            return _clean_roll(folder), q_id

    if zip_context:
        stem = os.path.splitext(os.path.basename(zip_context))[0]
        if not _is_generic(stem) and re.match(r"^[a-zA-Z0-9_-]{2,40}$", stem):
            return _clean_roll(stem), q_id
    return None, q_id


def _read_member(zf: zipfile.ZipFile, member: zipfile.ZipInfo, limit: int) -> Optional[bytes]:
    """Read at most `limit` bytes of decompressed data; None if the member is larger (header lies included)."""
    with zf.open(member) as handle:
        data = handle.read(limit + 1)
    return None if len(data) > limit else data


def extract_student_submissions(uploaded_files: List[Tuple[str, bytes]]) -> Dict[str, Any]:
    students: Dict[str, Dict[str, Dict[str, str]]] = {}
    warnings: List[str] = []
    ignored_binaries: List[str] = []
    counters = {"c_files": 0, "uncompressed": 0, "processed": 0, "unknown": 0}

    total_upload = sum(len(content) for _, content in uploaded_files)
    if total_upload > settings.max_upload_bytes:
        raise ZipIngestionError(
            f"Upload ({total_upload / 1048576:.1f} MB) exceeds the {settings.max_upload_bytes / 1048576:.0f} MB limit."
        )

    def safe_path(path: str) -> bool:
        return not (".." in path.replace("\\", "/").split("/") or path.startswith(("/", "\\")) or re.match(r"^[a-zA-Z]:", path))

    def register_c_file(path_hint: str, zip_context: str, raw: bytes) -> None:
        basename = os.path.basename(path_hint)
        if not basename or basename.startswith(".") or "__MACOSX" in path_hint:
            return
        ext = os.path.splitext(basename.lower())[1]
        if ext in IGNORED_EXTENSIONS or basename.lower() == "a.out":
            ignored_binaries.append(path_hint)
            return
        if ext != ".c":
            return

        roll, q_id = parse_roll_and_question(path_hint, zip_context)
        if not q_id:
            warnings.append(f"Unrecognised C filename '{path_hint}' (expected something like que1.c or 25104_que1.c); skipped.")
            return
        if not 1 <= int(q_id[1:]) <= settings.max_questions_per_paper:
            warnings.append(f"'{path_hint}' refers to {q_id}, outside 1..{settings.max_questions_per_paper}; skipped.")
            return
        if not roll:
            counters["unknown"] += 1
            roll = f"UNKNOWN_STUDENT_{counters['unknown']}"
            warnings.append(f"Could not identify the student for '{path_hint}'; assigned '{roll}'.")

        if q_id in students.get(roll, {}):
            prior = students[roll][q_id]["filename"]
            warnings.append(f"Duplicate file for student '{roll}', {q_id}: '{basename}' replaced earlier '{prior}'.")
        students.setdefault(roll, {})[q_id] = {"filename": basename, "code": raw.decode("utf-8", errors="replace")}
        counters["c_files"] += 1

    def account(size: int) -> None:
        counters["uncompressed"] += size
        if counters["uncompressed"] > settings.max_uncompressed_bytes:
            raise ZipIngestionError(
                f"Decompressed data exceeds {settings.max_uncompressed_bytes / 1048576:.0f} MB (possible zip bomb)."
            )

    def process_zip(zip_name: str, data: bytes, context: str, depth: int) -> None:
        if depth > settings.max_nesting_depth:
            warnings.append(f"Skipped nested archive '{zip_name}' (deeper than {settings.max_nesting_depth} levels).")
            return
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            warnings.append(f"Corrupted ZIP skipped: {zip_name}")
            return
        with zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                name = member.filename
                if not safe_path(name) or "__MACOSX" in name or os.path.basename(name).startswith("."):
                    continue
                counters["processed"] += 1
                if counters["processed"] > settings.max_file_count:
                    warnings.append(f"Stopped after {settings.max_file_count} archive entries (file-count limit).")
                    return
                is_zip = name.lower().endswith(".zip")
                if member.compress_size > 0 and member.file_size / member.compress_size > 100:
                    warnings.append(f"Skipped '{name}': suspicious compression ratio.")
                    continue
                limit = settings.max_upload_bytes if is_zip else settings.max_single_file_bytes
                payload = _read_member(zf, member, limit)
                if payload is None:
                    warnings.append(f"Skipped '{name}': larger than the {limit // 1024} KB per-file limit.")
                    continue
                account(len(payload))
                if is_zip:
                    process_zip(name, payload, os.path.basename(name), depth + 1)
                else:
                    register_c_file(name, context, payload)

    for fname, content in uploaded_files:
        base = os.path.basename(fname or "")
        if not base or not safe_path(fname or base):
            warnings.append(f"Rejected unsafe filename: {fname!r}")
            continue
        if base.lower().endswith(".zip"):
            process_zip(base, content, base, 1)
        elif base.lower().endswith(".c"):
            if len(content) > settings.max_single_file_bytes:
                warnings.append(f"Skipped '{base}': larger than the per-file limit.")
                continue
            account(len(content))
            register_c_file(base, "", content)

    return {
        "students": students,
        "warnings": warnings,
        "ignored_binaries": ignored_binaries,
        "total_c_files": counters["c_files"],
        "student_count": len(students),
    }
