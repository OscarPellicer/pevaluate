"""Combine the lab (notebook) marks and the end-of-session exam into one table per student.

Inputs (all produced by pevaluate / pexams):
  --lab-feedback   folder with pevaluate's feedback_*.yaml (one per submission; pairs list both)
  --exam-scores    one or more open_scores.csv (pevaluate exam-open / exam-free)
Students are matched across sources by name (accents, order and case ignored; fuzzy).

Output: a CSV (UTF-8 with BOM, ';' separated, opens directly in Excel) with one row per student:
name, lab mark and feedback, exam score, exam mark /10 and exam feedback, and where each value
came from, so that every row can be checked.

Example (`pevaluate combine-marks …`):
  pevaluate combine-marks --lab-feedback "P1 - SADC/correccion_practica/feedback" \
      --exam-scores "P1 - SADC/examen/correccion/impreso/evaluacion/open_scores.csv" \
                    "P1 - SADC/examen/correccion/abierto/open_scores.csv" \
      --output "P1 - SADC/notas_P1.csv"
"""
import argparse
import re
import csv
import glob
import os
from collections import defaultdict

import yaml
from .cli import levenshtein_ratio, name_order_variants, normalize_person_name as normalize_name, token_name_similarity


def similarity(a: str, b: str) -> float:
    best = 0.0
    for x in name_order_variants(a):
        for y in name_order_variants(b):
            # Symmetric: "Arnau Julio" must match "Arnau Julio Candel" whichever was seen first.
            best = max(best, levenshtein_ratio(x, y), token_name_similarity(x, y), token_name_similarity(y, x))
    return best


