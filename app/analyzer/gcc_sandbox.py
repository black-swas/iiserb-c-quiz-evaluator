"""Compile and run one student submission under OS-level limits (POSIX).

Isolation model (no root, no containers needed, so it works inside a Render web service):
  * scrubbed environment for compiler and program (no secrets are ever passed to children)
  * RLIMIT_CPU / AS / FSIZE / CORE / NPROC on the program, CPU / AS / FSIZE on the compiler
  * own session + process group; the whole group is SIGKILLed on exit, timeout or output flood
  * stdout is read incrementally and capped, so an endless puts() loop cannot exhaust memory
  * the server process itself is non-dumpable (see app.security.harden_process), so a student
    program cannot read the server's environment through /proc/<ppid>/environ
Static pre-checks (c_static_analyzer) refuse to run submissions that try obvious escapes.
"""
import math
import os
import re
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
from typing import Callable, List, Optional, Tuple

try:
    import resource
except ImportError:  # pragma: no cover - only on non-POSIX development machines
    resource = None  # type: ignore[assignment]

from app.config import settings
from app.schemas import GccTestResult, TestCase

SAFE_ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"}
MAX_STDIN_BYTES = 49152  # stays below the 64 KiB pipe buffer so writing never blocks
_PATH_RE = re.compile(r"(?<![\w\"'.])(?:/[\w.\-]+){2,}")


def gcc_available() -> bool:
    return shutil.which("gcc") is not None


def normalize_output(text: str) -> str:
    return "\n".join(line.strip() for line in text.strip().splitlines() if line.strip())


def sanitize_compiler_errors(stderr_text: str, tmpdir: str) -> str:
    """Strip sandbox paths and cap the length. (Dangerous #includes are rejected before compiling.)"""
    if not stderr_text:
        return ""
    cleaned = stderr_text.replace(tmpdir + "/", "").replace(tmpdir, "")
    return "\n".join(_PATH_RE.sub("[path]", line) for line in cleaned.splitlines()[:30])


def _with_limits(
    cmd: List[str], cpu: int, mem: int, fsize: int, nproc: Optional[int] = None
) -> Tuple[List[str], Optional[Callable[[], None]]]:
    """Returns (argv, preexec_fn) applying resource limits to `cmd`.

    Prefers the util-linux `prlimit` wrapper: it needs no Python code between fork and exec, so it
    is safe in a multi-threaded server. Falls back to a preexec_fn when prlimit is unavailable.
    """
    exe = shutil.which("prlimit")
    if exe:
        argv = [exe, f"--cpu={cpu}", f"--as={mem}", f"--fsize={fsize}", "--core=0"]
        if nproc is not None:
            argv.append(f"--nproc={nproc}")
        return argv + ["--"] + cmd, None
    if resource is None:  # pragma: no cover - development machines without POSIX limits
        return cmd, None

    def _preexec() -> None:
        pairs = [(resource.RLIMIT_CPU, cpu), (resource.RLIMIT_AS, mem), (resource.RLIMIT_FSIZE, fsize), (resource.RLIMIT_CORE, 0)]
        if nproc is not None:
            pairs.append((resource.RLIMIT_NPROC, nproc))
        for res, value in pairs:
            try:
                resource.setrlimit(res, (value, value))
            except (ValueError, OSError):
                pass

    return cmd, _preexec


