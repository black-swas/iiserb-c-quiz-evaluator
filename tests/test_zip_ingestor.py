"""Archive ingestion: student identity, limits, and the merge/overwrite bugs of the previous version."""
import io
import zipfile

from app.analyzer.zip_ingestor import extract_student_submissions, parse_roll_and_question

C = '#include <stdio.h>\nint main() { int n; scanf("%d", &n); printf("%d\\n", n); return 0; }\n'


def make_zip(files, compress=zipfile.ZIP_DEFLATED):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compress) as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


def students(result):
    return {roll: sorted(qs) for roll, qs in result["students"].items()}


def test_folder_per_student_inside_an_outer_zip_named_with_digits():
    data = make_zip({"25104/que1.c": C, "25105/que1.c": C, "25106/que1.c": C})
    result = extract_student_submissions([("batch2025.zip", data)])
    assert students(result) == {"25104": ["Q1"], "25105": ["Q1"], "25106": ["Q1"]}
    assert result["total_c_files"] == 3


def test_per_student_zip_and_suffix_cleanup():
    uploads = [("student1_que_paper1.zip", make_zip({"que1.c": C, "que2.c": C})), ("26416.zip", make_zip({"que1.c": C}))]
    result = extract_student_submissions(uploads)
    assert students(result) == {"student1": ["Q1", "Q2"], "26416": ["Q1"]}


def test_distinct_unnamed_students_are_not_merged():
    result = extract_student_submissions([("quiz.zip", make_zip({"alice/que1.c": C, "bob/que1.c": C}))])
    assert students(result) == {"alice": ["Q1"], "bob": ["Q1"]}


def test_files_without_any_identity_get_distinct_placeholders_and_a_warning():
    result = extract_student_submissions([("class.zip", make_zip({"que1.c": C, "que2.c": C}))])
    assert len(result["students"]) == 2
    assert any("Could not identify" in w for w in result["warnings"])


def test_duplicate_file_is_reported_not_silently_replaced():
    result = extract_student_submissions([("sub.zip", make_zip({"25104_que1.c": C, "final/25104_que1.c": C + "// newer\n"}))])
    assert students(result) == {"25104": ["Q1"]}
    assert any("Duplicate" in w for w in result["warnings"])


def test_loose_c_files_and_naming_variants():
    uploads = [("25104_que1.c", C.encode()), ("25104_q2.c", C.encode()), ("25104_3.c", C.encode()), ("que_4.c", C.encode())]
    result = extract_student_submissions(uploads)
    assert students(result)["25104"] == ["Q1", "Q2", "Q3"]
    assert any("Could not identify" in w for w in result["warnings"])      # que_4.c has no student id


def test_parse_examples():
    assert parse_roll_and_question("25104_que1.c") == ("25104", "Q1")
    assert parse_roll_and_question("que3.c", "26416.zip") == ("26416", "Q3")
    assert parse_roll_and_question("batch/alice/q2.c") == ("alice", "Q2")
    assert parse_roll_and_question("notes.txt") == (None, None)


def test_questions_outside_the_allowed_range_are_skipped():
    result = extract_student_submissions([("s.zip", make_zip({"que99.c": C, "que0.c": C}))])
    assert result["total_c_files"] == 0 and result["warnings"]


def test_zip_bomb_member_is_skipped():
    bomb = make_zip({"25104_que1.c": "0" * 3_000_000})
    result = extract_student_submissions([("bomb.zip", bomb)])
    assert result["total_c_files"] == 0
    assert any("compression ratio" in w or "per-file limit" in w for w in result["warnings"])


def test_path_traversal_members_are_ignored():
    result = extract_student_submissions([("evil.zip", make_zip({"../25104_que1.c": C, "/abs/25105_que1.c": C}))])
    assert result["total_c_files"] == 0


def test_binaries_are_ignored_but_listed():
    result = extract_student_submissions([("s.zip", make_zip({"25104/a.out": "x", "25104/que1.c": C}))])
    assert result["ignored_binaries"] == ["25104/a.out"] and result["total_c_files"] == 1


def test_corrupt_zip_is_reported():
    result = extract_student_submissions([("broken.zip", b"definitely not a zip")])
    assert result["total_c_files"] == 0 and any("Corrupted" in w for w in result["warnings"])


# ------------------------------------------------------------------ naming scenarios
import pytest


