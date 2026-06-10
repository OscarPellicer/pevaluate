import csv
import os
from pathlib import Path

import pytest

from autocorrect.exam_open import load_project_dotenv, run_open_answer_smoke_test


def _requires_llm():
    load_project_dotenv()
    if os.getenv("RUN_LLM_TESTS") != "1":
        pytest.skip("set RUN_LLM_TESTS=1 to run real LLM tests")
    if not os.getenv("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY is required for real LLM tests")


@pytest.mark.llm
def test_open_answer_smoke_pipeline_with_real_llm(tmp_path):
    _requires_llm()

    model = os.getenv("PEVALUATE_LLM_TEST_MODEL", "google/gemini-3-flash-preview")
    output_dir = Path(run_open_answer_smoke_test(str(tmp_path), real_llm=True, model=model))

    scores_csv = output_dir / "open_scores.csv"
    report_candidates = [
        output_dir / "open_response_report.pdf",
        output_dir / "open_response_report.html",
        output_dir / "open_responses_report.pdf",
        output_dir / "open_responses_report.html",
        output_dir / "report.pdf",
        output_dir / "report.html",
    ]
    feedback_candidates = [output_dir / "feedback", output_dir / "student_feedback_pdfs"]

    assert scores_csv.exists()
    assert any(path.exists() for path in report_candidates)
    assert any(path.exists() for path in feedback_candidates)

    rows = list(csv.DictReader(scores_csv.open(encoding="utf-8")))
    assert len(rows) == 4
    assert all(row["status"] == "graded" for row in rows)
    assert all(row["feedback"].strip() for row in rows)
