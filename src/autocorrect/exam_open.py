"""Grade the open answers of pexams exams (``pevaluate exam-open``): one LLM call per answer crop.

Grades are kept in ``open_evaluations.yaml`` (teacher edits there are reused on the next run) and
``open_scores.csv``; ``needs_review.csv`` lists the answers a teacher should check. Reports are in
:mod:`autocorrect.report`, voided questions and overall marks in :mod:`autocorrect.marks`.
"""
import argparse
import csv
import json
import math
import os
import re
from pathlib import Path
from typing import Optional

from autocorrect.common import safe_name, read_csv_rows, to_float, write_yaml
from autocorrect.llm import LLMClient, parse_json_response
from autocorrect.open_results import (
    FEEDBACK_STYLE,
    GRADER_SYSTEM,
    evaluations_yaml_path,
    grader_record,
    image_for_model,
    load_evaluations_yaml,
    load_exam_questions,
    make_grading_client,
    with_model_grade,
    write_evaluations_yaml,
    write_scores_csv,
)
from autocorrect.report import STUDENT_TEXTS, generate_open_response_report
from autocorrect.utils import load_project_dotenv

OPEN_SCORES_FIELDS = [
    "student_id", "student_name", "model_id", "question_id", "question_text", "original_id",
    "crop_path", "context_crop_path", "ink_outside_box", "graded_from", "score", "max_score", "feedback",
    "response_markdown", "conversion_warnings", "confidence", "model_input_path", "evaluations_yaml", "status",
    "grader_model", "grader_effort", "teacher_edited",
]


def _context_crop_path(row: dict, index_csv: str) -> str:
    """The crop with the box and its surroundings, for answers with writing outside the box
    (pexams ``ink_outside_box=yes``); empty otherwise."""
    if str(row.get("ink_outside_box", "")).strip().lower() != "yes" or not row.get("context_crop_path"):
        return ""
    path = _resolve_crop_path(row, index_csv, key="context_crop_path")
    return path if os.path.exists(path) else ""


def _highlight_answer_box(context_path: str, box: str, output_dir: str, row: dict) -> str:
    """Outline the answer box in red on the context crop (``box`` = "x,y,width,height" pixels):
    the image the model grades, and the one kept in model_inputs/ for the report."""
    marked_dir = os.path.join(output_dir, "model_inputs")
    os.makedirs(marked_dir, exist_ok=True)
    marked_path = os.path.join(marked_dir, f"{_artifact_stem(row)}.png")
    try:
        from PIL import Image, ImageDraw

        image = Image.open(context_path).convert("RGB")
        x, y, w, h = (int(float(v)) for v in str(box).split(","))
        draw = ImageDraw.Draw(image)
        for i in range(max(4, round(image.width * 0.004))):
            draw.rectangle((x - i, y - i, x + w + i, y + h + i), outline=(220, 40, 30))
        image.save(marked_path)
        return marked_path
    except Exception:
        return context_path


def _resolve_crop_path(row: dict, index_csv: str, key: str = "crop_path") -> str:
    crop_path = row.get(key, "")
    if os.path.isabs(crop_path):
        return crop_path
    relative_to_index = os.path.abspath(os.path.join(os.path.dirname(index_csv), crop_path))
    # Older pexams versions wrote paths relative to the working directory of the correction.
    if not os.path.exists(relative_to_index) and os.path.exists(crop_path):
        return os.path.abspath(crop_path)
    return relative_to_index


OUTSIDE_BOX_NOTE = (
    "The image shows the answer box (outlined in red) and its surroundings, because the student also wrote "
    "outside the box. Everything the student wrote next to or below the box that continues this answer is "
    "part of it: transcribe and grade it too. Ignore the printed text of other questions and handwriting "
    "that clearly belongs to another question."
)


