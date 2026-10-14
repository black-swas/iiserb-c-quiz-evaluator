"""Pairwise structural clone detection with false-positive control.

Two students who both write the textbook loop for a trivial problem produce *identical* token
streams, so raw similarity alone is poor evidence. This engine therefore separates:

  * similarity  - how alike the canonicalised programs are (renamed identifiers, for/while swaps,
                  whitespace and comments are all normalised away)
  * strength    - how *unusual* the match is within the class:
        STRONG  the shared structure is distinctive (rare shingles, or identical non-trivial comments),
                or the same pair is a near-exact match in several questions (corroboration)
        WEAK    the programs are alike but so are many classmates' (common textbook solution)

Only STRONG matches create a PLAGIARISM_CLONE verdict or a collusion pair. WEAK matches are shown to
the TA as context. All thresholds are configurable (see app.config).
"""
import math
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Dict, List, Set, Tuple

from app.analyzer.c_static_analyzer import C_KEYWORDS, extract_and_strip_comments
from app.config import settings
from app.schemas import CloneMatch, CollusionPair

TOKEN_SPEC = re.compile(
    r'("([^"\\]|\\.)*")|'
    r"('([^'\\]|\\.)*')|"
    r"(\b\d+(?:\.\d+)?\b)|"
    r"(\b[a-zA-Z_][a-zA-Z0-9_]*\b)|"
    r"(==|!=|<=|>=|&&|\|\||<<|>>|\+\+|--|\+=|-=|\*=|\/=|%=|&=|\|=|\^=|->|[+\-*/%&|^~<>!=?:;,.()\[\]{}])"
)

MAX_TOKENS = 1500
MIN_COMPARE_TOKENS = 14
LOOSE_MATCH_BELOW = 95.0           # below this similarity a match needs LOOSE_EXCLUSIVE_FACTOR x the usual distinctiveness
LOOSE_EXCLUSIVE_FACTOR = 2.5       # (two students independently using the same clever trick are ~90% alike, copies are ~100%)
EXACT_PERCENT = 99.5               # inside a group of 3+ look-alikes only identical pairs corroborate each other
SHINGLE_PREFILTER_PERCENT = 25.0   # unrelated programs sit far below this; cheap guard before SequenceMatcher


