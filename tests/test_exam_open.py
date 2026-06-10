import csv
import json
import argparse
import yaml

from autocorrect.cli import feedback_to_moodle_csv
from autocorrect.exam_open import (
    build_open_answer_prompt,
    evaluate_open_responses,
    generate_open_response_report,
    run_open_answer_smoke_test,
)


def test_feedback_to_moodle_csv_resolves_english_moodle_columns(tmp_path):
    feedback_dir = tmp_path / "feedback"
    feedback_dir.mkdir()
    (feedback_dir / "feedback.yaml").write_text(
        yaml.safe_dump({
            "students": [{"full_name": "Student One"}],
            "feedback": "Good work.",
            "mark": 8.5,
        }),
        encoding="utf-8",
    )

    marks_csv = tmp_path / "marks.csv"
    with open(marks_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Full name", "Grade", "Feedback comments"])
        writer.writeheader()
        writer.writerow({"Full name": "Student One", "Grade": "", "Feedback comments": ""})

    output_csv = tmp_path / "filled.csv"
    feedback_to_moodle_csv(argparse.Namespace(
        marks_csv=str(marks_csv),
        feedback_dir=str(feedback_dir),
        output=str(output_csv),
        encoding="utf-8",
        name_column="Nom complet",
        grade_column="Qualificació",
        feedback_column="Comentaris de retroacció.",
        submission_modified_column="Darrera modificació (tramesa)",
        grade_modified_column="Darrera modificació (qualificació)",
        feedback_format="plain",
        partial=False,
        skip_filled=False,
        clear_timestamps=False,
        fuzzy_threshold=70.0,
    ))

    with open(output_csv, newline="", encoding="utf-8") as f:
        row = next(csv.DictReader(f))
    assert row["Grade"] == "8,50"
    assert row["Feedback comments"] == "Good work."


def test_build_open_answer_prompt_includes_question_rubric_and_expected_answer():
    question = {
        "text": "Explain regularization.",
        "expected_answer": "It penalizes overly complex models.",
        "rubric": "Award points for penalty and generalization.",
        "points": 4,
    }
    row = {"student_id": "s1", "student_name": "Student One", "points": "4"}

    prompt = build_open_answer_prompt(question, row)

    assert "Explain regularization." in prompt
    assert "It penalizes overly complex models." in prompt
    assert "Award points" in prompt
    assert "Student One" in prompt
    assert "response_markdown" in prompt
    assert "conversion_warnings" in prompt


def test_evaluate_open_responses_dry_run_writes_pending_scores_and_prompts(tmp_path):
    exam_dir = tmp_path / "exam"
    responses_dir = tmp_path / "responses"
    output_dir = tmp_path / "eval"
    exam_dir.mkdir()
    responses_dir.mkdir()

    crop_path = responses_dir / "student_model_1_q_2.png"
    crop_path.write_bytes(b"fake image bytes")

    (exam_dir / "exam_model_1_questions.json").write_text(
        json.dumps({
            "questions": [
                {
                    "id": 2,
                    "question_type": "open_answer",
                    "text": "Explain regularization.",
                    "points": 4,
                    "expected_answer": "It penalizes overly complex models.",
                    "rubric": "Award points for penalty and generalization.",
                }
            ]
        }),
        encoding="utf-8",
    )

    index_csv = tmp_path / "open_responses_index.csv"
    with open(index_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "student_id", "student_name", "model_id", "question_id", "original_id",
                "points", "crop_path",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "student_id": "student-1",
            "student_name": "Student One",
            "model_id": "1",
            "question_id": "2",
            "original_id": "open_q",
            "points": "4",
            "crop_path": str(crop_path),
        })

    output_csv = evaluate_open_responses(
        index_csv=str(index_csv),
        exam_dir=str(exam_dir),
        output_dir=str(output_dir),
        dry_run=True,
        keep_prompts=True,
    )

    with open(output_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert rows[0]["status"] == "pending"
    assert rows[0]["max_score"] == "4"
    assert rows[0]["question_text"] == "Explain regularization."
    assert rows[0]["response_markdown"] == ""
    assert (output_dir / "open_evaluations.yaml").exists()
    assert (output_dir / "prompts" / "student-1_q_2.md").exists()


class _FakeMessage:
    content = json.dumps({
        "score": 3.5,
        "max_score": 4,
        "feedback": "Buen trabajo; falta concretar el efecto en validación.",
        "response_markdown": "La regularización reduce el sobreajuste usando $\\lambda$.",
        "conversion_warnings": [],
        "confidence": 0.9,
    })


class _FakeChoice:
    message = _FakeMessage()


class _FakeResponse:
    choices = [_FakeChoice()]


class _FakeCompletions:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        assert kwargs["response_format"] == {"type": "json_object"}
        return _FakeResponse()


class _FakeChat:
    def __init__(self):
        self.completions = _FakeCompletions()


class _FakeClient:
    def __init__(self):
        self.chat = _FakeChat()


def test_evaluate_open_responses_with_fake_llm_writes_editable_artifacts_and_report(tmp_path):
    exam_dir = tmp_path / "exam"
    responses_dir = tmp_path / "responses"
    output_dir = tmp_path / "eval"
    exam_dir.mkdir()
    responses_dir.mkdir()

    crop_path = responses_dir / "student_model_1_q_2.png"
    crop_path.write_bytes(b"fake image bytes")

    (exam_dir / "exam_model_1_questions.json").write_text(
        json.dumps({
            "questions": [
                {
                    "id": 2,
                    "question_type": "open_answer",
                    "text": "Explain regularization.",
                    "points": 4,
                    "expected_answer": "It penalizes overly complex models.",
                    "rubric": "Award points for penalty and generalization.",
                }
            ]
        }),
        encoding="utf-8",
    )

    index_csv = tmp_path / "open_responses_index.csv"
    with open(index_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "student_id", "student_name", "model_id", "question_id", "original_id",
                "points", "crop_path",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "student_id": "student-1",
            "student_name": "Student One",
            "model_id": "1",
            "question_id": "2",
            "original_id": "open_q",
            "points": "4",
            "crop_path": str(crop_path),
        })

    client = _FakeClient()
    output_csv = evaluate_open_responses(
        index_csv=str(index_csv),
        exam_dir=str(exam_dir),
        output_dir=str(output_dir),
        client=client,
    )
    report_path = generate_open_response_report(output_csv, str(output_dir))

    with open(output_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert client.chat.completions.calls == 1
    assert rows[0]["status"] == "graded"
    assert rows[0]["score"] == "3.5"
    assert "$\\lambda$" in rows[0]["response_markdown"]
    yaml_path = output_dir / "open_evaluations.yaml"
    assert yaml_path.exists()
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert data["responses"][0]["feedback"].startswith("Buen trabajo")
    assert data["responses"][0]["question_text"] == "Explain regularization."
    report_html = open(report_path, encoding="utf-8").read()
    assert "Explain regularization." in report_html
    assert "Percentile Samples" in report_html
    assert "Converted Markdown Rendered" in report_html
    assert (output_dir / "student_feedback_pdfs" / "student-1.html").exists()
    assert "Question 2" in (output_dir / "student_feedback_pdfs" / "student-1.html").read_text(encoding="utf-8")

    output_csv = evaluate_open_responses(
        index_csv=str(index_csv),
        exam_dir=str(exam_dir),
        output_dir=str(output_dir),
        client=client,
    )
    assert client.chat.completions.calls == 1
    with open(output_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["status"] == "cached"


def test_open_answer_smoke_test_runs_without_real_llm(tmp_path):
    output_dir = run_open_answer_smoke_test(str(tmp_path), real_llm=False)

    assert (tmp_path / "evaluation" / "open_scores.csv").exists()
    assert (tmp_path / "evaluation" / "open_evaluations.yaml").exists()
    assert (tmp_path / "evaluation" / "question_2_score_distribution.png").exists()
    assert (tmp_path / "evaluation" / "open_responses_report.html").exists()
    assert (tmp_path / "evaluation" / "open_responses_report.pdf").exists()
    assert not (tmp_path / "evaluation" / "post_analysis.json").exists()
    assert (tmp_path / "reevaluation" / "post_analysis.yaml").exists()
    assert (tmp_path / "mc_correction" / "scanned_pages" / "student-1.png").exists()
    from PIL import Image
    with Image.open(tmp_path / "mc_correction" / "scanned_pages" / "student-1.png") as page:
        assert page.width > 1500
        assert page.height > 2000
    assert (tmp_path / "mc_correction" / "stats_report.html").exists()
    assert (tmp_path / "mc_correction" / "stats_report.pdf").exists()
    assert (tmp_path / "mc_correction" / "mark_distribution_0_10.png").exists()
    assert (tmp_path / "reevaluation" / "open_scores.csv").exists()
    assert not (tmp_path / "reevaluation" / "model_inputs").exists()
    assert len(list((tmp_path / "evaluation" / "student_feedback_pdfs").glob("*.pdf"))) == 4
    assert len(list((tmp_path / "reevaluation" / "student_feedback_pdfs").glob("*.pdf"))) == 4
    report_html = (tmp_path / "evaluation" / "open_responses_report.html").read_text(encoding="utf-8")
    assert "open_score_distribution.png" not in report_html
    assert "question_2_score_distribution.png" in report_html
    assert 'class="mermaid"' in report_html
    feedback_html = (tmp_path / "evaluation" / "student_feedback_pdfs" / "student-1.html").read_text(encoding="utf-8")
    assert "Corrected Multiple-Choice Template" in feedback_html
    assert "Open-Answer Feedback" in feedback_html
    assert "model_inputs" not in feedback_html
    assert "mc_correction/scanned_pages/student-1.png" in feedback_html.replace("\\", "/")
    assert "Multiple-Choice Report" in report_html
    assert "Exam Statistics Report" in report_html
    assert "Question Analysis" in report_html
    assert "Overall Results" in report_html
    assert "Students</span><span class='stat-value'>4</span>" in report_html
    assert output_dir == str(tmp_path / "evaluation")
