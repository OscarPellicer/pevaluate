"""Shared by ``exam-open`` and ``exam-free``: exam questions, the grading client, the grader
record, and the ``open_evaluations.yaml`` / ``open_scores.csv`` files that the reports read."""
import csv
import json
import os
import re
from pathlib import Path
from typing import Dict, Optional

import yaml
from autocorrect.common import write_yaml
from autocorrect.llm import LLMClient, write_run_manifest
from autocorrect.utils import load_project_dotenv

GRADER_SYSTEM = "You are an assistant helping a teacher grade open-answer exam responses."

FEEDBACK_STYLE = (
    "Write the feedback impersonally, in the passive voice (e.g. 'the threshold is correctly justified', "
    "'se identifica bien el umbral'), not addressing the student as 'you' and not as 'the student'. "
    "The feedback goes to the student as if written by the teacher: never mention the image, the scan, "
    "the crop, the box, the transcription, legibility, a review or that the grading is automatic (put any "
    "such remark in conversion_warnings instead). If nothing was written (a blank box, or only stray marks "
    "or traces of erased writing), the score is 0 and the feedback is an empty string."
)


def load_exam_questions(exam_dir: str) -> Dict[str, Dict[str, dict]]:
    """``{model id: {question id: question}}`` from pexams ``exam_model_*_questions.json``."""
    questions_by_model: Dict[str, Dict[str, dict]] = {}
    for path in Path(exam_dir).glob("exam_model_*_questions.json"):
        match = re.match(r"exam_model_(.+)_questions\.json$", path.name)
        if not match:
            continue
        model_id = match.group(1)
        payload = json.loads(path.read_text(encoding="utf-8"))
        questions = payload.get("questions", [])
        questions_by_model[model_id] = {str(q.get("id")): q for q in questions}
    return questions_by_model


def make_grading_client(model: str, effort: Optional[str], api_key_env: Optional[str], output_dir: str,
                        command: str, inputs: list, extra: dict) -> LLMClient:
    """The LLM client (calls logged to ``llm_calls.jsonl``) and the run manifest."""
    load_project_dotenv()
    client = LLMClient(model, effort=effort, api_key_env=api_key_env,
                       log_path=os.path.join(output_dir, "llm_calls.jsonl"), tool="pevaluate")
    write_run_manifest(output_dir, command, client, inputs=inputs, extra=extra)
    return client


def grader_record(meta: dict) -> dict:
    """The provenance kept next to each graded response."""
    return {
        "provider": meta.get("provider"),
        "model": meta.get("model_served") or meta.get("model_requested"),
        "model_requested": meta.get("model_requested"),
        "effort": meta.get("effort"),
        "fallback_used": meta.get("fallback_used"),
        "request_id": meta.get("request_id"),
        "graded_at_utc": meta.get("timestamp_utc"),
        "tool_version": meta.get("tool_version"),
    }


def with_model_grade(record: dict, answer: dict) -> dict:
    """The grader block plus the model's own score and feedback, so teacher edits to the
    top-level fields can be measured later (human-vs-LLM agreement)."""
    return {**record, "score": answer.get("score"), "feedback": answer.get("feedback")}


def image_for_model(path: str, max_width: Optional[int] = 900) -> tuple[bytes, str]:
    """Grayscale PNG no wider than ``max_width`` pixels. Image tokens grow with the pixel
    count, and handwriting stays legible at ~900 px for a full-width answer box."""
    from io import BytesIO
    from PIL import Image

    image = Image.open(path).convert("L")
    if max_width and image.width > max_width:
        image = image.resize((max_width, round(image.height * max_width / image.width)), Image.LANCZOS)
    buffer = BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return buffer.getvalue(), "image/png"


def evaluations_yaml_path(output_dir: str) -> str:
    return os.path.join(output_dir, "open_evaluations.yaml")


def load_evaluations_yaml(output_dir: str) -> Dict[tuple[str, str], dict]:
    """Saved grades (with any teacher edits), keyed by ``(student_id, question_id)``."""
    path = evaluations_yaml_path(output_dir)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        payload = yaml.safe_load(f) or {}
    items = payload.get("responses", []) if isinstance(payload, dict) else []
    loaded = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("student_id", "")), str(item.get("question_id", "")))
        loaded[key] = item
    return loaded


def write_evaluations_yaml(output_dir: str, result_rows: list[dict]):
    responses = []
    for row in result_rows:
        responses.append({
            "student_id": row.get("student_id", ""),
            "student_name": row.get("student_name", ""),
            "model_id": row.get("model_id", ""),
            "question_id": row.get("question_id", ""),
            "question_text": row.get("question_text", ""),
            "original_id": row.get("original_id", ""),
            "crop_path": row.get("crop_path", ""),
            "model_input_path": row.get("model_input_path", ""),
            "score": row.get("score", ""),
            "max_score": row.get("max_score", ""),
            "feedback": row.get("feedback", ""),
            "response_markdown": row.get("response_markdown", ""),
            "conversion_warnings": [
                warning.strip()
                for warning in str(row.get("conversion_warnings", "")).split(";")
                if warning.strip()
            ],
            "confidence": row.get("confidence", ""),
            "status": row.get("status", ""),
            "graded_from": row.get("graded_from") or "box",
            "grader": row.get("grader") or {},
        })
    write_yaml(evaluations_yaml_path(output_dir), {"responses": responses})


def write_scores_csv(output_dir: str, result_rows: list[dict], fieldnames: list[str]) -> str:
    """``open_scores.csv`` with the given columns; adds ``grader_model``/``grader_effort`` to each row."""
    for row in result_rows:
        grader = row.get("grader") or {}
        row["grader_model"] = grader.get("model", "")
        row["grader_effort"] = grader.get("effort", "")
    output_csv = os.path.join(output_dir, "open_scores.csv")
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result_rows)
    return output_csv
