# IISER Bhopal — Department of Data Science & Engineering
## DSE-101: C Programming Laboratory
### Quiz 1: Number Theory, Sequences & Bitwise Logic

**Course Code:** `DSE-101`  
**Duration:** 60 Minutes  
**Evaluation Mode:** Automated GCC Sandbox & AST Integrity Triage  

---

## Instructions for Students
1. Every solution must be written in standard C (C99/C11 standard) and submitted as a separate `.c` file named `que1.c`, `que2.c`, and `que3.c` inside a single ZIP archive named `<your_roll_no>.zip`.
2. Do not use external libraries or system calls (`stdlib.h` system wrappers, `unistd.h`, `windows.h`, `fork`, `exec`).
3. Programs are executed in an isolated GCC sandbox with strict CPU time limits (1.5 seconds per test case) and memory bounds (128 MB).
4. Code is evaluated against both visible **Sample Test Cases** and unseen **Hidden Test Cases**. Hardcoding sample outputs or attempting to mislead automated evaluators will trigger immediate integrity flags.

---

## Question 1: Count Set Bits (Hamming Weight)
- **Question ID:** `Q1`
- **Expected Complexity:** $\mathcal{O}(\log N)$ or $\mathcal{O}(\text{set bits})$
- **Topic Tags:** `bitwise`, `loops`, `number-theory`

### Problem Statement
Write a C program that reads a single non-negative integer $N$ from standard input and computes the number of set bits (1s in its binary representation).

### Input Format
A single line containing a non-negative integer $N$ where:
$$0 \le N \le 2\,000\,000\,000$$

### Output Format
Print the total count of set bits followed by a single newline character `\n`.

### Sample Test Cases

#### Sample 1 (Visible)
- **Input:**
  ```text
  0
  ```
- **Output:**
  ```text
  0
  ```
- **Explanation:** In binary, $0 = 0_2$, which has zero set bits.

#### Sample 2 (Visible)
- **Input:**
  ```text
  7
  ```
- **Output:**
  ```text
  3
  ```
- **Explanation:** In binary, $7 = 111_2$, which has 3 set bits.

#### Sample 3 (Visible)
- **Input:**
  ```text
  16
  ```
- **Output:**
  ```text
  1
  ```
- **Explanation:** In binary, $16 = 10000_2$, which is a power of 2 with exactly 1 set bit.

### Hidden Test Suite (Evaluator Ground Truth)
| Test Case # | Input (`stdin`) | Expected Output (`stdout`) | Test Category / Objective |
|---|---|---|---|
| Hidden 1 | `1023` | `10` | Full 10-bit contiguous mask ($2^{10}-1$) |
| Hidden 2 | `1048576` | `1` | High single-bit power of 2 ($2^{20}$) |
| Hidden 3 | `123456789` | `16` | Arbitrary 27-bit integer |
| Hidden 4 | `2147483647` | `31` | Maximum signed 32-bit positive integer ($2^{31}-1$) |

---

## Question 2: Collatz Conjecture Steps
- **Question ID:** `Q2`
- **Expected Complexity:** $\mathcal{O}(\text{steps})$
- **Topic Tags:** `loops`, `recursion`, `sequences`

### Problem Statement
Given a positive integer $N$, compute the total number of transformation steps required to reach $1$ according to the Collatz rules:
- If $N$ is even: $N \leftarrow \frac{N}{2}$
- If $N$ is odd: $N \leftarrow 3N + 1$

If $N$ is already $1$, the number of transformation steps is $0$.

### Input Format
A single positive integer $N$ where:
$$1 \le N \le 100\,000$$

### Output Format
Print the total number of transformation steps required to reach 1, followed by a newline.

### Sample Test Cases

#### Sample 1 (Visible)
- **Input:**
  ```text
  1
  ```
- **Output:**
  ```text
  0
  ```
- **Explanation:** $N$ is already 1, requiring 0 steps.

#### Sample 2 (Visible)
- **Input:**
  ```text
  6
  ```
- **Output:**
  ```text
  8
  ```
- **Explanation:** The sequence is $6 \to 3 \to 10 \to 5 \to 16 \to 8 \to 4 \to 2 \to 1$ (8 steps).

#### Sample 3 (Visible)
- **Input:**
  ```text
  11
  ```
- **Output:**
  ```text
  14
  ```
- **Explanation:** Sequence: $11 \to 34 \to 17 \to 52 \to 26 \to 13 \to 40 \to 20 \to 10 \to 5 \to 16 \to 8 \to 4 \to 2 \to 1$ (14 steps).

### Hidden Test Suite (Evaluator Ground Truth)
| Test Case # | Input (`stdin`) | Expected Output (`stdout`) | Test Category / Objective |
|---|---|---|---|
| Hidden 1 | `27` | `111` | Famous high-depth Collatz seed (peaks at 9232) |
| Hidden 2 | `100` | `25` | Medium two-digit boundary |
| Hidden 3 | `1000` | `111` | Three-digit boundary |
| Hidden 4 | `9999` | `91` | Large boundary input near limit |

---

## Question 3: Sum of Multiples of 3 or 5 below N
- **Question ID:** `Q3`
- **Expected Complexity:** $\mathcal{O}(N)$ or $\mathcal{O}(1)$
- **Topic Tags:** `loops`, `series`, `math`

### Problem Statement
Find the sum of all natural numbers strictly less than $N$ that are multiples of $3$ or $5$.
If a number is a multiple of both $3$ and $5$ (e.g., $15, 30$), it must be counted only once. If $N \le 3$, the sum is $0$.

> **Note on Integer Width:** For larger values of $N$ (e.g., $N = 1\,000\,000$), the resulting sum exceeds the 32-bit signed integer maximum ($2^{31}-1 \approx 2.14 \times 10^9$). You **must** use a 64-bit integer (`long long` in C with format specifier `%lld`) to avoid arithmetic overflow.

### Input Format
A single integer $N$ where:
$$1 \le N \le 1\,000\,000$$

### Output Format
Print the computed sum followed by a single newline character.

### Sample Test Cases

#### Sample 1 (Visible)
- **Input:**
  ```text
  10
  ```
- **Output:**
  ```text
  23
  ```
- **Explanation:** Multiples of 3 or 5 strictly below 10 are $3, 5, 6, 9$. Their sum is $3 + 5 + 6 + 9 = 23$.

#### Sample 2 (Visible)
- **Input:**
  ```text
  16
  ```
- **Output:**
  ```text
  60
  ```
- **Explanation:** Multiples are $3, 5, 6, 9, 10, 12, 15$. Their sum is $3 + 5 + 6 + 9 + 10 + 12 + 15 = 60$.

### Hidden Test Suite (Evaluator Ground Truth)
| Test Case # | Input (`stdin`) | Expected Output (`stdout`) | Test Category / Objective |
|---|---|---|---|
| Hidden 1 | `2` | `0` | Lower edge case: no positive multiples below 2 |
| Hidden 2 | `100` | `2318` | Moderate range check |
| Hidden 3 | `1000` | `233168` | Four-digit range check |
| Hidden 4 | `50000` | `583291668` | Intermediate boundary check |
| Hidden 5 | `1000000` | `233333166668` | Maximum constraint; strictly requires 64-bit `long long` |
