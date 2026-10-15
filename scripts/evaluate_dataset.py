"""Score the evaluator on the designed 15-persona dataset with ONE compact report (cheap on tokens).

Usage (from the repo root, Linux/WSL because the sandbox needs gcc):
    python scripts/evaluate_dataset.py --zips "/path/to/iice 2" --paper 1            # deterministic + LLM if a key is set
    python scripts/evaluate_dataset.py --zips "/path/to/iice 2" --paper 1 --no-llm   # no API calls

Reads studentN_que_paperP.zip from --zips and sample_quiz_data/quizP_paper.json. The API key is read from the
ANTHROPIC_API_KEY environment variable only; it is never printed or written anywhere.
"""
import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Persona design: which technique each creative student used per question (T = distinctive, m = mild, F = plain).
TECH = {
    1: {2: "TTF", 3: "TmT", 4: "TTF", 5: "TTF", 6: "TTm"},
    2: {2: "FTT", 3: "FFT", 4: "FTF", 5: "TTT", 6: "mFm"},
    3: {2: "TTF", 3: "mFT", 4: "mTF", 5: "FTT", 6: "mmF"},
}
RED_TYPES = {9: {"PLAGIARISM_CLONE"}, 10: {"SAMPLE_INPUT_SPOOFING"}, 11: {"HARDCODED_PRINTF"}, 12: {"DEAD_CODE_PADDING"},
             13: {"PROMPT_INJECTION"}, 14: {"BROKEN_LOGIC"}}


def expected(paper, student, q):
    """-> (accepted tabs, accepted cheat types)"""
    if student == 15:
        return {"RED"}, {1: {"TIMEOUT"}, 2: {"COMPILE_ERROR"}, 3: {"UNSUBMITTED_OR_STUB"}}[paper]
    if student in RED_TYPES:
        return {"RED"}, RED_TYPES[student]
    if student in (1, 7):
        return {"GREEN"}, {"NONE"}
    if student == 8:
        return {"GREEN", "RED"}, {"NONE", "PLAGIARISM_CLONE"}      # original of the copied pair: either is defensible
    c = TECH[paper][student][q - 1]
    return ({"BLUE"} if c == "T" else {"GREEN", "BLUE"} if c == "m" else {"GREEN"}), {"NONE"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zips", required=True, help="folder containing studentN_que_paperP.zip")
    ap.add_argument("--paper", type=int, default=1, choices=(1, 2, 3))
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--max-wrong", type=int, default=25)
    args = ap.parse_args()

    os.environ["SQLITE_DB_PATH"] = str(Path(tempfile.mkdtemp(prefix="qe_ds_")) / "h.db")
    if args.no_llm:
        os.environ["LLM_ENABLED"] = "false"

    from app.analyzer.pipeline import run_full_quiz_evaluation
    from app.analyzer.zip_ingestor import extract_student_submissions
    from app.config import settings
    from app.schemas import QuizPaper

    paper_json = json.loads((ROOT / "sample_quiz_data" / f"quiz{args.paper}_paper.json").read_text(encoding="utf-8"))
    zip_dir = Path(args.zips)
    zips = sorted(zip_dir.glob(f"student*_que_paper{args.paper}.zip"))
    if not zips:
        zips = sorted((zip_dir / f"que{args.paper}_solutions").glob(f"student*_que_paper{args.paper}.zip"))
    if not zips:
        zips = sorted((zip_dir / f"quiz{args.paper}_solutions").glob(f"student*_que_paper{args.paper}.zip"))
    if not zips:
        zips = sorted(zip_dir.rglob(f"student*_que_paper{args.paper}.zip"))
    uploads = [(p.name, p.read_bytes()) for p in zips]
    if not uploads:
        print(f"no student zips found in {args.zips}"); return 2
    extracted = extract_student_submissions(uploads)
    report = asyncio.run(run_full_quiz_evaluation(QuizPaper(**paper_json), extracted))

    rows = []
    for qid, evs in report["evaluations_by_question"].items():
        for e in evs:
            s = int(re.match(r"student(\d+)", e["roll_no"]).group(1))
            tabs, cheats = expected(args.paper, s, int(qid[1:]))
            rows.append(dict(key=f"P{args.paper}-S{s}-{qid}", s=s, tab=e["tab_category"], cheat=e["cheat_type"], badge=e["verdict_badge"],
                             tabs=tabs, cheats=cheats, tests=(e.get("gcc_result") or {}).get("passed_count"), total=(e.get("gcc_result") or {}).get("total_count")))

    red_expected = [r for r in rows if r["tabs"] == {"RED"}]
    honest = [r for r in rows if "RED" not in r["tabs"]]
    caught = [r for r in red_expected if r["tab"] == "RED"]
    false_red = [r for r in honest if r["tab"] == "RED"]
    tab_ok = [r for r in rows if r["tab"] in r["tabs"]]
    type_ok = [r for r in caught if r["cheat"] in r["cheats"]]
    llm = report["engine"]["llm"]

    print(f"paper {args.paper} | {report['student_count']} students | {len(rows)} files | {report['elapsed_seconds']}s | sandbox={report['engine']['sandbox']}")
    print(f"RED recall {len(caught)}/{len(red_expected)} | honest files flagged RED {len(false_red)}/{len(honest)} | "
          f"tab accuracy {len(tab_ok)}/{len(rows)} | cheat-type accuracy {len(type_ok)}/{len(caught)}")
    print(f"expected->got tab counts: {dict(Counter((('/'.join(sorted(r['tabs']))), r['tab']) for r in rows))}")
    print(f"collusion pairs: {[(c['roll_a'], c['roll_b'], c['shared_questions']) for c in report['collusion_pairs']]}")
    print(f"LLM enabled={llm['enabled']} model={settings.primary_model} calls={llm['calls']} ok={llm['ok_calls']} failed={llm['failed_calls']} "
          f"reviewed={llm['submissions_reviewed']} tokens in/out={llm['input_tokens']}/{llm['output_tokens']} errors={llm['errors'][:2]} skipped={llm['skipped_reason']!r}")
    wrong = [r for r in rows if r["tab"] not in r["tabs"] or (r["tabs"] == {"RED"} and r["cheat"] not in r["cheats"])]
    print(f"--- {len(wrong)} mismatches (showing {min(len(wrong), args.max_wrong)}): key | expected tab/cheat | got | badge | tests")
    for r in wrong[:args.max_wrong]:
        print(f"{r['key']} | {'/'.join(sorted(r['tabs']))}/{'|'.join(sorted(r['cheats']))} | {r['tab']}/{r['cheat']} | {r['badge'][:34]} | {r['tests']}/{r['total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
