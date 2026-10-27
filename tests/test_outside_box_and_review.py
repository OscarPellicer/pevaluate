import csv
import io
import json

import yaml
from PIL import Image

from autocorrect.exam_open import FEEDBACK_STYLE, OUTSIDE_BOX_NOTE, evaluate_open_responses
from autocorrect.report import generate_open_response_report

ANSWER = json.dumps({
    "score": 1, "max_score": 2, "feedback": "Falta justificar que $2^5 - 2 = 30$.",
    "response_markdown": "30 direcciones", "conversion_warnings": [], "confidence": 0.6,
})


class RecordingClient:
    def __init__(self):
        self.prompts, self.image_sizes = {}, {}

    def complete(self, prompt, images=(), **kwargs):
        student = kwargs["context"]["student_id"]
        self.prompts[student] = prompt
        self.image_sizes[student] = Image.open(io.BytesIO(images[0][0])).size
        return ANSWER, {"provider": "fake", "model_requested": "fake"}


def _setup(tmp_path, ink_outside="yes"):
    exam_dir, crops = tmp_path / "exam", tmp_path / "crops"
    exam_dir.mkdir(exist_ok=True)
    (crops / "context").mkdir(parents=True, exist_ok=True)
    (exam_dir / "exam_model_1_questions.json").write_text(json.dumps({"questions": [
        {"id": 2, "question_type": "open_answer", "text": "Subredes", "points": 2, "rubric": "1 + 1"}]}), encoding="utf-8")
    Image.new("L", (40, 20), 255).save(crops / "s1.png")
    Image.new("L", (40, 20), 255).save(crops / "s2.png")
    Image.new("L", (100, 60), 255).save(crops / "context" / "s2.png")
    index = tmp_path / "open_responses_index.csv"
    fields = ["student_id", "student_name", "model_id", "question_id", "original_id", "points", "crop_path",
              "layout_check", "ink_outside_box", "ink_outside_mm2", "context_crop_path", "context_box"]
    with open(index, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerow({"student_id": "s1", "student_name": "Uno", "model_id": "1", "question_id": "2",
                         "points": "2", "crop_path": "crops/s1.png", "layout_check": "ok", "ink_outside_box": "no"})
        writer.writerow({"student_id": "s2", "student_name": "Dos", "model_id": "1", "question_id": "2",
                         "points": "2", "crop_path": "crops/s2.png", "layout_check": "ok",
                         "ink_outside_box": ink_outside, "ink_outside_mm2": "40",
                         "context_crop_path": "crops/context/s2.png", "context_box": "10,5,40,20"})
    return str(index), str(exam_dir)


def _rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {r["student_id"]: r for r in csv.DictReader(f)}


def test_writing_outside_the_box_is_graded_from_the_context_crop(tmp_path):
    index, exam_dir = _setup(tmp_path)
    client = RecordingClient()
    out = evaluate_open_responses(index, exam_dir, str(tmp_path / "eval"), client=client)

    assert OUTSIDE_BOX_NOTE in client.prompts["s2"] and OUTSIDE_BOX_NOTE not in client.prompts["s1"]
    assert all(FEEDBACK_STYLE in p for p in client.prompts.values())
    assert client.image_sizes == {"s1": (40, 20), "s2": (100, 60)}
    rows = _rows(out)
    assert (rows["s1"]["graded_from"], rows["s2"]["graded_from"]) == ("box", "context")


def test_regrade_outside_box_only_regrades_what_the_grader_did_not_see(tmp_path):
    index, exam_dir = _setup(tmp_path, ink_outside="no")
    first = RecordingClient()
    evaluate_open_responses(index, exam_dir, str(tmp_path / "eval"), client=first)

    index, exam_dir = _setup(tmp_path, ink_outside="yes")      # e.g. a newer pexams detects it
    second = RecordingClient()
    out = evaluate_open_responses(index, exam_dir, str(tmp_path / "eval"), client=second)
    assert second.prompts == {}                                 # cached, but flagged for review
    assert "writing outside the box" in _rows(tmp_path / "eval" / "needs_review.csv")["s2"]["reasons"]

    third = RecordingClient()
    out = evaluate_open_responses(index, exam_dir, str(tmp_path / "eval"), client=third, regrade_outside_box=True)
    assert set(third.prompts) == {"s2"}
    assert _rows(out)["s2"]["graded_from"] == "context"


def test_needs_review_skips_teacher_edits_and_reports_render_markdown(tmp_path):
    index, exam_dir = _setup(tmp_path)
    eval_dir = tmp_path / "eval"
    evaluate_open_responses(index, exam_dir, str(eval_dir), client=RecordingClient())
    assert set(_rows(eval_dir / "needs_review.csv")) == {"s1", "s2"}      # confidence 0.6

    data = yaml.safe_load((eval_dir / "open_evaluations.yaml").read_text(encoding="utf-8"))
    data["responses"][0]["score"] = 2                                      # the teacher reviews s1
    (eval_dir / "open_evaluations.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    out = evaluate_open_responses(index, exam_dir, str(eval_dir), client=RecordingClient())
    assert _rows(out)["s1"]["teacher_edited"] == "yes"
    assert set(_rows(eval_dir / "needs_review.csv")) == {"s2"}

    generate_open_response_report(out, str(eval_dir), lang="es")
    student = (eval_dir / "student_feedback_pdfs" / "s2.html").read_text(encoding="utf-8")
    assert "Comentario" in student and "Preguntas abiertas" in student
    assert 'class="arithmatex"' in student and "$2^5" not in student       # math rendered, not literal
    assert "context/s2.png" in student                                     # the image it was graded from
    marks = _rows(eval_dir / "overall_marks.csv")
    assert marks["s1"]["q_2"] == "2" and marks["s2"]["q_2"] == "1"
