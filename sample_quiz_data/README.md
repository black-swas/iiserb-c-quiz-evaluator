# Sample Quiz Data & Benchmark Suite

This directory contains reference question papers, student submission datasets, authoring guidelines, and generation prompts for the **IISER Bhopal DSE C-Lab Quiz Evaluator**.

---

## 1. Directory Contents

| File / Folder | Format | Description |
|---|:---:|---|
| **[`quiz1_paper.json`](quiz1_paper.json)** | JSON | **Question Paper 1 (Machine-Readable):** Official evaluator schema for Quiz 1 (Hamming Weight, Collatz Steps, Sum of Multiples). Loaded automatically by `/api/samples`. |
| **[`quiz1_paper.md`](quiz1_paper.md)** | Markdown | **Question Paper 1 (Human-Readable):** Formatted exam sheet for Quiz 1 with full constraints, sample cases, and hidden ground truth tables. |
| **[`quiz2_paper.json`](quiz2_paper.json)** | JSON | Question Paper 2: Arrays & Linear Algorithms (Second Largest, Array Inversion, Majority Element). |
| **[`quiz3_paper.json`](quiz3_paper.json)** | JSON | Question Paper 3: Matrices & Logic (Binary GCD, Palindrome Check, In-Place Matrix Transposition). |
| **[`quiz1_solutions/`](quiz1_solutions/)** | Folder | **Student Sample Solutions:** 15 student archives (`student1_que_paper1.zip` … `student15_que_paper1.zip`) plus extracted C source codes in `c_sources/` for Quiz 1. |
| **[`QUESTION_PAPER_FORMAT.md`](QUESTION_PAPER_FORMAT.md)** | Docs | **Question Paper Specification:** Complete schema reference (JSON & Markdown), field constraints, and guidelines for designing cheat-resilient test suites. |
| **[`GENERATION_MAPPING.md`](GENERATION_MAPPING.md)** | Docs | **Persona & Triage Mapping:** In-depth behavior matrix for all 15 student personas on Quiz 1, detailing algorithmic choices, detection vectors, and expected tabs. |
| **[`DATASET_GENERATION_PROMPT.md`](DATASET_GENERATION_PROMPT.md)** | Docs | **LLM Benchmark Generation Prompt:** Ready-to-copy master prompt for generating new 3-question papers and 15-persona student codebases via Claude, GPT-4o, or Gemini. |

---

## 2. The 7 Types of Tests Performed

The evaluator systematically verifies all submissions through 7 verification layers:

1. **Security violations:** Checks for restricted operations such as `system()`, `fork()`, `socket()`, `getenv()`, file-writing operations, inline assembly, and unsafe or forbidden `#include` paths. Programs that trigger these checks are not executed.
2. **Attempts to manipulate the grader:** Examines comments and string literals for text directed at an automated grader. Such instructions can trigger a review even if the code compiles.
3. **Empty or incomplete programs:** Detects empty implementations or skeleton `main()` functions that do not meaningfully implement the assigned solution.
4. **Compilation and runtime failures:** Compiles the submission with GCC and checks for compilation errors, execution timeouts, and failures during testing.
5. **Assignment-specific restrictions:** Checks whether the program uses constructs explicitly prohibited by the question paper, through its `forbidden_constructs` configuration.
6. **Functional correctness and hard-coded answers:** Runs the configured test cases. It distinguishes programs that pass, ordinary failing solutions, programs that always print the same output, and programs that only handle the sample inputs. It also checks for suspicious decoy loops that never reach the output.
7. **Plagiarism indicators and unusual approaches:** Compares submissions for structural similarity, looking for distinctive shared code or near-exact copies across multiple questions. It can flag strong matches for review and identify unusual techniques in otherwise correct solutions.

---

## 3. Quickstart: Running the Quiz 1 Benchmark

You can evaluate the Quiz 1 benchmark dataset deterministically in seconds (requires Linux or WSL with GCC installed):

```bash
# From the repository root:
python scripts/evaluate_dataset.py --zips sample_quiz_data/quiz1_solutions --paper 1 --no-llm
```

### Expected Output Summary
- **Students Evaluated:** 15 students (45 total C files)
- **RED Recall:** 100% (all designed cheats, bugs, timeouts, and clones caught)
- **Honest False Positives:** 0 (honest students S1–S7 are never flagged RED)
- **Plagiarism Collusion:** Student 8 & Student 9 pair detected across multiple questions ($\ge 94\%$ similarity)