def build_open_answer_prompt(question: dict, row: dict, outside_box: bool = False) -> str:
    max_points = row.get("points") or question.get("points") or 1
    expected_answer = question.get("expected_answer") or question.get("explanation") or ""
    rubric = question.get("rubric") or ""
    outside = f"\n{OUTSIDE_BOX_NOTE}\n" if outside_box else ""

    return f"""Grade this handwritten open-answer exam response.
{outside}
{FEEDBACK_STYLE}

Return only valid JSON with this shape:
{{
  "score": <number from 0 to {max_points}>,
  "max_score": {max_points},
  "feedback": "<one short sentence (at most 20 words), in the language of the student's response, saying only what is missing or wrong; 'Correcto.' if nothing is; empty if the answer is blank>",
  "response_markdown": "<student response transcribed to Markdown, preserving $math$, `code`, and Mermaid diagrams when possible>",
  "conversion_warnings": ["<short warning for any content that could not be converted to Markdown>"],
  "confidence": <number from 0 to 1>
}}

Question:
{question.get("text", "")}

Expected answer:
{expected_answer}

Rubric:
{rubric}

Student:
{row.get("student_id", "")} {row.get("student_name", "")}
"""


def _evaluate_with_llm(client, model: str, prompt: str, crop_path: str, context: Optional[dict] = None,
                       max_image_width: Optional[int] = 900) -> dict:
    """``client`` is any object with ``complete(prompt, images=(), **kwargs) -> (text, meta)``,
    such as ``autocorrect.llm.LLMClient``. ``model`` is unused (the client carries it)."""
    text, meta = client.complete(
        prompt, images=[image_for_model(crop_path, max_image_width)], system=GRADER_SYSTEM,
        json_output=True, purpose="grade_open_answer", context=context,
    )
    result = parse_json_response(text)
    # The model's own score and feedback stay in the grader block (teacher edits change only the top level).
    result["grader"] = with_model_grade(grader_record(meta), result)
    return result


def _artifact_stem(row: dict) -> str:
    return f"{safe_name(row.get('student_id', 'student'))}_q_{safe_name(row.get('question_id', 'question'))}"


def _coerce_result(result: dict, base_result: dict) -> dict:
    warnings = result.get("conversion_warnings", [])
    if isinstance(warnings, str):
        warnings = [warnings] if warnings else []
    if warnings is None:
        warnings = []
    return {
        "score": result.get("score", ""),
        "max_score": result.get("max_score", base_result.get("max_score", "")),
        "feedback": result.get("feedback", ""),
        "response_markdown": result.get("response_markdown", ""),
        "conversion_warnings": warnings,
        "confidence": result.get("confidence", ""),
        "grader": result.get("grader") or {},
        # "context" when the model saw the box with its surroundings (writing outside the box)
        "graded_from": result.get("graded_from") or "box",
    }


def _highlight_model_input(crop_path: str, output_dir: str, row: dict) -> str:
    marked_dir = os.path.join(output_dir, "model_inputs")
    os.makedirs(marked_dir, exist_ok=True)
    marked_path = os.path.join(marked_dir, f"{_artifact_stem(row)}.png")
    try:
        from PIL import Image, ImageDraw, ImageFont

        source = Image.open(crop_path).convert("RGB")
        width, height = source.size
        label_height = max(22, round(height * 0.08))
        image = Image.new("RGB", (width, height + label_height), "white")
        image.paste(source, (0, label_height))
        draw = ImageDraw.Draw(image)
        border = max(6, round(min(width, height) * 0.02))
        for i in range(border):
            draw.rectangle((i, label_height + i, width - 1 - i, label_height + height - 1 - i), outline=(220, 40, 30))
        try:
            font = ImageFont.truetype("arial.ttf", max(11, round(width * 0.014)))
        except Exception:
            font = None
        label = "Model input crop"
        label_width = min(width, 170)
        draw.rectangle((0, 0, label_width, label_height), fill=(220, 40, 30))
        draw.text((6, max(3, round(label_height * 0.18))), label, fill="white", font=font)
        image.save(marked_path)
        return marked_path
    except Exception:
        return crop_path


def _model_input_path(output_dir: str, row: dict, model_input_dir: Optional[str] = None) -> str:
    """The highlighted crop kept in model_inputs/ (reused from ``model_input_dir`` if it exists there)."""
    if model_input_dir:
        existing_path = os.path.join(model_input_dir, f"{_artifact_stem(row)}.png")
        if os.path.exists(existing_path):
            return existing_path
    return _highlight_model_input(row.get("crop_path", ""), output_dir, row)


def _read_existing_result(output_dir: str, row: dict) -> Optional[dict]:
    return load_evaluations_yaml(output_dir).get((str(row.get("student_id", "")), str(row.get("question_id", ""))))


