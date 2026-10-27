"""Marks of open-answer exams: the multiple-choice part read from pexams, voided questions, and
the per-student totals written to ``overall_marks.csv``."""
import csv
import os
from pathlib import Path
from typing import Dict, Optional

from autocorrect.common import read_csv_rows, to_float

# Void statuses (see resolve_question_voids) of questions that do not count.
VOID_EXCLUDED = ("void", "nicely_excluded")


def _find_student_image(directory: str, student_id: str) -> str:
    if not directory or not os.path.isdir(directory):
        return ""
    safe_id = str(student_id).lower()
    for suffix in ("*.png", "*.jpg", "*.jpeg"):
        for path in Path(directory).glob(suffix):
            stem = path.stem.lower()
            if stem == safe_id or safe_id in stem:
                return str(path)
    return ""


def load_mc_feedback_context(mc_correction_dir: Optional[str]) -> Dict[str, dict]:
    if not mc_correction_dir:
        return {}
    correction_dir = os.path.abspath(mc_correction_dir)
    final_rows = read_csv_rows(os.path.join(correction_dir, "final_marks.csv"), optional=True)
    raw_rows = read_csv_rows(os.path.join(correction_dir, "correction_results.csv"), optional=True)
    rows = final_rows or raw_rows
    images_dir = os.path.join(correction_dir, "scanned_pages")
    if not os.path.isdir(images_dir):
        images_dir = correction_dir

    context: Dict[str, dict] = {}
    for row in rows:
        student_id = str(row.get("student_id", "")).strip()
        if not student_id:
            continue
        score = row.get("score", "") or row.get("score_adjusted", "")
        max_score = row.get("max_score", "") or row.get("max_score_adjusted", "") or row.get("total_points", "")
        mark = row.get("mark", "") or row.get("mark_clipped", "")
        context[student_id] = {
            "student_id": student_id,
            "student_name": row.get("student_name", ""),
            "score": score,
            "max_score": max_score,
            "mark": mark,
            "correct": row.get("correct", "") or row.get("correct_count", ""),
            "incorrect": row.get("incorrect", "") or row.get("incorrect_count", ""),
            "na": row.get("NA", "") or row.get("na_count", ""),
            "image_path": _find_student_image(images_dir, student_id),
        }
    if not context and os.path.isdir(images_dir):
        for path in Path(images_dir).glob("*.png"):
            context[path.stem] = {"student_id": path.stem, "image_path": str(path)}
    return context


def student_totals(graded_rows: list[dict]) -> list[dict]:
    grouped: Dict[str, dict] = {}
    for row in graded_rows:
        key = row.get("student_id", "")
        item = grouped.setdefault(
            key,
            {
                "student_id": key,
                "student_name": row.get("student_name", ""),
                "score": 0.0,
                "max_score": 0.0,
                "voided_questions": "",
            },
        )
        if row.get("_void_status") in VOID_EXCLUDED:
            item["voided_questions"] = ",".join(filter(None, [item["voided_questions"], str(row.get("question_id", ""))]))
            continue
        item["score"] += row["_score"]
        item["max_score"] += row["_max_score"]
    return list(grouped.values())



def _parse_question_list(value) -> set[str]:
    """``"26, q14_modelo_dual"`` or a list -> {"26", "q14_modelo_dual"}."""
    if not value:
        return set()
    items = value.split(",") if isinstance(value, str) else value
    return {str(item).strip() for item in items if str(item).strip()}