def _kill_group(proc: subprocess.Popen) -> None:
    """SIGKILL the whole process group (the child is its own session leader, so pgid == pid)."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def _compile(src_path: str, bin_path: str, tmpdir: str) -> Tuple[int, str, bool]:
    """Returns (returncode, stderr, timed_out)."""
    gcc_cmd = ["gcc", "-O0", "-Wall", "-Wextra", "-fstack-protector-strong", src_path, "-o", bin_path, "-lm"]
    cpu = int(math.ceil(settings.compile_timeout_seconds)) + 2
    argv, preexec = _with_limits(gcc_cmd, cpu, 1536 * 1024 * 1024, 64 * 1024 * 1024)
    proc = subprocess.Popen(
        argv,
        cwd=tmpdir,
        env=dict(SAFE_ENV, TMPDIR=tmpdir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=preexec,
        start_new_session=True,
    )
    try:
        _, err = proc.communicate(timeout=settings.compile_timeout_seconds)
    except subprocess.TimeoutExpired:
        _kill_group(proc)   # kills gcc AND its cc1/as/ld children (same process group)
        try:
            proc.communicate(timeout=2)
        except Exception:
            pass
        return -1, "", True
    return proc.returncode, err.decode("utf-8", errors="replace"), False


def execute_binary_capped(
    bin_path: str,
    input_data: str,
    timeout_sec: float,
    tmpdir: str,
    max_output_bytes: int = 65536,
) -> Tuple[str, str, int, bool, bool]:
    """Run the compiled program once. Returns (stdout, stderr, returncode, timed_out, truncated)."""
    cpu = max(settings.rlimit_cpu_seconds, int(math.ceil(timeout_sec)) + 1)  # wall clock must fire first
    argv, preexec = _with_limits(
        [bin_path], cpu, settings.rlimit_as_bytes, max(0, settings.rlimit_fsize_bytes), max(1, settings.rlimit_nproc)
    )
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=tmpdir,
        env=dict(SAFE_ENV, HOME=tmpdir, TMPDIR=tmpdir),
        bufsize=0,
        preexec_fn=preexec,
        start_new_session=True,
    )

    data = input_data.encode("utf-8", errors="replace")[:MAX_STDIN_BYTES]
    try:
        view = memoryview(data)
        while view:
            written = proc.stdin.write(view)
            if not written:
                break
            view = view[written:]
    except OSError:
        pass  # program exited before reading everything
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass

    out_chunks: List[bytes] = []
    err_chunks: List[bytes] = []
    out_len = err_len = 0
    truncated = timed_out = False
    deadline = time.monotonic() + timeout_sec

    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ, "out")
    sel.register(proc.stderr, selectors.EVENT_READ, "err")
    try:
        while sel.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            for key, _ in sel.select(timeout=min(remaining, 0.1)):
                chunk = os.read(key.fd, 4096)  # returns whatever is available; never blocks after select()
                if not chunk:
                    sel.unregister(key.fileobj)
                    continue
                if key.data == "out":
                    out_len += len(chunk)
                    if out_len > max_output_bytes:
                        truncated = True
                        break
                    out_chunks.append(chunk)
                elif err_len < 16384:
                    err_chunks.append(chunk)
                    err_len += len(chunk)
            if truncated:
                break
    finally:
        _kill_group(proc)
        sel.close()
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except OSError:
                pass

    stdout_text = b"".join(out_chunks).decode("utf-8", errors="replace")
    stderr_text = b"".join(err_chunks).decode("utf-8", errors="replace")
    returncode = proc.returncode if proc.returncode is not None else -1
    return stdout_text, stderr_text, returncode, timed_out, truncated


def run_gcc_verification(
    raw_code: str,
    test_cases: List[TestCase],
    timeout_sec: Optional[float] = None,
) -> GccTestResult:
    timeout_sec = timeout_sec or settings.test_timeout_seconds
    sample_total = sum(1 for t in test_cases if t.is_sample)
    hidden_total = len(test_cases) - sample_total
    base = dict(total_count=len(test_cases), sample_total=sample_total, hidden_total=hidden_total)

    if not test_cases:
        return GccTestResult(compiled=True, skipped_reason="No test cases configured", **base)

    with tempfile.TemporaryDirectory(prefix="iiserb_c_sandbox_") as tmpdir:
        src_path = os.path.join(tmpdir, "submission.c")
        bin_path = os.path.join(tmpdir, "submission.out")
        with open(src_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(raw_code)

        try:
            returncode, stderr, compile_timed_out = _compile(src_path, bin_path, tmpdir)
        except OSError as exc:
            return GccTestResult(compiled=False, compiler_errors=f"Compiler invocation error: {exc}", **base)

        if compile_timed_out:
            return GccTestResult(
                compiled=False,
                compiler_errors=f"Compilation timed out (> {settings.compile_timeout_seconds:g}s).",
                **base,
            )
        if returncode != 0:
            return GccTestResult(
                compiled=False,
                compiler_errors=sanitize_compiler_errors(stderr, tmpdir)[:1500] or "Compilation failed.",
                **base,
            )

        warnings = sanitize_compiler_errors(stderr, tmpdir)[:600] if stderr else ""
        passed = sample_passed = hidden_passed = 0
        timed_out_any = runtime_err_any = False
        details = []

        for idx, tc in enumerate(test_cases, start=1):
            out, _err, rc, timed_out, truncated = execute_binary_capped(
                bin_path, tc.input_data, timeout_sec, tmpdir, settings.max_output_bytes
            )
            actual = normalize_output(out[:2048])
            expected = normalize_output(tc.expected_output)
            ok = (not timed_out) and (not truncated) and rc == 0 and actual == expected

            if timed_out:
                timed_out_any = True
                actual = f"[TIMEOUT > {timeout_sec:g}s]"
            elif truncated:
                actual = "[OUTPUT TRUNCATED: > 64 KB]"
            elif rc != 0:
                runtime_err_any = True

            if ok:
                passed += 1
                if tc.is_sample:
                    sample_passed += 1
                else:
                    hidden_passed += 1
            details.append({
                "case_index": idx,
                "is_sample": tc.is_sample,
                "passed": ok,
                "input": tc.input_data[:200],
                "expected": expected[:160],
                "actual": actual[:160],
                "returncode": rc,
            })

        return GccTestResult(
            compiled=True,
            compiler_warnings=warnings,
            passed_count=passed,
            sample_passed=sample_passed,
            hidden_passed=hidden_passed,
            timed_out=timed_out_any,
            runtime_error=runtime_err_any,
            case_details=details,
            **base,
        )
