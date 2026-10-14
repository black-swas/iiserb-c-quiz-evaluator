"""Pydantic models shared by the API, the analysers and the UI."""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

TabCategory = Literal["GREEN", "BLUE", "RED", "GRAY"]

CheatType = Literal[
    "NONE",
    "HARDCODED_PRINTF",
    "SAMPLE_INPUT_SPOOFING",
    "DEAD_CODE_PADDING",
    "PLAGIARISM_CLONE",
    "PROMPT_INJECTION",
    "SECURITY_VIOLATION",
    "RULE_VIOLATION",
    "COMPILE_ERROR",
    "TIMEOUT",
    "BROKEN_LOGIC",
    "UNSUBMITTED_OR_STUB",
]


# --------------------------------------------------------------------------- question paper
class TestCase(BaseModel):
    input_data: str = Field(default="", max_length=65536, description="Standard input passed to the C program")
    expected_output: str = Field(..., max_length=65536, description="Expected standard output")
    is_sample: bool = Field(default=False, description="True if this case was visible in the question paper")


class QuestionSpec(BaseModel):
    question_id: str = Field(..., pattern=r"^Q\d{1,2}$", description="Q1, Q2, ...")
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


# --------------------------------------------------------------------------- analysis results
class StaticAnalysisResult(BaseModel):
    line_count: int
    has_loops: bool
    loop_types: List[str]
    has_recursion: bool
    has_pointers: bool
    has_bitwise: bool
    has_ternary_or_goto: bool
    printf_count: int
    scanf_count: int
    constant_printf_lines: List[int]
    sample_spoof_lines: List[int]
    dead_loop_suspected: bool
    dead_loop_lines: List[int]
    prompt_injection_detected: bool
    prompt_injection_snippets: List[str]
    security_violations: List[str] = Field(default_factory=list)
    forbidden_hits: List[str] = Field(default_factory=list)
    include_notes: List[str] = Field(default_factory=list)
    is_empty_or_stub: bool
    uncommon_construct_notes: List[str]
    static_suspicion_reasons: List[str]


class GccTestResult(BaseModel):
    compiled: bool
    compiler_warnings: str = ""
    compiler_errors: str = ""
    passed_count: int = 0
    total_count: int = 0
    sample_passed: int = 0
    sample_total: int = 0
    hidden_passed: int = 0
    hidden_total: int = 0
    timed_out: bool = False
    runtime_error: bool = False
    skipped_reason: str = ""
    case_details: List[Dict[str, Any]] = Field(default_factory=list)


class CloneMatch(BaseModel):
    partner_roll_no: str
    question_id: str
    similarity_percent: float
    jaccard_percent: float
    sequence_percent: float
    exclusive_percent: float = 0.0
    cluster_size: int = 2
    near_cluster_size: Optional[int] = None   # size of the group of near-exact copies (None = unknown, fall back to cluster_size)
    strength: Literal["STRONG", "WEAK"] = "WEAK"
    corroborated: bool = False
    matched_lines_self: List[int] = Field(default_factory=list)
    matched_lines_partner: List[int] = Field(default_factory=list)


class SubmissionEvaluation(BaseModel):
    roll_no: str
    question_id: str
    filename: str
    raw_code: str
    normalized_tokens_preview: str = ""
    tab_category: TabCategory
    verdict_badge: str
    confidence_score: int = Field(ge=0, le=100)
    cheat_type: CheatType = "NONE"
    uncommon_approach_tag: Optional[str] = None
    logic_summary: str
    instructor_callout: str
    flagged_lines: List[int] = Field(default_factory=list)
    line_annotations: Dict[str, str] = Field(default_factory=dict)
    integrity_notes: List[str] = Field(default_factory=list)
    static_analysis: StaticAnalysisResult
    gcc_result: Optional[GccTestResult] = None
    clone_matches: List[CloneMatch] = Field(default_factory=list)
    max_clone_similarity: float = 0.0
    evaluation_source: Literal["DETERMINISTIC", "DETERMINISTIC+LLM"] = "DETERMINISTIC"
    llm_summary: Optional[str] = None
    llm_callout: Optional[str] = None
    llm_model: Optional[str] = None
    ta_feedback: Optional[Literal["AGREE", "DISAGREE"]] = None
    ta_override_category: Optional[Literal["GREEN", "BLUE", "RED"]] = None
    ta_note: Optional[str] = None


class CollusionPair(BaseModel):
    roll_a: str
    roll_b: str
    shared_questions: List[str]
    average_similarity: float
    max_similarity: float


# --------------------------------------------------------------------------- TA feedback (calibration memory)
class HITLFeedbackRequest(BaseModel):
    course_code: str = Field(default="DSE-101", max_length=40)
    question_id: str = Field(..., pattern=r"^Q\d{1,2}$")
    topic_tags: List[str] = Field(default_factory=list, max_length=20)
    problem_summary: str = Field(..., max_length=400)
    roll_no: str = Field(..., max_length=80)
    raw_code: str = Field(..., max_length=20000)
    original_category: Literal["GREEN", "BLUE", "RED", "GRAY"]
    original_cheat_type: str = Field(default="NONE", max_length=60)
    ta_decision: Literal["AGREE", "DISAGREE"]
    override_category: Literal["GREEN", "BLUE", "RED"]
    ta_explanation: str = Field(default="", max_length=600)


class HITLFeedbackResponse(BaseModel):
    status: str
    record_id: int
    message: str


# --------------------------------------------------------------------------- batch response / jobs
class BatchEvaluationResponse(BaseModel):
    course_code: str
    quiz_title: str
    evaluated_at: str = ""
    elapsed_seconds: float = 0.0
    student_count: int
    total_c_files: int
    summary_counts: Dict[str, int]
    questions: List[QuestionSpec]
    evaluations_by_question: Dict[str, List[SubmissionEvaluation]]
    student_matrix: Dict[str, Dict[str, Dict[str, Any]]]
    collusion_pairs: List[CollusionPair]
    ingestion_warnings: List[str] = Field(default_factory=list)
    ignored_binaries: List[str] = Field(default_factory=list)
    engine: Dict[str, Any] = Field(default_factory=dict)


class JobCreated(BaseModel):
    job_id: str
    status: str


class JobStatus(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "error"]
    stage: str = ""
    progress: float = 0.0
    message: str = ""
    error: Optional[str] = None
