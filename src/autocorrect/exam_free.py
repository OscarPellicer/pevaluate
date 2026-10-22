"""Grade free-form paper exams: answers written on blank sheets, with no answer boxes.

Each exam (one or more scanned pages) is sent whole to a vision LLM together with every
question, its expected answer and its rubric. The model reads the student's name and ID,
matches each written answer to its question by content (students may number them
differently or not at all) and grades it. The results are written in the same format as
``exam-open`` (``open_scores.csv`` + ``open_evaluations.yaml``), so the same reports and
per-student PDFs are produced, and edits to the YAML are reused on the next run.
"""
import argparse
import csv
import json
import os
from pathlib import Path
from typing import Optional

from autocorrect.exam_open import (
    GRADER_SYSTEM,
    _grader_record,
    image_for_model,
    _load_evaluations_yaml,
    _load_exam_questions,
    _parse_json_response,
    _safe_name,
    _write_evaluations_yaml,
    generate_open_response_report,
    load_project_dotenv,
)
from autocorrect.llm import LLMClient, write_run_manifest


def _render_pages(input_path: str, pages_dir: str, dpi: int) -> list[str]:
    os.makedirs(pages_dir, exist_ok=True)
    if os.path.isdir(input_path):
        return sorted(str(p) for p in Path(input_path).iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg"})
    import pymupdf

    paths = []
    with pymupdf.open(input_path) as doc:
        for i, page in enumerate(doc):
            path = os.path.join(pages_dir, f"page_{i + 1:03d}.png")
            if not os.path.exists(path):
                page.get_pixmap(dpi=dpi).save(path)
            paths.append(path)
    return paths


def build_free_exam_prompt(questions: list[dict]) -> str:
    blocks = []
    for q in questions:
        blocks.append(
            f"### Question {q['id']} (id: {q['id']}, max score: {q.get('points') or 1})\n"
            f"{q.get('text', '')}\n\nExpected answer:\n{q.get('expected_answer') or q.get('explanation') or ''}\n\n"
            f"Rubric:\n{q.get('rubric') or ''}"
        )
    ids = ", ".join(str(q["id"]) for q in questions)
    return f"""The images are the scanned pages of one student's handwritten exam, written on blank paper.

1. Read the student's name and ID number if they are written anywhere (empty string if not).
2. Find the student's answer to each question below. Answers may be numbered differently from
   the question ids (e.g. with the numbering of a longer original exam) or not numbered at all:
   match them by content. If a question has no answer, give score 0 and say so in the feedback.
3. Grade each answer with its rubric.

Return only valid JSON with this shape:
{{
  "student_name": "...",
  "student_id": "...",
  "answers": [
    {{
      "question_id": "<one of: {ids}>",
      "student_label": "<the number the student wrote for this answer, if any>",
      "score": <number from 0 to the question's max score>,
      "max_score": <the question's max score>,
      "feedback": "<one short sentence (at most 20 words), in the language of the student's response, saying only what is missing or wrong; 'Correcto.' if nothing is>",
      "response_markdown": "<the student's answer transcribed to Markdown>",
      "conversion_warnings": ["<short warning for anything unreadable>"],
      "confidence": <number from 0 to 1>
    }}
  ]
}}

Questions:

{chr(10).join(blocks)}
"""


def evaluate_free_exams(
    input_path: str,
    exam_dir: str,
    output_dir: str,
    model: str = "claude-opus-5-5",
    effort: Optional[str] = "medium",
    api_key_env: Optional[str] = None,
    pages_per_exam: int = 1,
    exam_model: str = "1",
    dpi: int = 150,
    dry_run: bool = False,
    force_regrade: bool = False,
    keep_prompts: bool = False,
    max_image_width: Optional[int] = 1240,
    client=None,
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    questions = list(_load_exam_questions(exam_dir).get(str(exam_model), {}).values())
    if not questions:
        raise RuntimeError(f"No questions found for model {exam_model} in {exam_dir}.")
    questions.sort(key=lambda q: int(q["id"]) if str(q["id"]).isdigit() else str(q["id"]))
    pages = _render_pages(input_path, os.path.join(output_dir, "pages"), dpi)
    exams = [pages[i:i + pages_per_exam] for i in range(0, len(pages), pages_per_exam)]
    prompt = build_free_exam_prompt(questions)
    if keep_prompts:
        Path(output_dir, "prompt.md").write_text(prompt, encoding="utf-8")

    cached = {} if force_regrade else _load_evaluations_yaml(output_dir)
    if not dry_run and client is None:
        load_project_dotenv()
        client = LLMClient(model, effort=effort, api_key_env=api_key_env,
                           log_path=os.path.join(output_dir, "llm_calls.jsonl"), tool="pevaluate")
        write_run_manifest(output_dir, "pevaluate exam-free", client, inputs=[input_path],
                           extra={"exam_dir": os.path.abspath(exam_dir), "pages_per_exam": pages_per_exam})

    raw_dir = os.path.join(output_dir, "raw_responses")
    os.makedirs(raw_dir, exist_ok=True)
    result_rows = []
    for index, exam_pages in enumerate(exams, start=1):
        exam_key = f"exam_{index:03d}"
        raw_path = os.path.join(raw_dir, f"{exam_key}.json")
        if not force_regrade and os.path.exists(raw_path):
            data = json.loads(Path(raw_path).read_text(encoding="utf-8"))
        elif dry_run:
            data = {"student_name": "", "student_id": "", "answers": []}
        else:
            text, meta = client.complete(
                prompt, images=[image_for_model(p, max_image_width) for p in exam_pages], system=GRADER_SYSTEM,
                json_output=True, purpose="grade_free_exam", context={"exam": exam_key, "pages": [Path(p).name for p in exam_pages]},
            )
            data = _parse_json_response(text)
            data["grader"] = _grader_record(meta)
            Path(raw_path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        read_id = str(data.get("student_id", "") or "").strip()
        student_id = _safe_name(read_id) if read_id else exam_key
        student_name = str(data.get("student_name", "") or "").strip()
        answers = {str(a.get("question_id")): a for a in data.get("answers", []) if isinstance(a, dict)}
        for q in questions:
            qid = str(q["id"])
            answer = answers.get(qid, {})
            edited = cached.get((student_id, qid))  # manual edits in the YAML win over the raw response
            source = edited if edited is not None else answer
            warnings = source.get("conversion_warnings", []) or []
            if isinstance(warnings, str):
                warnings = [w.strip() for w in warnings.split(";") if w.strip()]
            result_rows.append({
                "student_id": student_id,
                "student_name": student_name,
                "model_id": str(exam_model),
                "question_id": qid,
                "question_text": q.get("text", ""),
                "original_id": q.get("original_id", ""),
                "crop_path": exam_pages[0],
                "model_input_path": exam_pages[0],
                "score": source.get("score", 0 if answer or edited else ""),
                "max_score": source.get("max_score", q.get("points", "")),
                "feedback": source.get("feedback", "" if answer else "No answer found for this question."),
                "response_markdown": source.get("response_markdown", ""),
                "conversion_warnings": "; ".join(warnings),
                "confidence": source.get("confidence", ""),
                "grader": (edited or {}).get("grader") or data.get("grader") or {},
                "pages": [os.path.abspath(p) for p in exam_pages],
                "status": "cached" if edited is not None else ("pending" if dry_run else "graded"),
            })

    _write_evaluations_yaml(output_dir, result_rows)
    output_csv = os.path.join(output_dir, "open_scores.csv")
    fieldnames = [
        "student_id", "student_name", "model_id", "question_id", "question_text", "original_id",
        "crop_path", "score", "max_score", "feedback", "response_markdown",
        "conversion_warnings", "confidence", "model_input_path", "status", "grader_model", "grader_effort",
    ]
    for row in result_rows:
        row["grader_model"] = row["grader"].get("model", "")
        row["grader_effort"] = row["grader"].get("effort", "")
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result_rows)
    return output_csv


def main(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(description="Grade handwritten exams written on blank paper (no answer boxes) with a vision LLM.")
    parser.add_argument("--input-path", required=True, help="Scanned PDF, or a folder of page images in order.")
    parser.add_argument("--exam-dir", required=True, help="pexams exam directory with exam_model_*_questions.json (questions, expected answers, rubrics).")
    parser.add_argument("--output-dir", required=True, help="Directory for open_scores.csv, open_evaluations.yaml and reports.")
    parser.add_argument("--pages-per-exam", type=int, default=1, help="Consecutive pages that form one student's exam.")
    parser.add_argument("--exam-model", default="1", help="Exam model whose questions were answered.")
    parser.add_argument("--model", default="claude-opus-5-5", help="Grading model. Bare 'claude-...' ids use the Anthropic API; others use OpenRouter.")
    parser.add_argument("--effort", default="medium", help="Reasoning effort (low/medium/high); empty for the provider default.")
    parser.add_argument("--api-key-env", default=None, help="Environment variable holding the API key.")
    parser.add_argument("--dpi", type=int, default=150, help="Resolution used to render PDF pages.")
    parser.add_argument("--max-image-width", type=int, default=1240, help="Downscale pages to this width in pixels before sending them (0 = original size).")
    parser.add_argument("--dry-run", action="store_true", help="Render pages and write the prompt without calling the LLM.")
    parser.add_argument("--force-regrade", action="store_true", help="Ignore cached raw responses and YAML edits.")
    parser.add_argument("--keep-prompts", action="store_true", help="Save the grading prompt.")
    parser.add_argument("--student-converted-response", action="store_true", help="Also include the transcription in per-student PDFs.")
    args = parser.parse_args(argv)
    output_csv = evaluate_free_exams(
        args.input_path, args.exam_dir, args.output_dir, model=args.model, effort=args.effort or None,
        api_key_env=args.api_key_env, pages_per_exam=args.pages_per_exam, exam_model=args.exam_model,
        dpi=args.dpi, dry_run=args.dry_run, force_regrade=args.force_regrade, keep_prompts=args.keep_prompts,
        max_image_width=args.max_image_width or None,
    )
    report = generate_open_response_report(output_csv, args.output_dir, title="Free-Form Exam Report",
                                           student_converted_response=args.student_converted_response)
    print(f"Scores saved to: {output_csv}")
    print(f"Report saved to: {report}")