def resolve_question_voids(rows: list[dict], mc_feedback: Optional[Dict[str, dict]] = None,
                           void_questions=None, void_questions_nicely=None) -> list[dict]:
    """Mark voided open questions on the score rows (in place) in ``row["_void_status"]``.

    Questions are named by their exam number (``question_id``) or ``original_id``.
    ``void_questions`` are removed for everyone (score and max). ``void_questions_nicely``
    count for a student only if they raise that student's mark, the open-answer analogue of
    pexams' rule for multiple choice: each question's ratio score/max is compared with the
    rest of the exam (the multiple-choice part from ``mc_feedback`` plus the other counted
    open questions). Several nicely voided questions are added in decreasing ratio while
    they raise the mark, which gives the best possible mark. A tie leaves the mark
    unchanged, so the question is excluded. Statuses: ``void``, ``nicely_counted``,
    ``nicely_excluded``, or ``""``.
    """
    void = _parse_question_list(void_questions)
    nicely = _parse_question_list(void_questions_nicely) - void
    mc_feedback = mc_feedback or {}

    def names(row):
        return {str(row.get("question_id", "")).strip(), str(row.get("original_id", "")).strip()} - {""}

    by_student: Dict[str, list[dict]] = {}
    for row in rows:
        row["_void_status"] = "void" if names(row) & void else ""
        by_student.setdefault(row.get("student_id", ""), []).append(row)

    for student_id, student_rows in by_student.items():
        mc = mc_feedback.get(student_id, {})
        score = to_float(mc.get("score")) or 0.0
        max_score = to_float(mc.get("max_score")) or 0.0
        candidates = []
        for row in student_rows:
            row_score, row_max = to_float(row.get("score")), to_float(row.get("max_score"))
            if row["_void_status"] or row_max is None:
                continue
            if names(row) & nicely:
                candidates.append((row, row_score or 0.0, row_max))
            else:
                score, max_score = score + (row_score or 0.0), max_score + row_max
        for row, row_score, row_max in sorted(candidates, key=lambda c: c[1] / c[2] if c[2] else 0.0, reverse=True):
            current = score / max_score if max_score else 0.0
            if row_max and row_score / row_max > current:
                row["_void_status"] = "nicely_counted"
                score, max_score = score + row_score, max_score + row_max
            else:
                row["_void_status"] = "nicely_excluded"
    return rows


def write_overall_marks_csv(combined: list[dict], mc_feedback: Dict[str, dict], output_dir: str,
                            rows: Optional[list[dict]] = None) -> str:
    """One row per student: the multiple-choice part (score, max and counts), the score of each
    open question (``q_<number>``, also for voided ones: ``voided_questions`` says which did not
    count), the open part and the final mark /10."""
    path = os.path.join(output_dir, "overall_marks.csv")
    scores: Dict[str, Dict[str, str]] = {}
    for row in rows or []:
        scores.setdefault(row.get("student_id", ""), {})[str(row.get("question_id", ""))] = row.get("score", "")
    question_ids = sorted({q for per_student in scores.values() for q in per_student},
                          key=lambda q: (0, int(q)) if q.isdigit() else (1, q))
    fields = (["student_id", "student_name", "mc_correct", "mc_incorrect", "mc_blank", "mc_score", "mc_max"]
              + [f"q_{q}" for q in question_ids]
              + ["open_score", "open_max", "total_score", "total_max", "mark", "voided_questions"])
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for item in sorted(combined, key=lambda row: row.get("student_name", "") or row.get("student_id", "")):
            mc = mc_feedback.get(item["student_id"], {})
            mc_score, mc_max = to_float(mc.get("score")) or 0.0, to_float(mc.get("max_score")) or 0.0
            per_question = scores.get(item["student_id"], {})
            writer.writerow({
                "student_id": item["student_id"],
                "student_name": item.get("student_name", ""),
                "mc_correct": mc.get("correct", ""),
                "mc_incorrect": mc.get("incorrect", ""),
                "mc_blank": mc.get("na", ""),
                "mc_score": round(mc_score, 4),
                "mc_max": round(mc_max, 4),
                **{f"q_{q}": per_question.get(q, "") for q in question_ids},
                "open_score": round(item["score"] - mc_score, 4),
                "open_max": round(item["max_score"] - mc_max, 4),
                "total_score": round(item["score"], 4),
                "total_max": round(item["max_score"], 4),
                "mark": round(10 * item["score"] / item["max_score"], 4) if item["max_score"] else "",
                "voided_questions": item.get("voided_questions", ""),
            })
    return path


def combined_totals(open_totals: list[dict], mc_feedback: Dict[str, dict]) -> list[dict]:
    combined: Dict[str, dict] = {}
    for item in open_totals:
        combined[item["student_id"]] = {
            "student_id": item["student_id"],
            "student_name": item.get("student_name", ""),
            "score": float(item.get("score", 0) or 0),
            "max_score": float(item.get("max_score", 0) or 0),
            "voided_questions": item.get("voided_questions", ""),
        }
    for student_id, item in mc_feedback.items():
        target = combined.setdefault(
            student_id,
            {"student_id": student_id, "student_name": item.get("student_name", ""), "score": 0.0, "max_score": 0.0},
        )
        if not target.get("student_name") and item.get("student_name"):
            target["student_name"] = item.get("student_name", "")
        try:
            target["score"] += float(item.get("score", "") or 0)
            target["max_score"] += float(item.get("max_score", "") or 0)
        except ValueError:
            pass
    return list(combined.values())