def _open_client(model, effort, api_key_env, output_dir, index_csv, exam_dir):
    """The grading client, or None without an API key: responses already graded in the YAML
    (e.g. after manual edits) can still be reused to rebuild the reports; the error is raised
    only if something needs grading."""
    try:
        return make_grading_client(model, effort, api_key_env, output_dir, "pevaluate exam-open",
                                   inputs=[index_csv], extra={"exam_dir": os.path.abspath(exam_dir)})
    except RuntimeError as e:
        print(f"Warning: {e}")
        return None


def _base_result(row: dict, question: Optional[dict], crop_path: str, context_path: str) -> dict:
    """The fields of a result row that come from the index and the question, not from grading."""
    return {
        "student_id": row.get("student_id", ""),
        "student_name": row.get("student_name", ""),
        "model_id": str(row.get("model_id", "")),
        "question_id": str(row.get("question_id", "")),
        "question_text": (question or {}).get("text", ""),
        "original_id": row.get("original_id", ""),
        "crop_path": crop_path,
        "context_crop_path": context_path,
        "ink_outside_box": row.get("ink_outside_box", ""),
        "layout_check": row.get("layout_check", ""),
        "max_score": row.get("points", "") or (question or {}).get("points", ""),
    }


def _empty_result(base_result: dict, feedback: str = "") -> dict:
    return {"score": "", "max_score": base_result["max_score"], "feedback": feedback, "response_markdown": "",
            "conversion_warnings": [], "confidence": ""}


def _grade_response(row, question, base_result, context_path, model_image, prompt, *, output_dir, client, model,
                    dry_run, force_regrade, regrade_outside_box, max_image_width) -> tuple[dict, str]:
    """``(result, status)``: the saved grade (``cached``, teacher edits included), or a new one
    from the model (``graded``), or ``pending`` (dry run) / ``error``."""
    existing_result = None if force_regrade else _read_existing_result(output_dir, row)
    if (existing_result is not None and regrade_outside_box and context_path
            and (existing_result.get("graded_from") or "box") != "context"):
        existing_result = None  # graded from the box alone, before its overflow was seen
    if existing_result is not None:
        return _coerce_result(existing_result, base_result), "cached"
    if dry_run:
        return _empty_result(base_result), "pending"
    try:
        if client is None:
            raise RuntimeError("No API key found for the grading model. Use --dry-run to prepare prompts without grading.")
        graded = _evaluate_with_llm(client, model, prompt, model_image,
                                    context={"student_id": base_result["student_id"],
                                             "question_id": base_result["question_id"]},
                                    max_image_width=max_image_width)
        graded["graded_from"] = "context" if context_path else "box"
        return _coerce_result(graded, base_result), "graded"
    except Exception as e:
        return _empty_result(base_result, str(e)), "error"


def _result_row(base_result: dict, result: dict, status: str, model_input_path: str, output_dir: str) -> dict:
    return {
        **base_result,
        "score": result.get("score", ""),
        "max_score": result.get("max_score", base_result["max_score"]),
        "feedback": result.get("feedback", ""),
        "response_markdown": result.get("response_markdown", ""),
        "conversion_warnings": "; ".join(result.get("conversion_warnings", []) or []),
        "confidence": result.get("confidence", ""),
        "grader": result.get("grader") or {},
        "graded_from": result.get("graded_from") or "box",
        "model_input_path": model_input_path,
        "evaluations_yaml": evaluations_yaml_path(output_dir),
        "status": status,
    }


def _write_outputs(output_dir: str, result_rows: list[dict]) -> str:
    """``open_evaluations.yaml``, ``needs_review.csv`` and ``open_scores.csv``."""
    write_evaluations_yaml(output_dir, result_rows)
    for row in result_rows:
        row["teacher_edited"] = "yes" if _teacher_edited(row) else "no"
    write_needs_review_csv(result_rows, output_dir)
    return write_scores_csv(output_dir, result_rows, OPEN_SCORES_FIELDS)