@pytest.mark.parametrize("path,ctx,expected", [
    ("26416_que1.c", "", ("26416", "Q1")),
    ("26416_Que1.C", "", ("26416", "Q1")),
    ("26416_que01.c", "", ("26416", "Q1")),
    ("26416-que1.c", "", ("26416", "Q1")),
    ("26416 que 1.c", "", ("26416", "Q1")),
    ("26416_question_2.c", "", ("26416", "Q2")),
    ("26416_Q3.c", "", ("26416", "Q3")),
    ("26416_answer1.c", "", ("26416", "Q1")),
    ("26416_1.c", "", ("26416", "Q1")),
    ("que1_26416.c", "", ("26416", "Q1")),
    ("Q2 - 26416.c", "", ("26416", "Q2")),
    ("que1.c", "26416.zip", ("26416", "Q1")),
    ("Que 1.c", "26416.zip", ("26416", "Q1")),
    ("que-1.c", "26416.zip", ("26416", "Q1")),
    ("que_1.c", "26416.zip", ("26416", "Q1")),
    ("answer1.c", "26416.zip", ("26416", "Q1")),
    ("solution2.c", "26416.zip", ("26416", "Q2")),
    ("prog3.c", "26416.zip", ("26416", "Q3")),
    ("1.c", "26416.zip", ("26416", "Q1")),
    ("que1_solution.c", "26416.zip", ("26416", "Q1")),
    # duplicate / download / editor decorations
    ("26416_que1 (1).c", "", ("26416", "Q1")),
    ("26416_que1(2).c", "", ("26416", "Q1")),
    ("26416_que1 - Copy.c", "", ("26416", "Q1")),
    ("Copy of 26416_que1.c", "", ("26416", "Q1")),
    ("26416_que1_final.c", "", ("26416", "Q1")),
    ("26416_que1_v2.c", "", ("26416", "Q1")),
    ("26416_que1_final_final (1).c", "", ("26416", "Q1")),
    ("que1 (1).c", "26416.zip", ("26416", "Q1")),
    ("que1.c", "26416 (1).zip", ("26416", "Q1")),
    ("que1.c", "26416_que_paper1.zip", ("26416", "Q1")),
    # folders
    ("26416/que1.c", "", ("26416", "Q1")),
    ("26416 - Rishit Sharma/que1.c", "", ("26416 - Rishit Sharma", "Q1")),
    ("Rishit Sharma_123456_assignsubmission_file_/que2.c", "", ("Rishit Sharma_123456", "Q2")),
    ("Quiz 1/26416/que1.c", "", ("26416", "Q1")),
    ("submissions/batch2025/26416/que1.c", "", ("26416", "Q1")),
    ("26416/Q1/main.c", "", ("26416", "Q1")),
    ("26416/question 2/solution.c", "", ("26416", "Q2")),
    ("26416_que3/main.c", "", ("26416", "Q3")),
    ("26416\\que1.c", "", ("26416", "Q1")),
    ("राहुल_que1.c", "", ("राहुल", "Q1")),
    # not placeable
    ("main.c", "26416.zip", (None, None)),
    ("hello.c", "", (None, None)),
])
def test_naming_scenarios(path, ctx, expected):
    assert parse_roll_and_question(path, ctx) == expected


def test_same_student_with_different_letter_case_is_one_student():
    result = extract_student_submissions([("s.zip", make_zip({"S26416_que1.c": C, "s26416_que2.c": C}))])
    assert students(result) == {"S26416": ["Q1", "Q2"]}


def test_real_file_beats_empty_and_exact_name_beats_copy():
    z = make_zip({"26416_que1.c": "", "26416_que1 (1).c": C, "26416_que2.c": C + "// original\n", "26416_que2 - Copy.c": C + "// copy\n"})
    result = extract_student_submissions([("s.zip", z)])
    assert "(1)" in result["students"]["26416"]["Q1"]["filename"]
    assert result["students"]["26416"]["Q2"]["filename"] == "26416_que2.c"
    assert result["total_c_files"] == 2 and sum("Duplicate" in w for w in result["warnings"]) == 2


def test_conflicting_file_and_folder_identity_is_reported():
    result = extract_student_submissions([("s.zip", make_zip({"27111/26416_que1.c": C}))])
    assert students(result) == {"26416": ["Q1"]}
    assert any("27111" in w and "26416" in w for w in result["warnings"])


def test_utf16_bom_crlf_and_cp1252_sources_are_decoded():
    utf16 = ("#include <stdio.h>\r\nint main(){return 0;}\r\n").encode("utf-16")
    cp = "#include <stdio.h>\n// caf\xe9\nint main(){return 0;}\n".encode("cp1252")
    bom = b"\xef\xbb\xbf" + C.encode()
    result = extract_student_submissions([("a_que1.c", utf16), ("b_que1.c", cp), ("c_que1.c", bom)])
    s = result["students"]
    assert s["a"]["Q1"]["code"].startswith("#include") and "\r" not in s["a"]["Q1"]["code"] and "\x00" not in s["a"]["Q1"]["code"]
    assert "caf\xe9" in s["b"]["Q1"]["code"]
    assert s["c"]["Q1"]["code"].startswith("#include")