def normalize_c_tokens(raw_code: str) -> Tuple[List[str], List[Tuple[int, str]], List[str]]:
    """Returns (canonical tokens, per-line canonical text, raw tokens).

    Identifiers become VAR_n by order of appearance, loops all become LOOP, literals are bucketed.
    """
    stripped, _ = extract_and_strip_comments(raw_code)
    id_map: Dict[str, str] = {}
    flat: List[str] = []
    raw_tokens: List[str] = []
    line_reps: List[Tuple[int, str]] = []

    for idx, line in enumerate(stripped.splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        line_toks: List[str] = []
        for m in TOKEN_SPEC.finditer(s):
            str_lit, _, char_lit, _, num_lit, ident, op = m.groups()
            if str_lit is not None:
                tok, raw = "STR_LIT", str_lit
            elif char_lit is not None:
                tok, raw = "CHAR_LIT", char_lit
            elif num_lit is not None:
                tok, raw = (num_lit if num_lit in ("0", "1") else "NUM_LIT"), num_lit
            elif ident is not None:
                raw = ident
                if ident in ("for", "while", "do"):
                    tok = "LOOP"
                elif ident in C_KEYWORDS:
                    tok = ident
                else:
                    tok = id_map.setdefault(ident, f"VAR_{len(id_map) + 1}")
            elif op is not None:
                tok, raw = op, op
            else:
                continue
            flat.append(tok)
            raw_tokens.append(raw)
            line_toks.append(tok)
        if line_toks:
            line_reps.append((idx, " ".join(line_toks)))
    return flat, line_reps, raw_tokens


def _shingles(tokens: List[str], k: int) -> Set[Tuple[str, ...]]:
    if len(tokens) < k:
        return set()
    return {tuple(tokens[i:i + k]) for i in range(len(tokens) - k + 1)}


def _jaccard(a: Set, b: Set) -> float:
    if not a or not b:
        return 0.0
    return 100.0 * len(a & b) / len(a | b)


def compute_shingle_jaccard(tokens_a: List[str], tokens_b: List[str], k: int = 5) -> float:
    return _jaccard(_shingles(tokens_a, k), _shingles(tokens_b, k))


def compute_sequence_similarity(tokens_a: List[str], tokens_b: List[str]) -> float:
    """difflib ratio with autojunk=False (autojunk silently degrades long token streams)."""
    if not tokens_a or not tokens_b:
        return 0.0
    return SequenceMatcher(None, tokens_a, tokens_b, autojunk=False).ratio() * 100.0


def compute_comment_and_typo_overlap(code_a: str, code_b: str) -> float:
    """Share of identical non-trivial comments (a strong collusion signal)."""
    _, comments_a = extract_and_strip_comments(code_a)
    _, comments_b = extract_and_strip_comments(code_b)
    set_a = {c.strip().lower() for c in comments_a if len(c.strip()) > 8}
    set_b = {c.strip().lower() for c in comments_b if len(c.strip()) > 8}
    if not set_a or not set_b:
        return 0.0
    return 100.0 * len(set_a & set_b) / len(set_a | set_b)


def find_matching_lines(
    lines_a: List[Tuple[int, str]], lines_b: List[Tuple[int, str]]
) -> Tuple[List[int], List[int]]:
    trivial = {"{", "}", "return 0 ;", "return VAR_1 ;"}
    b_lookup = {norm for _, norm in lines_b if norm not in trivial and len(norm) > 4}
    a_lookup = {norm for _, norm in lines_a if norm not in trivial and len(norm) > 4}
    return ([n for n, norm in lines_a if norm in b_lookup], [n for n, norm in lines_b if norm in a_lookup])


class _UnionFind:
    def __init__(self, items: List[str]) -> None:
        self.parent = {x: x for x in items}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def run_question_plagiarism_matrix(
    question_id: str,
    submissions: Dict[str, str],
    threshold_percent: float = None,
) -> Tuple[Dict[str, List[CloneMatch]], Dict[str, str]]:
    thr = settings.clone_threshold_percent if threshold_percent is None else threshold_percent
    rolls = sorted(submissions)
    tokens: Dict[str, List[str]] = {}
    line_maps: Dict[str, List[Tuple[int, str]]] = {}
    previews: Dict[str, str] = {}
    for r in rolls:
        toks, lmap, _ = normalize_c_tokens(submissions[r])
        toks = toks[:MAX_TOKENS]
        tokens[r], line_maps[r] = toks, lmap
        previews[r] = " ".join(toks[:60]) + (" ..." if len(toks) > 60 else "")
    clone_map: Dict[str, List[CloneMatch]] = {r: [] for r in rolls}

    sh4 = {r: _shingles(tokens[r], 4) for r in rolls}
    sh5 = {r: _shingles(tokens[r], 5) for r in rolls}
    df: Counter = Counter()
    for r in rolls:
        df.update(sh4[r])

    # ---- candidate pairs
    candidates: List[Tuple[str, str, float, float, float]] = []   # a, b, seq, jaccard, exclusive%
    for i, a in enumerate(rolls):
        ta = tokens[a]
        if len(ta) < MIN_COMPARE_TOKENS:
            continue
        for b in rolls[i + 1:]:
            tb = tokens[b]
            if len(tb) < MIN_COMPARE_TOKENS:
                continue
            if 200.0 * min(len(ta), len(tb)) / (len(ta) + len(tb)) < thr:
                continue                                   # lengths too different to reach the threshold
            jacc = _jaccard(sh5[a], sh5[b])
            if jacc < SHINGLE_PREFILTER_PERCENT:
                continue
            matcher = SequenceMatcher(None, ta, tb, autojunk=False)
            if matcher.real_quick_ratio() * 100.0 < thr or matcher.quick_ratio() * 100.0 < thr:
                continue
            seq = matcher.ratio() * 100.0
            if seq < thr:
                continue
            shared = sh4[a] & sh4[b]
            denom = max(1, min(len(sh4[a]), len(sh4[b])))
            exclusive = 100.0 * sum(1 for s in shared if df[s] <= 2) / denom
            candidates.append((a, b, seq, jacc, exclusive))

    # ---- clusters of mutually similar submissions = "everyone wrote it this way"
    uf = _UnionFind(rolls)
    for a, b, *_ in candidates:
        uf.union(a, b)
    cluster_sizes = Counter(uf.find(r) for r in rolls)
    # Single-link clustering at the loose threshold chains unrelated pairs together on short problems; the
    # near-exact cluster (what corroboration needs) is only the group of really identical programs.
    uf_near = _UnionFind(rolls)
    for a, b, seq, *_ in candidates:
        if seq >= settings.clone_near_exact_percent:
            uf_near.union(a, b)
    near_sizes = Counter(uf_near.find(r) for r in rolls)

    for a, b, seq, jacc, exclusive in candidates:
        csize = cluster_sizes[uf.find(a)]
        small = min(len(tokens[a]), len(tokens[b])) < settings.clone_min_tokens
        comments = compute_comment_and_typo_overlap(submissions[a], submissions[b])
        need = settings.clone_exclusive_min_percent * (1.0 if seq >= LOOSE_MATCH_BELOW else LOOSE_EXCLUSIVE_FACTOR)
        strong = (not small) and (comments >= 50.0 or exclusive >= need)
        lines_a, lines_b = find_matching_lines(line_maps[a], line_maps[b])
        for me, other, mine, theirs in ((a, b, lines_a, lines_b), (b, a, lines_b, lines_a)):
            clone_map[me].append(CloneMatch(
                partner_roll_no=other,
                question_id=question_id,
                similarity_percent=round(seq, 1),
                jaccard_percent=round(jacc, 1),
                sequence_percent=round(seq, 1),
                exclusive_percent=round(exclusive, 1),
                cluster_size=csize,
                near_cluster_size=near_sizes[uf_near.find(a)],
                strength="STRONG" if strong else "WEAK",
                matched_lines_self=mine,
                matched_lines_partner=theirs,
            ))

    for r in rolls:
        clone_map[r].sort(key=lambda m: (m.strength != "STRONG", -m.similarity_percent))
    return clone_map, previews


def apply_collusion_corroboration(
    all_question_clones: Dict[str, Dict[str, List[CloneMatch]]],
    n_students: int,
    min_questions: int = None,
    near_exact_percent: float = None,
) -> int:
    """Upgrade WEAK matches of a pair that is a near-exact copy in several questions.

    Questions where the match sits inside a large cluster of identical solutions (the textbook
    answer) do not count towards corroboration. Returns the number of corroborated pairs.
    """
    min_q = settings.collusion_min_questions if min_questions is None else min_questions
    near = settings.clone_near_exact_percent if near_exact_percent is None else near_exact_percent
    cluster_limit = max(3, math.ceil(0.2 * n_students))

    counted: Dict[Tuple[str, str], Set[str]] = {}
    for q_id, clone_map in all_question_clones.items():
        for roll, matches in clone_map.items():
            for m in matches:
                group = m.cluster_size if m.near_cluster_size is None else m.near_cluster_size
                if (roll < m.partner_roll_no and m.similarity_percent >= near and group <= cluster_limit
                        and (group <= 2 or m.similarity_percent >= EXACT_PERCENT)):
                    counted.setdefault((roll, m.partner_roll_no), set()).add(q_id)
    corroborated = {pair for pair, qs in counted.items() if len(qs) >= min_q}

    for clone_map in all_question_clones.values():
        for roll, matches in clone_map.items():
            for m in matches:
                if m.strength != "STRONG" and tuple(sorted((roll, m.partner_roll_no))) in corroborated:
                    m.strength = "STRONG"
                    m.corroborated = True
    return len(corroborated)


def detect_cross_question_collusion(
    all_question_clones: Dict[str, Dict[str, List[CloneMatch]]],
    min_shared_questions: int = None,
) -> List[CollusionPair]:
    """Pairs with STRONG matches in at least `min_shared_questions` questions."""
    if min_shared_questions is None:
        min_shared_questions = settings.collusion_min_questions
    pair_map: Dict[Tuple[str, str], List[Tuple[str, float]]] = {}
    for q_id, clone_map in all_question_clones.items():
        for roll_a, matches in clone_map.items():
            for m in matches:
                if m.strength == "STRONG" and roll_a < m.partner_roll_no:
                    pair_map.setdefault((roll_a, m.partner_roll_no), []).append((q_id, m.similarity_percent))

    pairs: List[CollusionPair] = []
    for (roll_a, roll_b), q_scores in pair_map.items():
        if len(q_scores) >= min_shared_questions:
            scores = [s for _, s in q_scores]
            pairs.append(CollusionPair(
                roll_a=roll_a,
                roll_b=roll_b,
                shared_questions=sorted(q for q, _ in q_scores),
                average_similarity=round(sum(scores) / len(scores), 1),
                max_similarity=round(max(scores), 1),
            ))
    pairs.sort(key=lambda c: (len(c.shared_questions), c.average_similarity), reverse=True)
    return pairs