def evaluate_open_responses(
    index_csv: str,
    exam_dir: str,
    output_dir: str,
    model: str = "claude-opus-5-5",
    dry_run: bool = False,
    keep_prompts: bool = False,
    force_regrade: bool = False,
    model_input_dir: Optional[str] = None,
    client=None,
    effort: Optional[str] = None,
    api_key_env: Optional[str] = None,
    max_image_width: Optional[int] = 900,
    regrade_outside_box: bool = False,
) -> str:
    """Grade every crop of the pexams index (reusing grades already in open_evaluations.yaml).

    Answers with writing outside their box (pexams ``ink_outside_box=yes``) are graded from the
    context crop with the box outlined. ``regrade_outside_box`` regrades only those that were
    graded from the box alone (e.g. before pexams detected the overflow); ``force_regrade``
    regrades everything and discards teacher edits. Also writes ``needs_review.csv``.
    """
    os.makedirs(output_dir, exist_ok=True)
    prompts_dir = os.path.join(output_dir, "prompts")
    if keep_prompts:
        os.makedirs(prompts_dir, exist_ok=True)

    questions_by_model = load_exam_questions(exam_dir)
    rows = read_csv_rows(index_csv)
    if not dry_run and client is None:
        client = _open_client(model, effort, api_key_env, output_dir, index_csv, exam_dir)

    result_rows = []
    for row in rows:
        question = questions_by_model.get(str(row.get("model_id", "")), {}).get(str(row.get("question_id", "")))
        crop_path = _resolve_crop_path(row, index_csv)
        context_path = _context_crop_path(row, index_csv)
        base_result = _base_result(row, question, crop_path, context_path)

        if question is None:
            result_rows.append({**base_result, "score": "", "feedback": "Question metadata not found.", "response_markdown": "", "conversion_warnings": "", "confidence": "", "status": "missing_question"})
            continue
        if not os.path.exists(crop_path):
            result_rows.append({**base_result, "score": "", "feedback": "Crop image not found.", "response_markdown": "", "conversion_warnings": "", "confidence": "", "status": "missing_crop"})
            continue

        # Writing outside the box: the model sees the box (outlined) with its surroundings.
        model_image = _highlight_answer_box(context_path, row.get("context_box", ""), output_dir, row) if context_path else crop_path
        prompt = build_open_answer_prompt(question, row, outside_box=bool(context_path))
        if keep_prompts:
            prompt_path = os.path.join(prompts_dir, f"{safe_name(row.get('student_id', 'student'))}_q_{safe_name(base_result['question_id'])}.md")
            Path(prompt_path).write_text(prompt, encoding="utf-8")

        result, status = _grade_response(
            row, question, base_result, context_path, model_image, prompt, output_dir=output_dir, client=client,
            model=model, dry_run=dry_run, force_regrade=force_regrade, regrade_outside_box=regrade_outside_box,
            max_image_width=max_image_width)

        if context_path:
            model_input_path = model_image
        else:
            model_input_path = _model_input_path(output_dir, {**row, "crop_path": crop_path}, model_input_dir)
        if status == "graded":
            # Save progress after every new grade, so an interrupted run loses nothing.
            write_evaluations_yaml(output_dir, result_rows + [{**base_result, **result, "status": status}])
        result_rows.append(_result_row(base_result, result, status, model_input_path, output_dir))

    return _write_outputs(output_dir, result_rows)


REVIEW_MIN_CONFIDENCE = 0.75
# Grader warnings that point at something a teacher should look at (any language the model uses).
_REVIEW_WARNING = re.compile(
    r"blank|empty|vac[ií]|en blanco|cut|cortad|truncat|illegible|ilegible|unreadable|faint|tenue|"
    r"margin|margen|outside|fuera|edge|borde", re.IGNORECASE)


def _teacher_edited(row: dict) -> bool:
    """True if the score or feedback differ from the model's own (kept in the grader block)."""
    grader = row.get("grader") or {}
    if "score" not in grader:
        return False
    try:
        same_score = math.isclose(float(grader.get("score")), float(row.get("score")))
    except (TypeError, ValueError):
        same_score = str(grader.get("score")) == str(row.get("score"))
    return not same_score or str(grader.get("feedback", "")).strip() != str(row.get("feedback", "")).strip()


