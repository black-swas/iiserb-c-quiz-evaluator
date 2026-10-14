"""Lightweight static analysis of a single C submission.

Everything here is *evidence gathering*. Verdicts are decided in triage.py, where hard facts
(compilation, test results) always take precedence over these heuristics.
"""
import re
from typing import Dict, Iterator, List, Optional, Set, Tuple

from app.schemas import QuestionSpec, StaticAnalysisResult

# --------------------------------------------------------------------------- constants
PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|preceding)\s+(?:instructions?|rules?|prompts?|directions?|guidelines?)",
    r"disregard\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|preceding|rubric|grading|instructions?|rules?|directions?|criteria)",
    r"system\s*(?:prompt|instruction|override)",
    r"mark\s+(?:this|my|the)\s+(?:code|submission|answer|solution|program|file|response)\s+(?:as\s+)?(?:clean|green|correct|valid|passing|perfect|safe)",
    r"(?:classify|grade|rate|label|score)\s+(?:this|my|the)\s+(?:code|submission|answer|solution|program)",
    r"as\s+(?:clean|green)\s+and\s+(?:valid|correct)",
    r"you\s+are\s+(?:now\s+)?(?:an?\s+)?(?:ai|llm|language\s+model|assistant|grader|grading|evaluator|judge)",
    r"confidence_score\s*[:=]\s*\d+",
    r"tab_category",
    r"do\s+not\s+flag",
    r"(?:award|give|assign|grant)\s+(?:me\s+|this\s+)?(?:full|maximum|max|100|top)\s*(?:marks?|score|points?|credit)",
    r"new\s+instructions?\s*:",
]

# name -> description. Names the student defines themselves are skipped (e.g. a union-find connect()).
DANGEROUS_CALLS: Dict[str, str] = {
    "system": "Invokes system() shell command",
    "popen": "Invokes popen() process pipe",
    "fork": "Invokes fork() process creation",
    "vfork": "Invokes vfork() process creation",
    "execl": "Invokes exec() family syscall",
    "execlp": "Invokes exec() family syscall",
    "execle": "Invokes exec() family syscall",
    "execv": "Invokes exec() family syscall",
    "execvp": "Invokes exec() family syscall",
    "execve": "Invokes exec() family syscall",
    "socket": "Invokes socket() network call",
    "connect": "Invokes connect() network call",
    "listen": "Invokes listen() network call",
    "getenv": "Reads environment variables via getenv()",
    "secure_getenv": "Reads environment variables via secure_getenv()",
    "setenv": "Mutates environment variables via setenv()",
    "putenv": "Mutates environment variables via putenv()",
    "ptrace": "Invokes ptrace() process inspection",
    "dlopen": "Loads shared libraries via dlopen()",
    "dlsym": "Resolves symbols via dlsym()",
    "syscall": "Invokes raw syscall()",
    "kill": "Invokes kill() on other processes",
}

RESTRICTED_PATH_RE = re.compile(r"^\s*/(?:etc|proc|sys|root|home|app|mnt|dev|var|usr|tmp|run|boot)\b")

C_KEYWORDS = {
    "auto", "break", "case", "char", "const", "continue", "default", "do",
    "double", "else", "enum", "extern", "float", "for", "goto", "if",
    "inline", "int", "long", "register", "restrict", "return", "short",
    "signed", "sizeof", "static", "struct", "switch", "typedef", "union",
    "unsigned", "void", "volatile", "while", "bool", "true", "false",
    "size_t", "FILE", "NULL", "main", "printf", "scanf", "fprintf", "fscanf",
    "sprintf", "sscanf", "getchar", "putchar", "puts", "gets", "fgets",
    "malloc", "calloc", "realloc", "free", "exit", "abs", "labs", "pow",
    "sqrt", "sin", "cos", "tan", "log", "exp", "floor", "ceil", "strlen",
    "strcpy", "strncpy", "strcat", "strcmp", "strncmp", "memcpy", "memset",
    "qsort", "bsearch", "INT_MIN", "INT_MAX", "LONG_MIN", "LONG_MAX",
    "tolower", "toupper", "isalpha", "isdigit", "isalnum", "isspace",
}

