"""Offline smoke test of the open-answer pipeline (``pevaluate test-open``): fake crops, a fake
multiple-choice correction and a deterministic stand-in for the LLM, then grading, post-analysis,
re-evaluation and reports, as with real scans."""
import argparse
import base64
import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from autocorrect.exam_open import evaluate_open_responses, run_post_analysis
from autocorrect.report import _write_pdf_from_html, generate_open_response_report


class _SmokeClient:
    """Offline stand-in for ``autocorrect.llm.LLMClient``: same ``complete`` signature,
    deterministic canned answers."""

    def __init__(self):
        self.calls = 0

    @staticmethod
    def _meta() -> dict:
        return {"provider": "smoke", "model_requested": "smoke", "model_served": "smoke", "effort": None}

    def complete(self, prompt, images=(), **kwargs):
        if "Analyze these graded open-answer exam responses" in prompt:
            return json.dumps({
                "typical_errors": ["Some answers mention overfitting but omit validation performance."],
                "suggested_rubric_markdown": "4 points: 2 complexity penalty, 1 overfitting/generalization, 1 train-validation contrast.",
                "notes": "The original rubric is mostly aligned.",
            }), self._meta()
        samples = [
            (0.5, "Needs the core idea of regularization.", "Regularization changes the model.\n\nI am not sure how.", ["Handwriting had one unclear word."]),
            (2.0, "Mentions overfitting but misses validation.", "Regularization reduces overfitting.\n\nIt adds a penalty $\\lambda\\|w\\|^2$ to discourage large weights.", []),
            (3.0, "Good answer; mention validation performance more explicitly.", "Regularization reduces overfitting by penalizing complex models.\n\n```mermaid\ngraph LR\n    Complex[Complex model] --> Penalty[Penalty term]\n    Penalty --> Generalization[Better generalization]\n```\n\nIt may lower training score but improve validation performance.", []),
            (4.0, "Complete and precise.", "Regularization adds a penalty $\\lambda$ to model complexity.\n\nTraining may go down while validation improves.", []),
        ]
        score, feedback, response_md, warnings = samples[self.calls % len(samples)]
        self.calls += 1
        return json.dumps({
            "score": score,
            "max_score": 4,
            "feedback": feedback,
            "response_markdown": response_md,
            "conversion_warnings": warnings,
            "confidence": 0.85,
        }), self._meta()


def _write_smoke_png(path: str, lines: list[str]):
    try:
        from PIL import Image, ImageDraw
        from PIL import ImageFont

        image = Image.new("RGB", (900, 260), "white")
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype("arial.ttf", 18)
        except Exception:
            font = None
        y = 28
        for line in lines:
            draw.text((24, y), line, fill="black", font=font)
            y += 34
        image.save(path)
    except Exception:
        Path(path).write_bytes(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAAC0lEQVR4nGNg+A8AAwMBAY+ip1sAAAAASUVORK5CYII="
            )
        )


def _write_smoke_scan_page(path: str, student_id: str, student_name: str, score: float):
    try:
        from PIL import Image, ImageDraw
        from PIL import ImageFont

        image = Image.new("RGB", (1654, 2339), "white")
        draw = ImageDraw.Draw(image)
        try:
            title_font = ImageFont.truetype("arial.ttf", 44)
            body_font = ImageFont.truetype("arial.ttf", 28)
        except Exception:
            title_font = None
            body_font = None
        draw.rectangle((90, 100, 1564, 360), outline="black", width=4)
        draw.text((130, 150), "Corrected Multiple-Choice Template", fill="black", font=title_font)
        draw.text((130, 230), f"Student: {student_name} ({student_id})", fill="black", font=body_font)
        draw.text((130, 290), f"Score: {score:.2f}/3.00", fill="black", font=body_font)
        y = 460
        for question_no in range(1, 4):
            draw.rectangle((140, y, 1514, y + 320), outline="#334155", width=3)
            draw.text((180, y + 40), f"Question {question_no}", fill="black", font=body_font)
            draw.text((180, y + 120), "Detected answer and correction preview", fill="#475569", font=body_font)
            draw.line((920, y + 70, 1320, y + 70), fill="#16a34a", width=8)
            draw.line((920, y + 140, 1320, y + 140), fill="#dc2626", width=8)
            y += 420
        image.save(path)
    except Exception:
        _write_smoke_png(path, [student_name, "MC correction placeholder"])