def _review_reasons(row: dict) -> list[str]:
    reasons = []
    if row.get("status") not in ("graded", "cached"):
        reasons.append(f"not graded ({row.get('status')})")
    if row.get("layout_check") == "box_not_found":
        reasons.append("the crop does not match the printed box")
    if str(row.get("ink_outside_box", "")).lower() == "yes" and (row.get("graded_from") or "box") != "context":
        reasons.append("writing outside the box not seen by the grader (rerun with --regrade-outside-box)")
    confidence = to_float(row.get("confidence"))
    if confidence is not None and confidence < REVIEW_MIN_CONFIDENCE:
        reasons.append(f"low confidence ({confidence:.2f})")
    warnings = [w.strip() for w in str(row.get("conversion_warnings", "")).split(";") if w.strip()]
    flagged = [w for w in warnings if _REVIEW_WARNING.search(w)]
    if flagged:
        reasons.append("grader warning: " + flagged[0][:160])
    return reasons


def write_needs_review_csv(result_rows: list[dict], output_dir: str) -> str:
    """``needs_review.csv``: the answers a teacher should look at before publishing (not graded,
    crop off the box, writing outside the box not seen, low confidence, warnings about blank, cut
    or illegible text), with the reasons and the images to check. Answers the teacher already
    edited are left out."""
    path = os.path.join(output_dir, "needs_review.csv")
    fields = ["student_id", "student_name", "question_id", "original_id", "score", "max_score", "confidence",
              "reasons", "crop_path", "context_crop_path", "model_input_path"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in result_rows:
            reasons = _review_reasons(row)
            if reasons and not _teacher_edited(row):
                writer.writerow({**row, "reasons": " | ".join(reasons)})
    return path


def _post_analysis_yaml_path(output_dir: str) -> str:
    return os.path.join(output_dir, "post_analysis.yaml")


def _reevaluation_output_dir(output_dir: str) -> str:
    path = Path(output_dir)
    if path.name.lower() == "evaluation":
        return str(path.parent / "reevaluation")
    return str(path / "reevaluation")


def run_post_analysis(scores_csv: str, output_dir: str, model: str = "claude-opus-5-5", force: bool = False, client=None,
                      effort: Optional[str] = "medium", api_key_env: Optional[str] = None) -> str:
    output_path = _post_analysis_yaml_path(output_dir)
    if os.path.exists(output_path) and not force:
        return output_path
    os.makedirs(output_dir, exist_ok=True)

    rows = read_csv_rows(scores_csv)
    responses = [
        {
            "question_id": row.get("question_id", ""),
            "score": row.get("score", ""),
            "max_score": row.get("max_score", ""),
            "response_markdown": row.get("response_markdown", ""),
            "feedback": row.get("feedback", ""),
        }
        for row in rows
    ]

    if client is None:
        load_project_dotenv()
        client = LLMClient(model, effort=effort, api_key_env=api_key_env,
                           log_path=os.path.join(output_dir, "llm_calls.jsonl"), tool="pevaluate")

    prompt = (
        "Analyze these graded open-answer exam responses. Return JSON with keys "
        "typical_errors (list of strings), suggested_rubric_markdown (string), "
        "and notes (string).\n\n"
        + json.dumps(responses, ensure_ascii=False)
    )
    text, _ = client.complete(prompt, system="You help teachers analyze graded exam responses.",
                              json_output=True, purpose="post_analysis")
    data = parse_json_response(text)
    payload = {
        "source_scores_csv": os.path.abspath(scores_csv),
        "responses_count": len(rows),
        "typical_errors": data.get("typical_errors", []),
        "notes": data.get("notes", ""),
        "suggested_rubric_markdown": data.get("suggested_rubric_markdown", ""),
    }
    write_yaml(output_path, payload)
    return output_path


DESCRIPTION = "Grade pexams open-answer response crops with an LLM."


def build_parser(parser: Optional[argparse.ArgumentParser] = None) -> argparse.ArgumentParser:
    parser = parser or argparse.ArgumentParser(prog="pevaluate exam-open", description=DESCRIPTION)
    parser.add_argument("--index-csv", required=True, help="Path to pexams open_responses_index.csv.")
    parser.add_argument("--exam-dir", required=True, help="Directory containing exam_model_*_questions.json.")
    parser.add_argument("--output-dir", required=True, help="Directory for open_scores.csv, prompts, and feedback.")
    parser.add_argument("--model", default="claude-opus-5-5", help="Grading model. Bare 'claude-...' ids use the Anthropic API; others (e.g. google/gemini-3.1-pro-preview) use OpenRouter.")
    parser.add_argument("--effort", default="medium", help="Reasoning effort (low/medium/high); empty for the provider default.")
    parser.add_argument("--api-key-env", default=None, help="Environment variable holding the API key (default: ANTHROPIC_API_KEY or OPENROUTER_API_KEY).")
    parser.add_argument("--max-image-width", type=int, default=900, help="Downscale crops to this width in pixels before sending them (0 = original size). Fewer image tokens, same grades in our tests.")
    parser.add_argument("--dry-run", action="store_true", help="Write prompts and pending score rows without calling an LLM.")
    parser.add_argument("--keep-prompts", "--keep-prompt", dest="keep_prompts", action="store_true", help="Save generated grading prompts.")
    parser.add_argument("--force-regrade", action="store_true", help="Ignore the grades saved in open_evaluations.yaml (teacher edits included) and call the model again.")
    parser.add_argument("--post-analysis", action="store_true", help="Analyze graded responses and suggest rubric refinements.")
    parser.add_argument("--re-evaluate", action="store_true", help="Reserved for regrading with a revised rubric after post-analysis.")
    parser.add_argument("--mc-correction-dir", help="Optional pexams correction-results directory to merge multiple-choice feedback into per-student PDFs.")
    parser.add_argument("--student-converted-response", action="store_true", help="Also include the transcribed (converted) response in the per-student feedback PDFs. Off by default; the global report always includes it.")
    parser.add_argument("--void-questions", default=None, help="Comma-separated open questions (exam number or original id) removed for everyone. Void multiple-choice questions with pexams --void-questions.")
    parser.add_argument("--void-questions-nicely", default=None, help="Comma-separated open questions that count for a student only if they raise the student's overall mark (multiple choice from --mc-correction-dir included). Void multiple-choice questions with pexams --void-questions-nicely.")
    parser.add_argument("--regrade-outside-box", action="store_true", help="Regrade only the answers with writing outside their box (pexams ink_outside_box=yes) that were graded from the box alone; other grades and teacher edits are kept.")
    parser.add_argument("--lang", default="en", choices=sorted(STUDENT_TEXTS), help="Language of the per-student feedback PDFs (default: en).")
    return parser


def run(args: argparse.Namespace):
    llm_options = dict(model=args.model, effort=args.effort or None, api_key_env=args.api_key_env)
    output_csv = evaluate_open_responses(
        index_csv=args.index_csv,
        exam_dir=args.exam_dir,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
        keep_prompts=args.keep_prompts,
        force_regrade=args.force_regrade,
        max_image_width=args.max_image_width or None,
        regrade_outside_box=args.regrade_outside_box,
        **llm_options,
    )
    report_path = generate_open_response_report(output_csv, args.output_dir, mc_correction_dir=args.mc_correction_dir,
                                                student_converted_response=args.student_converted_response,
                                                void_questions=args.void_questions,
                                                void_questions_nicely=args.void_questions_nicely,
                                                lang=args.lang)
    print(f"Open-answer scores saved to: {output_csv}")
    print(f"Open-answer report saved to: {report_path}")
    if not (args.post_analysis or args.re_evaluate):
        return
    reeval_dir = _reevaluation_output_dir(args.output_dir)
    analysis_path = run_post_analysis(output_csv, reeval_dir if args.re_evaluate else args.output_dir,
                                      force=args.force_regrade, **llm_options)
    print(f"Post-analysis saved to: {analysis_path}")
    if args.re_evaluate:
        reeval_csv = evaluate_open_responses(
            index_csv=args.index_csv,
            exam_dir=args.exam_dir,
            output_dir=reeval_dir,
            dry_run=args.dry_run,
            keep_prompts=args.keep_prompts,
            force_regrade=args.force_regrade,
            model_input_dir=os.path.join(args.output_dir, "model_inputs"),
            max_image_width=args.max_image_width or None,
            **llm_options,
        )
        reeval_report = generate_open_response_report(reeval_csv, reeval_dir, title="Open-Answer Re-Evaluation Report", mc_correction_dir=args.mc_correction_dir,
                                                      student_converted_response=args.student_converted_response)
        print(f"Re-evaluation scores saved to: {reeval_csv}")
        print(f"Re-evaluation report saved to: {reeval_report}")


def main(argv: Optional[list[str]] = None):
    run(build_parser().parse_args(argv))
