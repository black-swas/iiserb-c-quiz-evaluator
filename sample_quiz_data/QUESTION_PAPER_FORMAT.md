# Question Paper Format & Authoring Guide

This guide describes the official question paper specification for the **IISER Bhopal DSE C-Lab Quiz Evaluator**. It defines both the machine-readable **JSON schema** (used by the GCC sandbox, static analyzer, and triage pipeline) and the human-readable **Markdown format** (used for student handouts and documentation).

---

## 1. Architecture Overview

In the evaluation workflow, a Question Paper serves three critical functions:
1. **Compilation & Execution Ground Truth:** Specifies the standard input (`stdin`) and expected output (`stdout`) for every test case.
2. **Cheat Detection Baseline:** Differentiates visible **Sample Test Cases** (`"is_sample": true`) from unseen **Hidden Test Cases** (`"is_sample": false`), enabling automated detection of hardcoded condition trees (Sample Input Spoofing).
3. **AST Static Policy Enforcement:** Enforces pedagogical constraints by listing `forbidden_constructs` (e.g., forbidding `goto`, `qsort`, or library shortcuts).

### The 7 Types of Tests Performed
Every submitted C program is subjected to seven layers of evaluation:
1. **Security violations:** Checks for restricted operations such as `system()`, `fork()`, `socket()`, `getenv()`, file-writing operations, inline assembly, and unsafe or forbidden `#include` paths. Programs that trigger these checks are not executed.
2. **Attempts to manipulate the grader:** Examines comments and string literals for text directed at an automated grader. Such instructions can trigger a review even if the code compiles.
3. **Empty or incomplete programs:** Detects empty implementations or skeleton `main()` functions that do not meaningfully implement the assigned solution.
4. **Compilation and runtime failures:** Compiles the submission with GCC and checks for compilation errors, execution timeouts, and failures during testing.
5. **Assignment-specific restrictions:** Checks whether the program uses constructs explicitly prohibited by the question paper, through its `forbidden_constructs` configuration.
6. **Functional correctness and hard-coded answers:** Runs the configured test cases. It distinguishes programs that pass, ordinary failing solutions, programs that always print the same output, and programs that only handle the sample inputs. It also checks for suspicious decoy loops that never reach the output.
7. **Plagiarism indicators and unusual approaches:** Compares submissions for structural similarity, looking for distinctive shared code or near-exact copies across multiple questions. It can flag strong matches for review and identify unusual techniques in otherwise correct solutions.

---

## 2. JSON Schema Specification

The evaluator accepts either a root JSON object conforming to `QuizPaper`, or a bare array `[ ... ]` of `QuestionSpec` objects.

### Pydantic Schema Definition
```python
class TestCase(BaseModel):
    input_data: str = Field(default="", max_length=65536)
    expected_output: str = Field(..., max_length=65536)
    is_sample: bool = Field(default=False)

class QuestionSpec(BaseModel):
    question_id: str = Field(..., pattern=r"^Q\d{1,2}$")  # e.g., "Q1", "Q2", "Q3"
    title: str = Field(..., min_length=1, max_length=200)
    problem_statement: str = Field(..., max_length=20000)
    topic_tags: List[str] = Field(default_factory=list, max_length=20)
    expected_complexity: str = Field(default="O(N)", max_length=80)
    forbidden_constructs: List[str] = Field(default_factory=list, max_length=20)
    test_cases: List[TestCase] = Field(default_factory=list, max_length=60)

class QuizPaper(BaseModel):
    course_code: str = Field(default="DSE-101", max_length=40)
    quiz_title: str = Field(default="C Programming Lab Quiz", max_length=200)
    questions: List[QuestionSpec]
```

### Complete JSON Schema Example
```json
{
  "course_code": "DSE-101",
  "quiz_title": "Quiz 1: Number Theory, Sequences & Bitwise Logic",
  "questions": [
    {
      "question_id": "Q1",
      "title": "Count Set Bits (Hamming Weight)",
      "problem_statement": "Write a C program to count the number of set bits (1s) in the binary representation of a given non-negative integer N.\n\n### Input Format\nA single non-negative integer `N` (0 <= N <= 2,000,000,000).\n\n### Output Format\nPrint the count of set bits followed by a newline.",
      "topic_tags": [
        "bitwise",
        "loops",
        "number-theory"
      ],
      "expected_complexity": "O(log N)",
      "forbidden_constructs": [
        "__builtin_popcount"
      ],
      "test_cases": [
        {
          "input_data": "0\n",
          "expected_output": "0",
          "is_sample": true
        },
        {
          "input_data": "7\n",
          "expected_output": "3",
          "is_sample": true
        },
        {
          "input_data": "16\n",
          "expected_output": "1",
          "is_sample": true
        },
        {
          "input_data": "1023\n",
          "expected_output": "10",
          "is_sample": false
        },
        {
          "input_data": "1048576\n",
          "expected_output": "1",
          "is_sample": false
        },
        {
          "input_data": "123456789\n",
          "expected_output": "16",
          "is_sample": false
        },
        {
          "input_data": "2147483647\n",
          "expected_output": "31",
          "is_sample": false
        }
      ]
    }
  ]
}
```

---

## 3. Field-by-Field Reference

### Root Level (`QuizPaper`)
| Field | Type | Required | Description |
|---|---|---|---|
| `course_code` | `string` | Optional (default `"DSE-101"`) | Official course designation code. |
| `quiz_title` | `string` | Optional (default `"C Programming Lab Quiz"`) | Human-readable title displayed in the evaluator header and export reports. |
| `questions` | `array` | **Required** | List of questions (minimum 1, maximum configurable via `MAX_QUESTIONS_PER_PAPER`, default 10). |

