"""The model's original grade is kept in the grader block, so teacher edits can be measured."""
import csv
import json

import yaml
from PIL import Image

from autocorrect import exam_free
from autocorrect.exam_open import evaluate_open_responses
from autocorrect.llm import LLMClient

META = {"provider": "anthropic", "model_requested": "claude-opus-5-5", "model_served": "claude-opus-5-5",
        "effort": "medium", "fallback_used": False, "request_id": "req_1",
        "timestamp_utc": "2026-10-27T00:00:00+00:00", "tool_version": "test"}


class _FakeLLMClient(LLMClient):
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def complete(self, prompt, images=(), **kwargs):
        self.calls += 1
        return json.dumps(self.reply), META


def _exam(tmp_path):
    exam_dir = tmp_path / "exam"; exam_dir.mkdir()
    questions = [{"id": 1, "original_id": "q_auc", "text": "¿Por qué?", "points": 1, "expected_answer": "X", "rubric": "- 100 %: X"}]
    (exam_dir / "exam_model_1_questions.json").write_text(json.dumps({"questions": questions}), encoding="utf-8")
    return exam_dir


def test_exam_open_keeps_llm_grade_after_teacher_edit(tmp_path):
    exam_dir = _exam(tmp_path)
    Image.new("RGB", (400, 100), "white").save(tmp_path / "crop.png")
    index = tmp_path / "index.csv"
    with open(index, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["student_id", "student_name", "model_id", "question_id", "original_id", "crop_path", "points"])
        w.writeheader()
        w.writerow({"student_id": "1", "student_name": "Ana", "model_id": "1", "question_id": "1", "original_id": "q_auc",
                    "crop_path": "crop.png", "points": "1"})
    client = _FakeLLMClient({"score": 0.5, "max_score": 1, "feedback": "Falta X.", "response_markdown": "a", "confidence": 0.9})
    out = tmp_path / "out"
    evaluate_open_responses(str(index), str(exam_dir), str(out), client=client)
    path = out / "open_evaluations.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    item = data["responses"][0]
    assert (item["grader"]["score"], item["grader"]["feedback"]) == (0.5, "Falta X.")
    item["score"], item["feedback"] = 1, "Correcto."
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    evaluate_open_responses(str(index), str(exam_dir), str(out), client=client)
    item = yaml.safe_load(path.read_text(encoding="utf-8"))["responses"][0]
    assert client.calls == 1
    assert (item["score"], item["grader"]["score"], item["grader"]["feedback"]) == (1, 0.5, "Falta X.")


def test_exam_free_keeps_llm_grade_after_teacher_edit(tmp_path):
    exam_dir = _exam(tmp_path)
    pages = tmp_path / "pages"; pages.mkdir()
    Image.new("RGB", (400, 560), "white").save(pages / "p0.png")
    client = _FakeLLMClient({"student_name": "Ana", "student_id": "12345678A",
                             "answers": [{"question_id": "1", "score": 0.25, "max_score": 1, "feedback": "Falta X."}]})
    out = tmp_path / "out"
    exam_free.evaluate_free_exams(str(pages), str(exam_dir), str(out), client=client)
    path = out / "open_evaluations.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["responses"][0]["score"] = 1
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    exam_free.evaluate_free_exams(str(pages), str(exam_dir), str(out), client=client)
    item = yaml.safe_load(path.read_text(encoding="utf-8"))["responses"][0]
    assert (item["score"], item["grader"]["score"], item["grader"]["model"]) == (1, 0.25, "claude-opus-5-5")
