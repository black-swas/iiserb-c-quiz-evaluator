# C Lab Quiz Evaluator

Triage tool for C programming lab quizzes at **IISER Bhopal (Data Science & Engineering)**.
It compiles and runs every student submission against the question paper's tests inside a resource-limited
sandbox, checks for integrity problems (hard-coded output, copied code, text aimed at the grader), and lets an
optional LLM judge *approach* (standard vs creative). A TA then reviews a short, sorted list instead of every file.

| Tab | Meaning |
|---|---|
| **Needs review** (red) | Does not compile, times out, fails tests, hard-codes output, special-cases sample inputs, uses a forbidden construct, is empty, addresses the grader, or is a *strong* clone of another submission |
| **Creative approach** (blue) | Passes every test and uses a distinctive technique (bit tricks, closed forms, …) worth a five-second look |
| **Clear** (green) | Passes every test, no integrity indicators |
| **Unverified** (gray) | No tests ran (none configured, or the sandbox is unavailable). The tool gives no verdict instead of guessing |

## How a verdict is decided

Hard facts always outrank heuristics, and the LLM can never overturn them. The evaluator systematically performs **7 types of tests** across every submission:

1. **Security violations**  
   Checks for restricted operations such as `system()`, `fork()`, `socket()`, `getenv()`, file-writing operations, inline assembly, and unsafe or forbidden `#include` paths. Programs that trigger these checks are not executed.

2. **Attempts to manipulate the grader**  
   Examines comments and string literals for text directed at an automated grader. Such instructions can trigger a review even if the code compiles.

3. **Empty or incomplete programs**  
   Detects empty implementations or skeleton `main()` functions that do not meaningfully implement the assigned solution.

4. **Compilation and runtime failures**  
   Compiles the submission with GCC and checks for compilation errors, execution timeouts, and failures during testing.

5. **Assignment-specific restrictions**  
   Checks whether the program uses constructs explicitly prohibited by the question paper, through its `forbidden_constructs` configuration.

6. **Functional correctness and hard-coded answers**  
   Runs the configured test cases. It distinguishes programs that pass, ordinary failing solutions, programs that always print the same output, and programs that only handle the sample inputs. It also checks for suspicious decoy loops that never reach the output.

7. **Plagiarism indicators and unusual approaches**  
   Compares submissions for structural similarity, looking for distinctive shared code or near-exact copies across multiple questions. It can flag strong matches for review and identify unusual techniques in otherwise correct solutions.


**Plagiarism.** Programs are canonicalised (identifiers, literals, `for`/`while`, comments, whitespace ignored) and compared.
Two students who both write the textbook loop produce identical token streams, so similarity alone is weak evidence.
A match is **strong** only when the shared structure is distinctive in the class (rare statements, identical non-trivial
comments) or the same pair is a near-exact copy in several questions. Matches inside a large group of identical solutions are
shown as weak context and never create a verdict. Matches are evidence for a human, not proof.

**LLM (optional).** Claude Haiku (default `claude-haiku-5-5`) receives code that already passes all tests and no integrity flag.
It may only move green ↔ blue, add a one-line summary, line hints and an advisory "concern" note. It cannot touch a red or gray
verdict. Student code is wrapped in per-request random delimiters; failures are reported in the UI, never swallowed.

## Deploy on Render (from GitHub)