---

### Question Level (`QuestionSpec`)
| Field | Type | Pattern / Constraints | Description |
|---|---|---|---|
| `question_id` | `string` | `^Q\d{1,2}$` | **Must match regex pattern** (e.g., `"Q1"`, `"Q2"`, `"Q3"`). Corresponds to student file naming (`que1.c` $\to$ `Q1`). Must be unique within the paper. |
| `title` | `string` | 1–200 characters | Short, descriptive title of the programming problem. |
| `problem_statement` | `string` | Max 20,000 characters | Full problem statement in Markdown. Include clear Input Format, Output Format, and Constraints. |
| `topic_tags` | `string[]` | Max 20 elements | Categorical tags used by the LLM advisor to evaluate stylistic appropriateness (e.g., `["bitwise", "loops"]`). |
| `expected_complexity` | `string` | Max 80 characters | Target algorithmic complexity (e.g., `"O(N)"`, `"O(log N)"`, `"O(1)"`). |
| `forbidden_constructs` | `string[]` | Max 20 elements | C keywords, built-ins, or library functions banned for this specific problem (e.g., `["goto", "__builtin_popcount", "qsort"]`). Violations immediately fail triage with `RULE_VIOLATION`. |
| `test_cases` | `TestCase[]` | Max 60 test cases | Test suite containing both sample and hidden test cases. |

---

### Test Case Level (`TestCase`)
| Field | Type | Constraints | Description |
|---|---|---|---|
| `input_data` | `string` | Max 65,536 bytes | Raw text fed into program's `stdin`. **Always terminate inputs with a newline character (`\n`)** so standard `scanf` or `fgets` calls do not hang. |
| `expected_output` | `string` | Max 65,536 bytes | Expected text emitted on `stdout`. Trailing whitespace and carriage returns (`\r\n` vs `\n`) are automatically normalized by the sandbox comparator. |
| `is_sample` | `boolean` | `true` or `false` | **Critical flag.** When `true`, indicates the test case was published on the student's question sheet. When `false`, indicates an unseen hidden test case. |

---

## 4. Designing a High-Quality Test Suite

The automated triage engine uses behavioral telemetry from test runs to classify submissions. Follow these best practices to ensure accurate grading:

### 1. The 3:4 or 2:5 Sample-to-Hidden Ratio
- Provide **2 to 3 visible sample cases** (`"is_sample": true`) to help students verify their I/O format during the exam.
- Provide **4 to 7 hidden test cases** (`"is_sample": false`) covering diverse ranges.
- **Why this matters:** If a student hardcodes `if (n == 7) printf("3\n");`, they will pass 100% of visible sample cases (3/3) but pass 0% of hidden cases (0/4). The triage engine detects this discrepancy and marks the submission as `SAMPLE_INPUT_SPOOFING` in the **🔴 RED tab**.

### 2. Edge Case Coverage
Always include:
- **Boundary minimums:** $0$, $1$, negative values (if allowed), or empty sequences.
- **Boundary maximums:** Values testing upper bounds (e.g., $N = 2 \times 10^9$ for 32-bit unsigned integers; $N = 10^6$ for $O(N)$ vs $O(1)$ arithmetic).
- **Type overflow vectors:** Values where the answer fits only in 64-bit `long long` (e.g., $\sum_{i=1}^{10^6} i \approx 5 \times 10^{11} > 2^{31}-1$). This catches students who used standard `int`.

### 3. Whitespace & Formatting Conventions
- Write `input_data` with exact line endings:
  ```json
  "input_data": "10\n"
  ```
  For multi-line inputs:
  ```json
  "input_data": "5\n10 20 30 40 50\n"
  ```
- Keep `expected_output` crisp:
  ```json
  "expected_output": "23"
  ```
  The sandbox automatically strips trailing spaces and trailing `\n` on both actual and expected output before comparison.

---

## 5. Human-Readable Markdown Format

When authoring paper documentation or student handouts, use the standard Markdown format illustrated below (see `sample_quiz_data/quiz1_paper.md` for reference):

```markdown
# IISER Bhopal — Department of Data Science & Engineering
## DSE-101: C Programming Laboratory
### Quiz 1: Number Theory, Sequences & Bitwise Logic

**Course Code:** `DSE-101`  
**Duration:** 60 Minutes  
**Evaluation System:** Automated GCC Sandbox & Static AST Evaluator  

---

## Q1: Count Set Bits (Hamming Weight)
**Expected Complexity:** `O(log N)` | **Topic Tags:** `bitwise, loops`

Write a C program to count the number of set bits (1s) in the binary representation of a given non-negative integer N.

### Input Format
A single non-negative integer `N` (0 <= N <= 2,000,000,000).

### Output Format
Print the count of set bits followed by a newline.

#### Sample Test Cases
**Sample 1:**
```text
Input:
0
Output:
0
```

**Sample 2:**
```text
Input:
7
Output:
3
```
```

---

## 6. How Question Papers Are Loaded in the Evaluator

1. **Web Dashboard:**
   - Click the **"Load Sample Paper"** dropdown in the web UI. It queries the `/api/samples` endpoint, which automatically discovers all `*_paper.json` files placed inside `sample_quiz_data/`.
   - Alternatively, paste raw JSON directly into the Question Paper JSON textarea.
2. **REST API (`POST /api/jobs`):**
   - Transmitted as the `question_paper_json` multipart form field alongside the student zip archives.
3. **Automated Benchmark Runner:**
   - CLI script `python scripts/evaluate_dataset.py --paper 1` directly loads `sample_quiz_data/quiz1_paper.json`.