_BASE_CASE_NUMBERS = {"-1", "0", "1", "2", "3"}
_CONTROL_RE = re.compile(r"\b(?:if|else|while|for|do|switch|case|default)\b|\?")
_FUNC_RE = re.compile(
    r"\b(?:static\s+|inline\s+|extern\s+|const\s+)*(?:unsigned\s+|signed\s+)?"
    r"(?:long\s+long|long|int|void|float|double|char|short|size_t|bool|_Bool)"
    r"\b\s*\**\s*([A-Za-z_]\w*)\s*\(([^;{}]*)\)\s*([{;])"
)
_DIRECTIVE_RE = re.compile(r"^[ \t]*(?:#|%:)[ \t]*([A-Za-z_]+)([^\n]*)", re.M)
_DEREF_RE = re.compile(r"(?:^|[=(,;{}!&|<>+\-*/%?:\[]|\breturn\b)[ \t]*\*+[ \t]*[A-Za-z_(]", re.M)


# --------------------------------------------------------------------------- lexical helpers
def extract_and_strip_comments(code: str) -> Tuple[str, List[str]]:
    """Remove // and /* */ comments (string/char aware). Line numbering is preserved."""
    comments: List[str] = []
    out: List[str] = []
    i, n = 0, len(code)
    in_str = in_char = False
    while i < n:
        ch = code[i]
        nxt = code[i + 1] if i + 1 < n else ""
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(code[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
        elif in_char:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(code[i + 1])
                i += 2
                continue
            if ch == "'":
                in_char = False
            i += 1
        elif ch == '"':
            in_str = True
            out.append(ch)
            i += 1
        elif ch == "'":
            in_char = True
            out.append(ch)
            i += 1
        elif ch == "/" and nxt == "/":
            end = code.find("\n", i + 2)
            if end == -1:
                end = n
            comments.append(code[i + 2:end].strip())
            i = end
        elif ch == "/" and nxt == "*":
            end = code.find("*/", i + 2)
            if end == -1:
                end = n
            body = code[i + 2:end]
            comments.append(body.strip())
            out.append("\n" * body.count("\n"))
            i = end + 2 if end < n else n
        else:
            out.append(ch)
            i += 1
    return "".join(out), comments


def mask_literals(code: str) -> str:
    """Replace the *contents* of string/char literals by 'x' (length and newlines preserved)."""
    out: List[str] = []
    i, n = 0, len(code)
    while i < n:
        ch = code[i]
        if ch in "\"'":
            quote = ch
            out.append(ch)
            i += 1
            while i < n and code[i] != quote and code[i] != "\n":
                if code[i] == "\\" and i + 1 < n and code[i + 1] != "\n":
                    out.append("xx")
                    i += 2
                else:
                    out.append("x")
                    i += 1
            if i < n and code[i] == quote:
                out.append(quote)
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def string_literals(code: str) -> List[str]:
    lits: List[str] = []
    i, n = 0, len(code)
    while i < n:
        ch = code[i]
        if ch == '"':
            j, buf = i + 1, []
            while j < n and code[j] != '"' and code[j] != "\n":
                if code[j] == "\\" and j + 1 < n:
                    buf.append(code[j:j + 2])
                    j += 2
                else:
                    buf.append(code[j])
                    j += 1
            lits.append("".join(buf))
            i = j + 1
        elif ch == "'":
            j = i + 1
            while j < n and code[j] != "'" and code[j] != "\n":
                j += 2 if code[j] == "\\" else 1
            i = j + 1
        else:
            i += 1
    return lits


def add_line_numbers(code: str) -> str:
    lines = code.splitlines()
    width = max(2, len(str(len(lines))))
    return "\n".join(f"{idx:0{width}d}: {line}" for idx, line in enumerate(lines, start=1))


# --------------------------------------------------------------------------- structure helpers
def _match_brace(code: str, open_idx: int) -> int:
    depth = 0
    for idx in range(open_idx, len(code)):
        if code[idx] == "{":
            depth += 1
        elif code[idx] == "}":
            depth -= 1
            if depth == 0:
                return idx
    return -1


def defined_function_names(masked: str) -> Set[str]:
    """Names of functions the student actually *defines* (a bare prototype does not count,
    otherwise `int system(const char*);` would hide a call to the real system())."""
    return {m.group(1) for m in _FUNC_RE.finditer(masked) if m.group(3) == "{"}


def detect_defined_functions(masked: str) -> List[Tuple[str, str, int, int]]:
    """Returns (name, body, start_line, end_line) for every function *definition*."""
    results = []
    for m in _FUNC_RE.finditer(masked):
        if m.group(3) != "{":
            continue
        name = m.group(1)
        if name in ("if", "for", "while", "switch"):
            continue
        brace_start = m.end() - 1
        end = _match_brace(masked, brace_start)
        if end == -1:
            continue
        results.append((
            name,
            masked[brace_start + 1:end],
            masked[:m.start()].count("\n") + 1,
            masked[:end].count("\n") + 1,
        ))
    return results


def check_is_empty_or_skeleton_stub(masked: str) -> bool:
    """True for empty files and skeleton mains; short real solutions are NOT stubs."""
    code_lines = [ln.strip() for ln in masked.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    code_text = " ".join(code_lines)
    if not code_text.strip():
        return True
    funcs = detect_defined_functions(masked)
    if not funcs:
        return len(code_text) < 15
    for _, body, _, _ in funcs:
        body = re.sub(r"\breturn\s*(?:0|EXIT_SUCCESS)?\s*;", "", body)
        if re.sub(r"[;{}\s]", "", body):
            return False
    return True


def extract_all_loop_blocks(masked: str) -> List[Tuple[str, str, str, int]]:
    """(loop_type, header, body, start_line); headers may contain nested calls like strlen(s)."""
    loops: List[Tuple[str, str, str, int]] = []
    for m in re.finditer(r"\b(for|while)\s*\(", masked):
        paren_start = m.end() - 1
        depth, header_end = 0, -1
        for idx in range(paren_start, len(masked)):
            if masked[idx] == "(":
                depth += 1
            elif masked[idx] == ")":
                depth -= 1
                if depth == 0:
                    header_end = idx
                    break
        if header_end == -1:
            continue
        header = masked[paren_start + 1:header_end]
        rest = masked[header_end + 1:]
        start_line = masked[:m.start()].count("\n") + 1
        brace_m = re.match(r"\s*\{", rest)
        if brace_m:
            brace_start = header_end + 1 + brace_m.end() - 1
            end = _match_brace(masked, brace_start)
            if end != -1:
                loops.append((m.group(1), header, masked[brace_start + 1:end], start_line))
        else:
            semi = rest.find(";")
            if semi != -1:
                loops.append((m.group(1), header, rest[:semi + 1].strip(), start_line))
    for m in re.finditer(r"\bdo\s*\{", masked):
        brace_start = m.end() - 1
        end = _match_brace(masked, brace_start)
        if end != -1:
            loops.append(("do-while", "", masked[brace_start + 1:end], masked[:m.start()].count("\n") + 1))
    return loops


def _context_at(masked: str, pos: int) -> Tuple[str, List[str]]:
    """Text of the current statement up to pos, plus the headers of all enclosing blocks."""
    stack: List[str] = []
    seg_start = 0
    pdepth = 0
    for idx in range(pos):
        ch = masked[idx]
        if ch == "(":
            pdepth += 1
        elif ch == ")":
            pdepth = max(0, pdepth - 1)
        elif pdepth == 0:
            if ch == "{":
                stack.append(masked[seg_start:idx])
                seg_start = idx + 1
            elif ch == "}":
                if stack:
                    stack.pop()
                seg_start = idx + 1
            elif ch == ";":
                seg_start = idx + 1
    return masked[seg_start:pos], stack


def _is_guarded(masked: str, pos: int) -> bool:
    """True if the statement at pos is under an if/else/loop/switch/ternary."""
    segment, headers = _context_at(masked, pos)
    if _CONTROL_RE.search(segment):
        return True
    return any(re.search(r"\b(?:if|else|while|for|do|switch)\b", h) for h in headers)


def _extract_calls(masked: str, original: str, name: str) -> Iterator[Tuple[int, str]]:
    for m in re.finditer(rf"\b{name}\s*\(", masked):
        open_idx = m.end() - 1
        depth, j, closed = 0, open_idx, False
        while j < len(masked):
            if masked[j] == "(":
                depth += 1
            elif masked[j] == ")":
                depth -= 1
                if depth == 0:
                    closed = True
                    break
            j += 1
        if closed:
            yield m.start(), original[open_idx + 1:j]


def _split_args(text: str) -> List[str]:
    args: List[str] = []
    buf: List[str] = []
    depth = 0
    in_str = in_chr = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if in_str or in_chr:
            buf.append(ch)
            if ch == "\\" and i + 1 < n:
                buf.append(text[i + 1])
                i += 2
                continue
            if (in_str and ch == '"') or (in_chr and ch == "'"):
                in_str = in_chr = False
        elif ch == '"':
            in_str = True
            buf.append(ch)
        elif ch == "'":
            in_chr = True
            buf.append(ch)
        elif ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail or args:
        args.append(tail)
    return args


def _looks_like_prompt(fmt: str) -> bool:
    low = fmt.replace("\\n", "").replace("\\t", "").strip().lower()
    return low == "" or low.endswith(":") or "enter" in low or "input" in low or "please" in low


def analyze_output_calls(stripped: str, masked: str) -> Tuple[List[int], Set[str]]:
    """Returns (unguarded constant-output lines, variables that reach the output)."""
    constant_lines: Set[int] = set()
    dynamic_vars: Set[str] = set()
    for name in ("printf", "puts", "putchar"):
        for start, argtext in _extract_calls(masked, stripped, name):
            args = _split_args(argtext)
            if not args:
                continue
            line = stripped.count("\n", 0, start) + 1
            first = args[0]
            first_is_literal = (len(first) >= 2 and first.startswith('"') and first.endswith('"')) or (
                name == "putchar" and first.startswith("'")
            )
            if not first_is_literal:
                dynamic_vars.update(t for t in re.findall(r"[A-Za-z_]\w*", argtext) if t not in C_KEYWORDS)
                continue
            fmt = first[1:-1]
            has_conversion = name == "printf" and "%" in fmt.replace("%%", "")
            rest = args[1:]
            if has_conversion:
                ids = {t for t in re.findall(r"[A-Za-z_]\w*", " ".join(rest)) if t not in C_KEYWORDS}
                all_numeric = bool(rest) and all(re.fullmatch(r"[-+]?\d+(?:\.\d+)?", a) for a in rest)
                if ids:
                    dynamic_vars.update(ids)
                    continue
                if not all_numeric:
                    continue
            elif _looks_like_prompt(fmt):
                continue
            if not _is_guarded(masked, start):
                constant_lines.add(line)
    return sorted(constant_lines), dynamic_vars


# --------------------------------------------------------------------------- security / policy checks
def analyze_includes(stripped: str) -> Tuple[List[str], List[str]]:
    """Returns (security violations, harmless notes) for preprocessor directives."""
    joined = stripped.replace("\\\r\n", "").replace("\\\n", "")
    violations: List[str] = []
    notes: List[str] = []
    for m in _DIRECTIVE_RE.finditer(joined):
        directive = m.group(1).lower()
        rest = m.group(2).strip()
        if directive in {"include_next", "import", "embed"}:
            violations.append(f"Forbidden preprocessor directive #{directive}")
            continue
        if directive != "include":
            continue
        target = re.match(r'^<([^>]*)>|^"([^"]*)"', rest)
        if not target:
            violations.append("Computed #include (macro-expanded path) is not permitted")
            continue
        quoted = target.group(2) is not None
        name = target.group(2) if quoted else target.group(1)
        if name.startswith("/") or ".." in name or (quoted and "/" in name):
            violations.append(f"Forbidden path in #include: {name}")
        elif quoted:
            notes.append(f'Local header "{name}" is not available in single-file submissions')
    return violations, notes


def find_security_violations(stripped: str, masked: str, own_names: Set[str]) -> List[str]:
    found: List[str] = []
    for name, description in DANGEROUS_CALLS.items():
        if name in own_names:
            continue
        direct_call = rf"\b{name}\s*\("
        paren_call = rf"\(\s*{name}\s*\)\s*\("          # (system)("ls")
        pointer_alias = rf"=\s*&?\s*{name}\s*[;,)]"     # fp = system;
        macro_alias = rf"^[ \t]*#[ \t]*define[^\n]*\b{name}\b"
        if (re.search(direct_call, masked) or re.search(paren_call, masked)
                or re.search(pointer_alias, masked) or re.search(macro_alias, masked, re.M)):
            if description not in found:
                found.append(description)
    if re.search(r"\b(?:__asm__|__asm|asm)\b", masked):
        found.append("Inline assembly is not permitted")
    if "##" in masked:
        found.append("Token-pasting preprocessor operator (##) is not permitted")
    for lit in string_literals(stripped):
        if RESTRICTED_PATH_RE.match(lit):
            found.append("References a restricted system path")
            break
    if any("../" in lit for lit in string_literals(stripped)):
        found.append("Path traversal sequence in a string literal")
    if re.search(r'\b(?:fopen|freopen)\s*\([^;]*,\s*"[^"]*[wa+][^"]*"', stripped):
        found.append("Attempts to create or modify files")
    return list(dict.fromkeys(found))


def detect_prompt_injection(stripped: str, comments: List[str]) -> List[str]:
    haystacks = [
        "\n".join(comments),
        "\n".join(string_literals(stripped)),
        re.sub(r"_+", " ", stripped),
    ]
    snippets: List[str] = []
    for pattern in PROMPT_INJECTION_PATTERNS:
        for text in haystacks:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if m:
                snippets.append(m.group(0)[:80])
                break
    return snippets


def _find_spoof_lines(stripped: str, masked: str, question: Optional[QuestionSpec]) -> List[int]:
    if not question:
        return []
    sample_numbers: Set[str] = set()
    sample_words: Set[str] = set()
    for tc in question.test_cases:
        if not tc.is_sample:
            continue
        sample_numbers.update(re.findall(r"-?\d+", tc.input_data))
        sample_words.update(tok for tok in tc.input_data.split() if not re.fullmatch(r"-?\d+", tok))
    if not sample_numbers and not sample_words:
        return []
    lines_s = stripped.splitlines()
    lines_m = masked.splitlines()
    spoof: List[int] = []
    for idx, line_m in enumerate(lines_m):
        if not re.search(r"\bif\s*\(", line_m) or re.search(r"%\s*\d+\s*==", line_m):
            continue
        eq_nums = [n for n in re.findall(r"==\s*(-?\d+)", line_m) if n in sample_numbers]
        # tiny inputs (matrix sizes 2 3) are all "base case" numbers: two of them pinned in one condition is still a lookup
        nums = [n for n in eq_nums if n not in _BASE_CASE_NUMBERS] or (eq_nums if len(eq_nums) >= 2 and "&&" in line_m else [])
        words = [w for w in re.findall(r'strcmp\s*\([^;]*?"([^"]*)"', lines_s[idx]) if w in sample_words]
        if (nums or words) and re.search(r"\b(?:printf|puts)\b", "\n".join(lines_m[idx:idx + 4])):
            spoof.append(idx + 1)
    return spoof


# --------------------------------------------------------------------------- main entry point
def analyze_c_submission(raw_code: str, question: Optional[QuestionSpec] = None) -> StaticAnalysisResult:
    stripped, comments = extract_and_strip_comments(raw_code)
    masked = mask_literals(stripped)
    tags = {t.lower() for t in question.topic_tags} if question else set()

    # ---- integrity / policy
    injection = detect_prompt_injection(stripped, comments)
    include_violations, include_notes = analyze_includes(stripped)
    own_names = defined_function_names(masked)
    security = list(dict.fromkeys(include_violations + find_security_violations(stripped, masked, own_names)))
    forbidden_hits: List[str] = []
    if question:
        for name in question.forbidden_constructs:
            haystack = stripped if re.search(r"[./]", name) else masked
            if name and re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", haystack):
                forbidden_hits.append(name)

    is_stub = check_is_empty_or_skeleton_stub(masked)

    # ---- control flow
    loop_blocks = extract_all_loop_blocks(masked)
    loop_types = sorted({lb[0] for lb in loop_blocks})
    has_loops = bool(loop_blocks)
    recursive_funcs = [
        name for name, body, _, _ in detect_defined_functions(masked)
        if name != "main" and re.search(rf"\b{re.escape(name)}\s*\(", body)
    ]
    has_recursion = bool(recursive_funcs)

    # ---- constructs (string contents are masked so prompts like "n^2?" cannot trigger anything)
    # Only the scanf argument list is removed (one level of nested parens, no braces): the old greedy
    # `[^;]*` ate the whole body when scanf sat in an `if (...) {` condition, hiding bitwise/pointer use.
    code_no_scanf = re.sub(r"\bscanf\s*\([^;{}()]*(?:\([^()]*\)[^;{}()]*)*\)", "", masked)
    has_pointers = bool(
        _DEREF_RE.search(code_no_scanf)
        or re.search(r"\b(?:int|char|long|float|double|void|unsigned|short|size_t)\s*\*+\s*[A-Za-z_]", code_no_scanf)
        or re.search(r"->\s*[A-Za-z_]", code_no_scanf)
    )
    no_logical = re.sub(r"&&|\|\|", "  ", code_no_scanf)
    has_bitwise = bool(
        re.search(r"<<|>>|\^|~|&=|\|=", no_logical)
        or re.search(r"[A-Za-z0-9_\)\]][ \t]*[&|][ \t]*[A-Za-z0-9_\(]", no_logical)
    )
    has_ternary = bool(re.search(r"\?[^?:;{}]*:", masked))
    has_goto = bool(re.search(r"\bgoto\s+[A-Za-z_]", masked))

    # ---- output behaviour
    printf_count = len(re.findall(r"\bprintf\s*\(", masked))
    scanf_count = len(re.findall(r"\bscanf\s*\(", masked))
    constant_lines, dynamic_vars = analyze_output_calls(stripped, masked)
    spoof_lines = _find_spoof_lines(stripped, masked, question)
    dead_loop_suspected = bool(loop_blocks) and bool(constant_lines) and not dynamic_vars
    dead_loop_lines = sorted({lb[3] for lb in loop_blocks}) if dead_loop_suspected else []

    # ---- approach notes (used for the BLUE tab). Ternary operators are deliberately NOT notable.
    notes: List[str] = []
    if has_recursion and "recursion" not in tags:
        suffix = "instead of iterative loops" if not has_loops else "mixed with loops"
        notes.append(f"Recursive formulation ({', '.join(recursive_funcs)}) {suffix}")
    if has_bitwise:
        notes.append("Uses bitwise operations (&, |, ^, <<, >>) for the core logic")
    if has_pointers and "pointers" not in tags:
        notes.append("Uses pointer dereferencing / pointer arithmetic")
    if has_goto:
        notes.append("Uses explicit label/goto control flow")
    if (not has_loops and not has_recursion and not is_stub and not constant_lines and dynamic_vars
            and any("loop" in t for t in tags)):
        notes.append("Closed-form expression without iteration")

    reasons: List[str] = []
    if security:
        reasons.append("Security violation: " + "; ".join(security))
    if injection:
        reasons.append("Text addressed to an automated grader found in comments/strings")
    if forbidden_hits:
        reasons.append("Uses forbidden construct(s): " + ", ".join(forbidden_hits))
    if is_stub:
        reasons.append("Empty file or unattempted main() stub")
    if spoof_lines:
        reasons.append(f"Equality checks against sample inputs followed by output (lines {spoof_lines})")
    if constant_lines and not has_loops and not has_recursion:
        reasons.append(f"Unconditional constant output (lines {constant_lines})")
    if dead_loop_suspected:
        reasons.append(f"Loop(s) at line(s) {dead_loop_lines} never influence the printed output")

    return StaticAnalysisResult(
        line_count=len(stripped.splitlines()),
        has_loops=has_loops,
        loop_types=loop_types,
        has_recursion=has_recursion,
        has_pointers=has_pointers,
        has_bitwise=has_bitwise,
        has_ternary_or_goto=has_ternary or has_goto,
        printf_count=printf_count,
        scanf_count=scanf_count,
        constant_printf_lines=constant_lines,
        sample_spoof_lines=spoof_lines,
        dead_loop_suspected=dead_loop_suspected,
        dead_loop_lines=dead_loop_lines,
        prompt_injection_detected=bool(injection),
        prompt_injection_snippets=injection,
        security_violations=security,
        forbidden_hits=forbidden_hits,
        include_notes=include_notes,
        is_empty_or_stub=is_stub,
        uncommon_construct_notes=notes,
        static_suspicion_reasons=reasons,
    )