def _write_smoke_mc_report(mc_dir: str, students: list[tuple[str, str, float, list[str]]]):
    scans_dir = os.path.join(mc_dir, "scanned_pages")
    os.makedirs(scans_dir, exist_ok=True)
    for student_id, student_name, mc_score, _lines in students:
        _write_smoke_scan_page(os.path.join(scans_dir, f"{student_id}.png"), student_id, student_name, mc_score)

    _write_smoke_png(
        os.path.join(mc_dir, "mark_distribution_0_10.png"),
        ["Mark distribution", "MC smoke artifact"],
    )
    stats_html_path = os.path.join(mc_dir, "stats_report.html")
    Path(stats_html_path).write_text(
        "<!doctype html><html><body><h1>Exam Statistics Report</h1><p>Deterministic MC smoke report generated by pevaluate.</p><h2>Question Analysis</h2><p>Placeholder question analysis for smoke testing.</p></body></html>",
        encoding="utf-8",
    )
    _write_pdf_from_html(stats_html_path, os.path.join(mc_dir, "stats_report.pdf"))
    with open(os.path.join(mc_dir, "final_marks.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["student_id", "student_name", "score", "max_score", "correct", "incorrect", "NA", "mark"])
        writer.writeheader()
        for student_id, student_name, mc_score, _lines in students:
            writer.writerow({
                "student_id": student_id,
                "student_name": student_name,
                "score": mc_score,
                "max_score": 3,
                "correct": int(mc_score),
                "incorrect": 3 - int(mc_score),
                "NA": 0,
                "mark": round((mc_score / 3) * 10, 2),
            })


def run_open_answer_smoke_test(output_dir: Optional[str] = None, real_llm: bool = False, model: str = "claude-opus-5-5") -> str:
    root = output_dir or tempfile.mkdtemp(prefix="pevaluate_open_smoke_")
    os.makedirs(root, exist_ok=True)
    exam_dir = os.path.join(root, "exam")
    crops_dir = os.path.join(root, "open_responses")
    eval_dir = os.path.join(root, "evaluation")
    mc_dir = os.path.join(root, "mc_correction")
    mc_scans_dir = os.path.join(mc_dir, "scanned_pages")
    os.makedirs(exam_dir, exist_ok=True)
    os.makedirs(crops_dir, exist_ok=True)
    os.makedirs(mc_scans_dir, exist_ok=True)

    Path(os.path.join(exam_dir, "exam_model_1_questions.json")).write_text(
        json.dumps({
            "questions": [
                {
                    "id": 2,
                    "question_type": "open_answer",
                    "text": "Explain why regularization with a penalty λ can improve generalization.",
                    "points": 4,
                    "expected_answer": "Regularization uses a penalty λ to discourage overly complex models and can reduce overfitting.",
                    "rubric": "2 points for model complexity, 1 for overfitting/generalization, 1 for train/validation contrast.",
                }
            ]
        }, indent=2),
        encoding="utf-8",
    )
    index_csv = os.path.join(root, "open_responses_index.csv")
    with open(index_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["student_id", "student_name", "model_id", "question_id", "original_id", "points", "crop_path"],
        )
        writer.writeheader()
        smoke_students = [
            ("student-1", "Student One", 1.0, ["Regularization changes the model.", "I am not sure how."]),
            ("student-2", "Student Two", 2.0, ["Regularization reduces overfitting.", "It adds λ||w||² to penalize large weights."]),
            ("student-3", "Student Three", 3.0, ["Regularization reduces overfitting by penalizing complex models.", "complex model → penalty → better validation"]),
            ("student-4", "Student Four", 3.0, ["Regularization adds a penalty λ to model complexity.", "Training may go down while validation improves."]),
        ]
        _write_smoke_mc_report(mc_dir, smoke_students)

        for student_id, student_name, _mc_score, lines in smoke_students:
            crop_path = os.path.join(crops_dir, f"{student_id}_model_1_q_2.png")
            _write_smoke_png(crop_path, lines)
            writer.writerow({
                "student_id": student_id,
                "student_name": student_name,
                "model_id": "1",
                "question_id": "2",
                "original_id": "open_regularization",
                "points": "4",
                "crop_path": crop_path,
            })

    client = None if real_llm else _SmokeClient()
    scores_csv = evaluate_open_responses(
        index_csv=index_csv,
        exam_dir=exam_dir,
        output_dir=eval_dir,
        model=model,
        client=client,
        force_regrade=True,
    )
    reeval_dir = os.path.join(root, "reevaluation")
    run_post_analysis(scores_csv, reeval_dir, model=model, force=True, client=client)
    evaluate_open_responses(
        index_csv=index_csv,
        exam_dir=exam_dir,
        output_dir=reeval_dir,
        model=model,
        client=client,
        force_regrade=True,
        model_input_dir=os.path.join(eval_dir, "model_inputs"),
    )
    generate_open_response_report(os.path.join(reeval_dir, "open_scores.csv"), reeval_dir, title="Open-Answer Re-Evaluation Report", mc_correction_dir=mc_dir)
    generate_open_response_report(scores_csv, eval_dir, mc_correction_dir=mc_dir)
    return eval_dir


DESCRIPTION = "Run a small open-answer evaluation smoke test (offline by default)."


def build_parser(parser: Optional[argparse.ArgumentParser] = None) -> argparse.ArgumentParser:
    parser = parser or argparse.ArgumentParser(prog="pevaluate test-open", description=DESCRIPTION)
    parser.add_argument("--output-dir", help="Directory where smoke artifacts will be written.")
    parser.add_argument("--real-llm", action="store_true", help="Call the real grading model (--model) instead of the built-in fake client. This burns tokens.")
    parser.add_argument("--model", default="claude-opus-5-5", help="Model for --real-llm.")
    return parser


def run(args: argparse.Namespace):
    output_dir = run_open_answer_smoke_test(args.output_dir, real_llm=args.real_llm, model=args.model)
    print(f"Open-answer smoke artifacts saved to: {output_dir}")


def main(argv: Optional[list[str]] = None):
    run(build_parser().parse_args(argv))

