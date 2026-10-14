"""Turn uploaded ZIPs / loose .c files into {student: {question: code}} with strict resource limits.

Student identity and question number are recovered from whatever naming students used:
25104_que1.c, que1_25104.c, Que 1.c, 25104_que1 (1).c, 25104_que1_final.c, answer1.c, 1.c, alice-q2.c,
batch/25104/que1.c, 25104/Q1/main.c, Moodle folders ("Name_123_assignsubmission_file_/que1.c") and
per-student zips (25104.zip containing que1.c). Nothing here raises on bad names: a file that cannot be
placed is skipped with a warning, and every ambiguity (duplicates, conflicting names) is reported.
"""
import codecs
import io
import os
import re
import zipfile
import zlib
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings

GENERIC_DIR_NAMES = {
    "src", "code", "codes", "submission", "submissions", "all", "batch", "class", "quiz", "lab", "labs",
    "master", "files", "file", "student", "students", "output", "input", "__macosx", "answers", "answer",
    "solutions", "solution", "upload", "uploads", "download", "downloads", "desktop", "documents", "final",
    "new folder", "untitled folder", "assignment", "assignments", "homework", "exam", "test", "main",
    "program", "programs", "data", "project", "archive", "extracted", "unzipped", "backup",
}
GENERIC_DIR_RE = re.compile(r"^(?:batch|quiz|lab|set|paper|assignment|assign|hw|homework|exam|test|task|day|week|section|group)\s*[-_]?\s*\d*$", re.IGNORECASE)
# Words that are never a student identifier when they appear where one is expected ("que1_solution.c").
NOISE_WORDS = {
    "solution", "solutions", "answer", "answers", "ans", "main", "code", "program", "prog", "submission",
    "final", "test", "output", "source", "src", "file", "copy", "new", "old", "untitled", "program1",
}
IGNORED_EXTENSIONS = {
    ".out", ".exe", ".o", ".obj", ".dll", ".so", ".dylib", ".png", ".jpg", ".jpeg", ".pdf", ".ds_store", ".git",
    ".gif", ".bmp", ".class", ".pyc", ".a", ".lib", ".bin",
}
NOTABLE_NON_C = {".cpp", ".cc", ".cxx", ".h", ".hpp", ".txt", ".py", ".java", ".doc", ".docx", ".rtf", ".odt", ".md", ".ino"}
UNSUPPORTED_ARCHIVES = (".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".zipx")

Q_WORD = r"(?:questions?|ques|que|qn|qno|q|problems?|prob|programs?|prog|answers?|ans|solutions?|sol|task|exercise|ex|p)"
SEP = r"[\s_\-.]"
_Q_WORD_RE = re.compile(rf"^{Q_WORD}$", re.IGNORECASE)
_ROLL_FIRST = re.compile(rf"^(?P<roll>.+?){SEP}+{Q_WORD}{SEP}*(?P<n>\d{{1,2}})$", re.IGNORECASE)
_QUESTION_FIRST = re.compile(rf"^{Q_WORD}{SEP}*(?P<n>\d{{1,2}})(?:{SEP}+(?P<roll>.+))?$", re.IGNORECASE)
_NUMERIC_TAIL = re.compile(rf"^(?P<roll>[^\s_\-.]+){SEP}(?P<n>\d{{1,2}})$")
_BARE_NUMBER = re.compile(r"^(?P<n>\d{1,2})$")
_FALLBACK_Q = re.compile(rf"(?<![A-Za-z]){Q_WORD}{SEP}*(?P<n>\d{{1,2}})$", re.IGNORECASE)
# "26416_que1 (1)", "que1 - Copy", "que1_final", "que1-v2": download/editor decorations that are not part of the name.
_DECORATION = re.compile(
    rf"(?:{SEP}*\(\d+\)|{SEP}*\[\d+\]"
    rf"|{SEP}+(?:copy(?:{SEP}*\(?\d+\)?)?|final\d*|new|old|fixed|updated|submitted|correct(?:ed)?|done|edited|"
    rf"latest|backup|bak|resubmit(?:ted)?|attempt\d*|rev\d*|v(?:er(?:sion)?)?{SEP}?\d+))+$",
    re.IGNORECASE,
)
_COPY_PREFIX = re.compile(rf"^copy{SEP}+of{SEP}+", re.IGNORECASE)
# "student7_que_paper2" -> "student7"; "26416_quiz3" -> "26416"
ROLL_SUFFIX_RE = re.compile(r"[_\-](?:que|quiz|paper|set|batch|lab)[_\-\w]*$", re.IGNORECASE)
_MOODLE_RE = re.compile(r"_assignsubmission_\w*$", re.IGNORECASE)
_ROLL_OK = re.compile(r'^[^\x00-\x1f/\\:*?"<>|]{1,60}$')     # any script (combining marks are not \w); no path/control characters


class ZipIngestionError(Exception):
    pass


def _is_generic(name: str) -> bool:
    low = name.strip().lower()
    return low in GENERIC_DIR_NAMES or bool(GENERIC_DIR_RE.match(low)) or bool(_Q_WORD_RE.match(low))


def _strip_decorations(stem: str) -> Tuple[str, bool]:
    """(stem without copy/version decorations, whether anything was removed)."""
    original = stem
    stem = _COPY_PREFIX.sub("", stem.strip())
    stem = _DECORATION.sub("", stem).strip(" _-.")
    return (stem or original.strip()), stem != original.strip()


def _clean_roll(name: str) -> str:
    name = _MOODLE_RE.sub("", name.strip())
    name = _DECORATION.sub("", name)
    cleaned = ROLL_SUFFIX_RE.sub("", name)
    cleaned = re.sub(r"\s+", " ", (cleaned or name)).strip(" _-.")
    return cleaned


def _plausible_roll(text: Optional[str]) -> bool:
    if not text:
        return False
    text = text.strip(" _-.")
    return bool(_ROLL_OK.match(text)) and len(text) >= 1 and text.lower() not in NOISE_WORDS and not _is_generic(text)


def _parse_stem(stem: str, allow_bare_number: bool) -> Tuple[Optional[str], Optional[str]]:
    """(roll, question) from a name without extension; either may be None."""
    m = _ROLL_FIRST.match(stem)
    if m and _plausible_roll(m.group("roll")):
        return _clean_roll(m.group("roll")), f"Q{int(m.group('n'))}"
    m = _QUESTION_FIRST.match(stem)
    if m:
        tail = (m.group("roll") or "").strip(" _-.")
        looks_like_id = bool(tail) and _plausible_roll(tail) and (any(c.isdigit() for c in tail) or (" " not in tail and len(tail) >= 3))
        return (_clean_roll(tail) if looks_like_id else None), f"Q{int(m.group('n'))}"
    m = _NUMERIC_TAIL.match(stem)
    if m:
        roll = m.group("roll")
        if _plausible_roll(roll):
            return _clean_roll(roll), f"Q{int(m.group('n'))}"
        return None, f"Q{int(m.group('n'))}"
    if allow_bare_number:
        m = _BARE_NUMBER.match(stem)
        if m:
            return None, f"Q{int(m.group('n'))}"
    m = _FALLBACK_Q.search(stem)
    if m:
        return None, f"Q{int(m.group('n'))}"
    return None, None


def _folder_identity(folder: str) -> Optional[str]:
    folder = _clean_roll(_strip_decorations(folder)[0])
    return folder if _plausible_roll(folder) else None


def parse_roll_and_question(path_hint: str, zip_context: str = "") -> Tuple[Optional[str], Optional[str]]:
    """Student identifier and question id (Q1..Qn) from a path inside an archive."""
    roll, q_id, _ = _parse_path(path_hint, zip_context)
    return roll, q_id


def _parse_path(path_hint: str, zip_context: str = "") -> Tuple[Optional[str], Optional[str], bool]:
    """-> (roll, question, name_was_decorated)."""
    parts = [p for p in path_hint.replace("\\", "/").strip("/").split("/") if p]
    if not parts:
        return None, None, False
    fname, dir_parts = parts[-1], parts[:-1]
    stem = fname[:-2] if fname.lower().endswith(".c") else fname
    stem, decorated = _strip_decorations(stem)

    roll, q_id = _parse_stem(stem, allow_bare_number=True)
    if q_id and roll:
        return roll, q_id, decorated

    if q_id is None:                                   # main.c inside 25104/Q1/, or 25104_que1/main.c
        for folder in reversed(dir_parts):
            f_roll, f_q = _parse_stem(_strip_decorations(folder)[0], allow_bare_number=False)
            if f_q:
                q_id, roll = f_q, f_roll
                break
    if q_id is None:
        return None, None, decorated
    if roll:
        return roll, q_id, decorated

    for folder in reversed(dir_parts):                 # innermost folder first
        found = _folder_identity(folder)
        if found and _parse_stem(_strip_decorations(folder)[0], allow_bare_number=False)[1] is None:
            return found, q_id, decorated
    if zip_context:
        stem_ctx = os.path.splitext(os.path.basename(zip_context))[0]
        found = _folder_identity(stem_ctx)
        if found:
            return found, q_id, decorated
    return None, q_id, decorated


def _folder_roll(path_hint: str) -> Optional[str]:
    """Identity implied by the containing folders only (used to warn about name conflicts)."""
    parts = [p for p in path_hint.replace("\\", "/").strip("/").split("/") if p][:-1]
    for folder in reversed(parts):
        found = _folder_identity(folder)
        if found and _parse_stem(_strip_decorations(folder)[0], allow_bare_number=False)[1] is None:
            return found
    return None


def _decode_source(raw: bytes) -> str:
    """Bytes -> text for UTF-8 (with/without BOM), UTF-16/32 (PowerShell, Notepad) and Windows-1252 files.

    Line endings are normalised to LF and NUL bytes dropped so the analyzers and gcc see clean text.
    """
    if raw.startswith(codecs.BOM_UTF8):
        text = raw[3:].decode("utf-8", errors="replace")
    elif raw.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        text = raw.decode("utf-32", errors="replace")
    elif raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        text = raw.decode("utf-16", errors="replace")
    elif len(raw) >= 4 and raw[:400].count(b"\x00") > len(raw[:400]) // 4:       # UTF-16 without a BOM
        text = raw.decode("utf-16-le" if raw[1:400:2].count(b"\x00") < raw[0:400:2].count(b"\x00") else "utf-16-be",
                          errors="replace")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
    return text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")


def _read_member(zf: zipfile.ZipFile, member: zipfile.ZipInfo, limit: int) -> Optional[bytes]:
    """Read at most `limit` bytes of decompressed data; None if the member is larger (header lies included)."""
    with zf.open(member) as handle:
        data = handle.read(limit + 1)
    return None if len(data) > limit else data


def extract_student_submissions(uploaded_files: List[Tuple[str, bytes]]) -> Dict[str, Any]:
    students: Dict[str, Dict[str, Dict[str, str]]] = {}
    warnings: List[str] = []
    ignored_binaries: List[str] = []
    ignored_other: Dict[str, int] = {}
    canonical: Dict[str, str] = {}                     # casefolded roll -> first spelling seen ("S26416" == "s26416")
    ranks: Dict[Tuple[str, str], Tuple[int, int, Tuple[int, ...], int]] = {}
    counters = {"c_files": 0, "uncompressed": 0, "processed": 0, "unknown": 0, "order": 0}

    total_upload = sum(len(content) for _, content in uploaded_files)
    if total_upload > settings.max_upload_bytes:
        raise ZipIngestionError(
            f"Upload ({total_upload / 1048576:.1f} MB) exceeds the {settings.max_upload_bytes / 1048576:.0f} MB limit."
        )

    def safe_path(path: str) -> bool:
        return not (".." in path.replace("\\", "/").split("/") or path.startswith(("/", "\\")) or re.match(r"^[a-zA-Z]:", path))

    def note_other(ext: str, path_hint: str) -> None:
        lower = path_hint.lower()
        if lower.endswith(".c.txt") or lower.endswith(".c.docx"):
            warnings.append(f"'{path_hint}' looks like a C file saved with an extra extension; skipped (rename it to .c).")
        elif ext in NOTABLE_NON_C:
            ignored_other[ext] = ignored_other.get(ext, 0) + 1

    def register_c_file(path_hint: str, zip_context: str, raw: bytes, mtime: Tuple[int, ...] = ()) -> None:
        path_hint = path_hint.replace("\\", "/")
        basename = os.path.basename(path_hint)
        if (not basename or basename.startswith((".", "~")) or "__MACOSX" in path_hint
                or basename.lower() in ("thumbs.db", "desktop.ini")):
            return
        ext = os.path.splitext(basename.lower())[1]
        if ext in IGNORED_EXTENSIONS or basename.lower() == "a.out":
            ignored_binaries.append(path_hint)
            return
        if ext != ".c":
            note_other(ext, path_hint)
            return

        roll, q_id, decorated = _parse_path(path_hint, zip_context)
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
        else:
            folder_roll = _folder_roll(path_hint)
            if (folder_roll and folder_roll.casefold() != roll.casefold() and "/" in path_hint
                    and any(c.isdigit() for c in roll) and any(c.isdigit() for c in folder_roll)):
                warnings.append(f"'{path_hint}': the file name says student '{roll}' but its folder says '{folder_roll}'; using '{roll}'.")
            roll = canonical.setdefault(roll.casefold(), roll)

        text = _decode_source(raw)
        if not text.strip():
            warnings.append(f"'{path_hint}' is empty.")
        counters["order"] += 1
        # A real file beats an empty one, an exact name beats "(1)"/"copy"/"final" decorations, then the newest wins.
        rank = (1 if text.strip() else 0, 0 if decorated else 1, mtime, counters["order"])
        key = (roll, q_id)
        if key in ranks:
            prior = students[roll][q_id]["filename"]
            if rank > ranks[key]:
                warnings.append(f"Duplicate file for student '{roll}', {q_id}: '{basename}' replaced earlier '{prior}'.")
            else:
                warnings.append(f"Duplicate file for student '{roll}', {q_id}: kept '{prior}', ignored '{basename}'.")
                return
        else:
            counters["c_files"] += 1
        ranks[key] = rank
        students.setdefault(roll, {})[q_id] = {"filename": basename, "code": text}

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
        except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError):
            warnings.append(f"Corrupted ZIP skipped: {zip_name}")
            return
        with zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                name = member.filename.replace("\\", "/")
                if not safe_path(name) or "__MACOSX" in name or os.path.basename(name).startswith("."):
                    continue
                counters["processed"] += 1
                if counters["processed"] > settings.max_file_count:
                    warnings.append(f"Stopped after {settings.max_file_count} archive entries (file-count limit).")
                    return
                lower = name.lower()
                is_zip = lower.endswith(".zip")
                if member.flag_bits & 0x1:
                    warnings.append(f"Skipped '{name}': the archive entry is password-protected.")
                    continue
                if member.compress_size > 0 and member.file_size / member.compress_size > 100:
                    warnings.append(f"Skipped '{name}': suspicious compression ratio.")
                    continue
                if lower.endswith(UNSUPPORTED_ARCHIVES):
                    warnings.append(f"Skipped '{name}': only .zip archives are supported (re-zip it).")
                    continue
                limit = settings.max_upload_bytes if is_zip else settings.max_single_file_bytes
                try:
                    payload = _read_member(zf, member, limit)
                except (RuntimeError, NotImplementedError, zlib.error, EOFError, OSError, zipfile.BadZipFile):
                    warnings.append(f"Skipped '{name}': damaged or unreadable archive entry.")
                    continue
                if payload is None:
                    warnings.append(f"Skipped '{name}': larger than the {limit // 1024} KB per-file limit.")
                    continue
                account(len(payload))
                if is_zip:
                    process_zip(name, payload, os.path.basename(name), depth + 1)
                else:
                    register_c_file(name, context, payload, tuple(member.date_time))

    for fname, content in uploaded_files:
        norm = (fname or "").replace("\\", "/")
        base = os.path.basename(norm)
        if not base or not safe_path(norm):
            warnings.append(f"Rejected unsafe filename: {fname!r}")
            continue
        lower = base.lower()
        if lower.endswith(".zip"):
            process_zip(base, content, base, 1)
        elif lower.endswith(".c"):
            if len(content) > settings.max_single_file_bytes:
                warnings.append(f"Skipped '{base}': larger than the per-file limit.")
                continue
            account(len(content))
            register_c_file(norm, "", content)
        elif lower.endswith(UNSUPPORTED_ARCHIVES):
            warnings.append(f"Skipped '{base}': only .zip archives and .c files are supported (re-zip it).")
        else:
            note_other(os.path.splitext(lower)[1], norm)

    if ignored_other:
        listing = ", ".join(f"{ext} x{n}" for ext, n in sorted(ignored_other.items()))
        warnings.append(f"Ignored non-C files ({listing}); only .c files are evaluated.")

    return {
        "students": students,
        "warnings": warnings,
        "ignored_binaries": ignored_binaries,
        "total_c_files": counters["c_files"],
        "student_count": len(students),
    }
