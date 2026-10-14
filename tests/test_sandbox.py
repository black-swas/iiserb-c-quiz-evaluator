"""Sandbox behaviour with real gcc (Linux only)."""
import os
import sys
import time

import pytest

from app.analyzer.gcc_sandbox import gcc_available, run_gcc_verification
from app.schemas import TestCase as Case
from app.security import harden_process

pytestmark = pytest.mark.skipif(
    not (sys.platform.startswith("linux") and gcc_available()), reason="needs Linux and gcc"
)


def case(inp="", out="x", sample=False):
    return Case(input_data=inp, expected_output=out, is_sample=sample)


ECHO = '#include <stdio.h>\nint main() {\n    int n;\n    scanf("%d", &n);\n    printf("%d\\n", n * 2);\n    return 0;\n}\n'


def test_correct_program_passes_and_counts_sample_and_hidden():
    result = run_gcc_verification(ECHO, [case("5\n", "10", True), case("21\n", "42")])
    assert result.compiled and (result.passed_count, result.total_count) == (2, 2)
    assert (result.sample_passed, result.sample_total, result.hidden_passed, result.hidden_total) == (1, 1, 1, 1)


def test_wrong_output_fails_and_is_described():
    result = run_gcc_verification(ECHO, [case("5\n", "11")])
    assert result.passed_count == 0 and result.case_details[0]["actual"] == "10" and result.case_details[0]["expected"] == "11"


def test_compile_error_is_reported_without_running_anything():
    result = run_gcc_verification("int main() { int x = ; }\n", [case()])
    assert result.compiled is False and "error" in result.compiler_errors.lower()
    assert "submission.c" in result.compiler_errors and "/tmp" not in result.compiler_errors


def test_no_test_cases_means_nothing_was_verified():
    result = run_gcc_verification(ECHO, [])
    assert result.total_count == 0 and result.skipped_reason


def test_infinite_loop_times_out_quickly():
    started = time.time()
    result = run_gcc_verification("int main() { for (;;) {} }\n", [case()], timeout_sec=1.0)
    assert result.timed_out is True and result.passed_count == 0
    assert time.time() - started < 8


def test_program_that_prints_then_sleeps_is_cut_off_at_the_timeout():
    code = '#include <stdio.h>\n#include <unistd.h>\nint main() {\n    printf("hello\\n");\n    fflush(stdout);\n    sleep(20);\n    return 0;\n}\n'
    started = time.time()
    result = run_gcc_verification(code, [case()], timeout_sec=1.0)
    assert result.timed_out is True and time.time() - started < 8     # the old buffered read() would have blocked here


def test_output_flood_is_truncated():
    code = '#include <stdio.h>\nint main() { for (;;) puts("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"); }\n'
    result = run_gcc_verification(code, [case()])
    assert "TRUNCATED" in result.case_details[0]["actual"] and result.passed_count == 0


def test_non_utf8_output_does_not_crash_the_evaluation():
    result = run_gcc_verification('#include <stdio.h>\nint main() { putchar(0xff); putchar(10); return 0; }\n', [case()])
    assert result.compiled and result.passed_count == 0


def test_nonzero_exit_code_fails_the_test():
    result = run_gcc_verification('int main() { return 3; }\n', [case("", "")])
    assert result.passed_count == 0 and result.runtime_error is True


def test_server_environment_is_not_inherited(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-never-reach-student-code")
    code = '#include <stdio.h>\n#include <stdlib.h>\nint main() {\n    const char *k = getenv("ANTHROPIC_API_KEY");\n    printf("%s\\n", k ? k : "unset");\n    return 0;\n}\n'
    result = run_gcc_verification(code, [case("", "unset")])
    assert result.passed_count == 1


def test_server_process_environment_is_unreadable_after_hardening():
    if os.geteuid() == 0:
        pytest.skip("root can read /proc/<pid>/environ regardless")
    if not harden_process():
        pytest.skip("prctl(PR_SET_DUMPABLE) is not permitted in this environment")
    code = r'''#include <stdio.h>
#include <unistd.h>
int main() {
    char path[64];
    snprintf(path, sizeof path, "/proc/%d/environ", (int)getppid());
    FILE *f = fopen(path, "r");
    puts(f ? "readable" : "denied");
    return 0;
}
'''
    result = run_gcc_verification(code, [case("", "denied")])
    assert result.passed_count == 1, result.case_details


def test_runaway_compilation_is_killed_and_leaves_no_compiler_behind():
    levels = 24
    macros = "".join(f"#define M{i} M{i + 1} M{i + 1}\n" for i in range(levels)) + f"#define M{levels} 1\n"
    code = macros + "int v[] = { M0 };\nint main() { return 0; }\n"
    from app.config import settings
    old = settings.compile_timeout_seconds
    settings.compile_timeout_seconds = 3.0
    try:
        started = time.time()
        result = run_gcc_verification(code, [case()])
    finally:
        settings.compile_timeout_seconds = old
    assert result.compiled is False and time.time() - started < 15
    time.sleep(0.5)
    survivors = os.popen("pgrep -f 'cc[1] .*iiserb_c_sandbox' || true").read().strip()
    assert survivors == "", survivors