def test_non_c_and_unsupported_files_are_reported_not_crashing():
    z = make_zip({"26416/que1.c": C, "26416/notes.txt": "x", "26416/que2.cpp": "x", "26416/que3.c.txt": C, "26416/more.rar": "x"})
    result = extract_student_submissions([("s.zip", z), ("all.7z", b"x"), ("readme.docx", b"x")])
    joined = " ".join(result["warnings"])
    assert students(result) == {"26416": ["Q1"]}
    assert "que3.c.txt" in joined and ".rar" in joined and "all.7z" in joined and ".cpp" in joined


def test_password_protected_or_damaged_entries_do_not_crash():
    good = make_zip({"26416_que1.c": C})
    damaged = bytearray(make_zip({"26417_que1.c": C * 40}, compress=zipfile.ZIP_STORED))
    damaged[60:70] = b"\xff" * 10
    result = extract_student_submissions([("a.zip", good), ("b.zip", bytes(damaged))])
    assert "26416" in result["students"]


def test_zip_inside_zip_inside_zip_is_supported():
    inner = make_zip({"que1.c": C})
    mid = make_zip({"26416.zip": inner})
    outer = make_zip({"all/mid.zip": mid})
    result = extract_student_submissions([("everything.zip", outer)])
    assert students(result) == {"26416": ["Q1"]}


# ------------------------------------------------------------------ identity written inside the file
from app.analyzer.zip_ingestor import _header_identity


@pytest.mark.parametrize("header,expected", [
    ("// Name: Rishit Sharma\n// Roll No: 26416\n", ("26416", "Rishit Sharma")),
    ("// Roll Number : 26416, Name: Rishit Sharma\n", ("26416", "Rishit Sharma")),
    ("/*\n * Name   - Alice Smith\n * Roll no. 25104\n */\n", ("25104", "Alice Smith")),
    ("/* Student ID: 25104 */\n", ("25104", None)),
    ("// Enrollment No: B21CS045\n", ("B21CS045", None)),
    ("// Name: Rishit Sharma Roll No: 26416\n", ("26416", "Rishit Sharma")),
    ("// Alice Smith - 25104\n", ("25104", "Alice Smith")),
    ("// 25104 Alice\n", ("25104", "Alice")),
    ("// 25104\n", ("25104", None)),
    ("#include <stdio.h>\n// Author: Bob\n", (None, "Bob")),
    ("// Name:\n// Roll No:\n", (None, None)),                       # an unfilled template
    ("// Name: Your Name\n// Roll No: XXXXX\n", (None, None)),
    ("// Program name: Count bits\n// Test ID: 12\n", (None, None)),   # not a student identity
    ("int main() { return 0; } // Roll: 99999\n", (None, None)),      # only leading comment lines count
])
def test_identity_inside_the_file(header, expected):
    assert _header_identity(header + "int main() { return 0; }\n") == expected


def test_roll_in_file_is_used_when_the_file_name_has_no_student():
    z = make_zip({"que1.c": "// Roll No: 26416\n" + C, "que2.c": C, "que3.c": "// roll: 26416\n" + C})
    result = extract_student_submissions([("class.zip", z)])
    assert students(result) == {"26416": ["Q1", "Q2", "Q3"]}                # que2.c inherits from its siblings
    assert not any("UNKNOWN" in w for w in result["warnings"])


def test_name_in_file_is_used_when_there_is_no_roll():
    z = make_zip({"que1.c": "// Name: Alice Smith\n" + C, "que2.c": "// Name: alice smith\n" + C})
    assert students(extract_student_submissions([("class.zip", z)])) == {"Alice Smith": ["Q1", "Q2"]}


def test_batch_zip_with_different_students_per_file_is_not_merged():
    outer = make_zip({"alpha.zip": make_zip({"que1.c": "// Roll: 11111\n" + C}), "beta.zip": make_zip({"que1.c": "// Roll: 22222\n" + C})})
    assert students(extract_student_submissions([("class.zip", outer)])) == {"11111": ["Q1"], "22222": ["Q1"]}
    loose = [("que1.c", ("// Roll: 11111\n" + C).encode()), ("que1.c", ("// Roll: 22222\n" + C).encode()), ("que1.c", C.encode())]
    result = extract_student_submissions(loose)
    assert set(result["students"]) == {"11111", "22222", "UNKNOWN_STUDENT_1"}   # the anonymous one is not guessed


def test_file_name_roll_beats_the_roll_in_the_file_and_conflict_is_reported():
    result = extract_student_submissions([("26416_que1.c", ("// Roll: 27111\n" + C).encode())])
    assert students(result) == {"26416": ["Q1"]}
    assert any("27111" in w and "26416" in w for w in result["warnings"])


def test_roll_in_file_beats_a_batch_zip_name_but_not_a_folder():
    z = make_zip({"que1.c": "// Roll: 26416\n" + C})
    result = extract_student_submissions([("CS101_lab.zip", z)])
    assert students(result) == {"26416": ["Q1"]}
    folder = make_zip({"25104/que1.c": "// Roll: 26416\n" + C})
    assert students(extract_student_submissions([("x.zip", folder)])) == {"25104": ["Q1"]}
