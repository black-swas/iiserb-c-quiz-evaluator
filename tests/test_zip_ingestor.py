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