1. Push this folder to a GitHub repository (the repo root must contain `Dockerfile` and `render.yaml`) or access the live deployment on [Render](https://iiserb-c-quiz-evaluator.onrender.com/).
2. Render dashboard → **New → Blueprint** → select the repo. Render reads `render.yaml` and creates the web service
   (Docker, Singapore, Starter plan, 1 GB persistent disk at `/app/data`).
3. When prompted, set **`ANTHROPIC_API_KEY`** (optional; without it the tool runs fully deterministically).
4. Open the service → **Environment** → copy the generated **`API_AUTH_TOKEN`**. Share it with TAs; the web UI asks for it once per browser session.
5. Open the service URL. The header shows *Sandbox ready* and the AI-review status.

Notes
* One worker process on purpose (jobs and the rate limiter are in memory). Use the Starter plan or larger (512 MB+).
* The disk keeps the TA calibration memory across deploys. Without it the app still works but the memory resets.
* `REQUIRE_AUTH=true` makes the server **fail closed** if no token is configured.
* Behind Render's proxy the real client address is taken from the proxy headers by uvicorn (`--proxy-headers`); the rate limiter never trusts a header sent by the client itself.

## Using it

1. **Question paper**: a JSON file (see [`sample_quiz_data/`](sample_quiz_data/) and the [Question Paper Format Guide](sample_quiz_data/QUESTION_PAPER_FORMAT.md)). Mark the tests printed on the paper with `"is_sample": true`; the rest are hidden tests.
2. **Submissions**: one ZIP per student (`26416.zip` containing `que1.c`…), a master ZIP with a folder per student, or loose files like `26416_que1.c`. Suffixes such as `_que_paper1` are removed from student ids.
3. **Evaluate**. A progress bar follows the server-side job. Results: *Triage* (list + code, tests, evidence), *Class matrix*, *Integrity* (collusion pairs, side-by-side compare), *TA memory*.
4. **Export** a detailed CSV or the matrix CSV, **save the session** as JSON to reopen later, or tick *Hide student ids* for blind marking.

Evidence strength numbers (e.g. 95/100) describe how much hard evidence supports a verdict. They are **not** probabilities.

## Configuration

All settings are environment variables (see `.env.example`). The important ones:

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Enables AI review |
| `ANTHROPIC_MODEL` / `FALLBACK_MODEL` | `claude-haiku-5-5` / `claude-haiku-4-5-20251001` | Model chain |
| `REQUIRE_AUTH` / `API_AUTH_TOKEN` | `false` / – | Access control (`render.yaml` turns it on and generates a token) |
| `GCC_TIMEOUT_SECONDS` | `3.0` | Wall clock per test case |
| `RLIMIT_AS_BYTES` | 128 MB | Address space per student program |
| `SANDBOX_TEST_WORKERS` | `4` | Test cases of one submission run side by side (set `1` on a very small instance) |
| `CLONE_THRESHOLD_PERCENT` | `88` | Minimum similarity to list a pair |
| `CLONE_EXCLUSIVE_MIN_PERCENT` | `20` | Share of shared structure that must be distinctive for a *strong* match (x2.5 when similarity is below 95%) |
| `COLLUSION_MIN_QUESTIONS` | `2` | Near-exact repeats needed to corroborate a pair |
| `MAX_STUDENTS_PER_SESSION` / `MAX_QUESTIONS_PER_PAPER` | `60` / `10` | Limits |

## Security model (read before exposing it)

Student code is untrusted. Defences, in layers:

* Static pre-checks refuse to compile or run files that call `system`, `fork`, `socket`, `getenv`, use inline assembly or `##`,
  `#include` absolute / traversal paths (including digraph and line-spliced spellings), or write files.
* The compiler and the program run with a scrubbed environment, `RLIMIT` CPU / memory / file-size / processes (via `prlimit`),
  their own session and process group (the whole group is killed on timeout or output flood), capped output and no core dumps.
* The server process is **non-dumpable**, so a student program running under the same Unix user cannot read the server's
  environment through `/proc/<pid>/environ`. Secrets are also removed from `os.environ` after start-up.
* The application directory is read-only in the container; only `/app/data` is writable.
* Uploads and ZIPs are size-, ratio-, depth- and count-limited; archive members are read with a hard cap.

**Limits you should know:** there is no network namespace or container-level isolation (a Render web service cannot create
one), so a malicious program that evades the static checks could still make outbound connections or read world-readable files.
That is why the service should stay behind the access token, be used only for your own class's submissions, and hold no
secrets besides the optional API key. For hostile input at scale, run the sandbox in a separate locked-down worker (e.g. gVisor, Firecracker, a dedicated judge service).

## Develop and test

```bash
python -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest                                                # needs gcc on Linux for the sandbox/API tests
uvicorn app.main:app --reload                         # http://localhost:8000
```

The sandbox is POSIX-only; on Windows run it in WSL or Docker (`docker build -t qe . && docker run -p 8000:8000 qe`).
GitHub Actions (`.github/workflows/ci.yml`) runs the tests and builds the image on every push.

## Benchmark Dataset & Sample Question Papers

A complete benchmark test suite modeling **15 distinct student personas** answering **Question Paper 1** (45 C source submissions) is included under [`sample_quiz_data/`](sample_quiz_data/):

* **Question Paper 1**: Available in machine-readable JSON ([`quiz1_paper.json`](sample_quiz_data/quiz1_paper.json)) and formatted exam Markdown ([`quiz1_paper.md`](sample_quiz_data/quiz1_paper.md)).
* **Student Sample Solutions**: 15 student ZIP archives + extracted `.c` sources in [`sample_quiz_data/quiz1_solutions/`](sample_quiz_data/quiz1_solutions/).
* **Question Paper Format Guide**: Full JSON schema and authoring specifications in [`sample_quiz_data/QUESTION_PAPER_FORMAT.md`](sample_quiz_data/QUESTION_PAPER_FORMAT.md).
* **Generation & Persona Mapping**: In-depth ground truth behavior and triage matrix in [`sample_quiz_data/GENERATION_MAPPING.md`](sample_quiz_data/GENERATION_MAPPING.md).
* **Dataset Generation Prompt**: Ready-to-copy Master Prompt for generating new question papers and solution datasets with frontier LLMs in [`sample_quiz_data/DATASET_GENERATION_PROMPT.md`](sample_quiz_data/DATASET_GENERATION_PROMPT.md).

Run the benchmark evaluation with:
```bash
python scripts/evaluate_dataset.py --zips sample_quiz_data/quiz1_solutions --paper 1 --no-llm
```

```
app/
  main.py              API, auth, jobs, static UI
  analyzer/            ingestion, static analysis, sandbox, plagiarism, triage, LLM, pipeline
  database/            TA calibration memory (SQLite)
  static/              index.html, styles.css, app.js (no build step, no CDNs)
sample_quiz_data/      question papers, format guides, persona mapping, and benchmark student solutions
  quiz1_solutions/     15 student solution archives and extracted C source files
  quiz1_paper.json     Question paper 1 (JSON)
  quiz1_paper.md       Question paper 1 (Markdown)
  quiz2_paper.json     Question paper 2 (JSON)
  quiz3_paper.json     Question paper 3 (JSON)
  QUESTION_PAPER_FORMAT.md      Specification for creating question papers
  GENERATION_MAPPING.md         15-persona behavior & triage mapping
  DATASET_GENERATION_PROMPT.md  Master prompt to generate new quiz papers & solutions
scripts/               dataset accuracy benchmarking (`evaluate_dataset.py`)
tests/                 regression tests (one per defect found in earlier versions)
```