class Roster:
    """Students seen so far; each new name is merged with the most similar existing one."""

    def __init__(self, threshold: float):
        self.threshold = threshold
        self.students = []  # dicts with "name" and the collected fields

    def get(self, name: str) -> dict:
        best, best_score = None, 0.0
        for student in self.students:
            score = similarity(name, student["name"])
            if score > best_score:
                best, best_score = student, score
        if best is not None and best_score >= self.threshold:
            best.setdefault("aliases", set()).add(name)
            return best
        student = {"name": name, "aliases": {name}}
        self.students.append(student)
        return student


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pevaluate combine-marks", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lab-feedback", required=True)
    parser.add_argument("--exam-scores", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--threshold", type=float, default=75.0, help="Minimum name similarity (0-100) to merge two names.")
    parser.add_argument("--lab-weight", type=float, default=0.3, help="Weight of the lab (notebook) mark in the final mark.")
    parser.add_argument("--exam-weight", type=float, default=0.7, help="Weight of the exam mark in the final mark.")
    parser.add_argument("--notice", default="", help="Text appended to every student's feedback (e.g. a warning for next time).")
    parser.add_argument("--lang", choices=["es", "en"], default="es", help="Language of the composed feedback.")
    parser.add_argument("--roster", help="Grade file to fill (CSV or Excel), e.g. a Moodle gradebook export.")
    parser.add_argument("--roster-id-column", default="Número de identificación")
    parser.add_argument("--roster-name-column", default="Nombre alumno")
    parser.add_argument("--roster-mark-column", default="Nota numérica")
    parser.add_argument("--roster-feedback-column", default="Retroalimentación", help="Column added (or filled) with the composed feedback.")
    parser.add_argument("--roster-output", help="Filled copy of --roster (default: <roster>_filled.<ext>).")
    args = parser.parse_args(argv)

    roster = Roster(args.threshold)

    # Lab: the Moodle submitter (from the file name) and every member listed by the grader.
    for path in sorted(glob.glob(os.path.join(args.lab_feedback, "feedback_*.yaml"))):
        data = yaml.safe_load(open(path, encoding="utf-8")) or {}
        names = [s.get("full_name", "") if isinstance(s, dict) else str(s) for s in data.get("students", [])]
        submission = os.path.basename(str(data.get("submission_file", "")))
        for name in [n for n in names if n.strip()]:
            student = roster.get(name)
            if "lab_mark" in student and student.get("lab_source") != submission:
                # The same student appears in two submissions (e.g. alone and in a pair): keep the
                # higher mark and record both.
                student["lab_conflict"] = f"{student['lab_mark']} ({student['lab_source']}) vs {data.get('mark')} ({submission})"
                if float(data.get("mark") or 0) <= float(student["lab_mark"] or 0):
                    continue
            student["lab_mark"] = data.get("mark")
            student["lab_feedback"] = str(data.get("feedback", "")).strip()
            student["lab_source"] = submission
            student["lab_group"] = " / ".join(names) if len(names) > 1 else ""

    # Exams: sum the question scores of each exam.
    for scores_csv in args.exam_scores:
        exams = defaultdict(list)
        with open(scores_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                exams[(row["student_id"], row["student_name"])].append(row)
        for (student_id, name), rows in exams.items():
            student = roster.get(name or student_id)
            rows.sort(key=lambda r: r["question_id"])
            score = sum(float(r["score"] or 0) for r in rows)
            max_score = sum(float(r["max_score"] or 0) for r in rows)
            student["exam_score"] = f"{score:g} / {max_score:g}"
            student["exam_mark"] = round(10 * score / max_score, 2) if max_score else ""
            student["exam_feedback"] = "\n".join(f"P{r['question_id']} ({float(r['score'] or 0):g}/{float(r['max_score'] or 0):g}): {r['feedback']}" for r in rows)
            student["exam_id"] = student_id
            student["exam_source"] = os.path.basename(os.path.dirname(scores_csv))

    labels = LABELS[args.lang]
    for student in roster.students:
        lab = float(student["lab_mark"]) if student.get("lab_mark") not in (None, "") else None
        exam = float(student["exam_mark"]) if student.get("exam_mark") not in (None, "") else None
        final = args.lab_weight * (lab or 0) + args.exam_weight * (exam or 0)
        student["final_mark"] = round(final, 2)
        parts = [f"{labels['lab']} ({args.lab_weight:.0%}): " + (f"{lab:g}/10" if lab is not None else labels["missing"])]
        if student.get("lab_feedback"):
            parts.append(student["lab_feedback"])
        parts.append("")
        parts.append(f"{labels['exam']} ({args.exam_weight:.0%}): " + (f"{exam:g}/10 ({student['exam_score']})" if exam is not None else labels["missing"]))
        if student.get("exam_feedback"):
            parts.append(student["exam_feedback"])
        parts.append("")
        parts.append(f"{labels['final']}: {args.lab_weight:g} × {lab or 0:g} + {args.exam_weight:g} × {exam or 0:g} = {final:.2f}/10")
        if args.notice:
            parts += ["", args.notice]
        student["feedback"] = "\n".join(parts)

    fields = ["name", "aliases", "final_mark", "lab_mark", "exam_mark", "exam_score", "feedback", "lab_feedback", "exam_feedback",
              "lab_conflict", "lab_group", "lab_source", "exam_id", "exam_source"]
    rows = sorted(roster.students, key=lambda s: normalize_name(s["name"]))
    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        for student in rows:
            writer.writerow({**student, "aliases": " | ".join(sorted(student["aliases"] - {student["name"]}))})
    print(f"{len(rows)} students -> {args.output}")
    print("Without lab mark:", ", ".join(s["name"] for s in rows if "lab_mark" not in s) or "-")
    print("Two lab submissions:", ", ".join(s["name"] for s in rows if s.get("lab_conflict")) or "-")
    print("Without exam:", ", ".join(s["name"] for s in rows if "exam_mark" not in s) or "-")
    if args.roster:
        fill_roster(args, rows)


def _digits(value) -> str:
    return re.sub(r"\D", "", str(value or "")).lstrip("0")


def fill_roster(args, students):
    """Fill the mark (and feedback) of every row of a grade file, matching by ID, then by name."""
    import pandas as pd

    path = args.roster
    excel = path.lower().endswith((".xlsx", ".xls"))
    table = pd.read_excel(path, dtype=str) if excel else pd.read_csv(path, dtype=str, sep=None, engine="python")
    marks, feedback, unmatched, used = [], [], [], set()
    for _, row in table.iterrows():
        rid, rname = _digits(row.get(args.roster_id_column)), str(row.get(args.roster_name_column, ""))
        match = None
        if len(rid) >= 6:
            match = next((s for s in students if _digits(s.get("exam_id")).startswith(rid)), None)
        if match is None and rname.strip():
            best = max(students, key=lambda s: max(similarity(rname, n) for n in s["aliases"] | {s["name"]}), default=None)
            if best is not None and max(similarity(rname, n) for n in best["aliases"] | {best["name"]}) >= args.threshold:
                match = best
        if match is None:
            unmatched.append(rname)
            marks.append(None); feedback.append("")
        else:
            used.add(id(match))
            marks.append(match["final_mark"]); feedback.append(match["feedback"])
    table[args.roster_mark_column] = marks
    table[args.roster_feedback_column] = feedback
    out = args.roster_output or re.sub(r"(\.[^.]+)$", r"_filled\1", path)
    table.to_excel(out, index=False) if excel else table.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"Filled {len(table) - len(unmatched)} of {len(table)} rows -> {out}")
    print("Grade-file rows without marks:", ", ".join(unmatched) or "-")
    print("Students not in the grade file:", ", ".join(s["name"] for s in students if id(s) not in used) or "-")


LABELS = {
    "es": {"lab": "Práctica (notebook)", "exam": "Examen", "final": "Nota final", "missing": "no presentado (0)"},
    "en": {"lab": "Lab (notebook)", "exam": "Exam", "final": "Final mark", "missing": "not submitted (0)"},
}


if __name__ == "__main__":
    main()
