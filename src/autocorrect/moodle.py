"""Fill a Moodle assignment grading worksheet (``pevaluate moodle-csv``) with marks and feedback,
either from pevaluate's ``feedback/*.yaml`` or from a ``pevaluate combine-marks`` CSV."""
import argparse
import csv
import html
import re
from pathlib import Path
from typing import Optional

import yaml

from .common import add_hidden_alias, read_csv_rows
from .moodle_columns import find_column
from .names import levenshtein_ratio, name_order_variants, normalize_name, token_name_similarity

_NOT_SUBMITTED = re.compile(r"^\s*(no\b|sin\b|cap\b|nothing\b)", re.IGNORECASE)


def resolve_moodle_column(fieldnames, requested, role, required=True):
    """The worksheet column for ``role`` (``requested`` first, then the known Moodle spellings in
    Catalan, Spanish and English, ignoring accents and punctuation). ``""`` disables the column."""
    resolved = find_column(fieldnames, requested, role)
    if resolved and requested and requested != resolved:
        print(f"Resolved Moodle column '{requested}' to '{resolved}'.")
    if resolved is None and required and requested != "":
        print(f"CSV column not found for {role}: {requested}. Available columns: {fieldnames}")
    return resolved


def find_moodle_row(student_name, row_by_name, fuzzy_threshold):
    """(row, match type, score 0-100): exact match on any name order, else the most similar name
    (character or token similarity) if it reaches ``fuzzy_threshold``."""
    keys = name_order_variants(student_name)
    for key in keys:
        if key in row_by_name:
            return row_by_name[key], "exact", 100.0

    if fuzzy_threshold is None or fuzzy_threshold <= 0:
        return None, None, 0.0

    best_key = None
    best_score = 0.0
    best_match_type = "fuzzy"
    for candidate_key in row_by_name:
        for key in keys:
            score = levenshtein_ratio(key, candidate_key)
            if score > best_score:
                best_key = candidate_key
                best_score = score
                best_match_type = "fuzzy"

            token_score = token_name_similarity(key, candidate_key)
            if token_score > best_score:
                best_key = candidate_key
                best_score = token_score
                best_match_type = "token-fuzzy"

    if best_key is not None and best_score >= fuzzy_threshold:
        return row_by_name[best_key], best_match_type, best_score
    return None, None, best_score


def _find_row_any(names, row_by_name, fuzzy_threshold):
    best = (None, None, 0.0)
    for name in names:
        found = find_moodle_row(name, row_by_name, fuzzy_threshold)
        if found[0] is not None and (best[0] is None or found[2] > best[2]):
            best = found
    return best


def format_moodle_mark(mark):
    if mark is None:
        return ""
    return f"{float(mark):.2f}".replace(".", ",")


def format_moodle_feedback(feedback, feedback_format):
    feedback = str(feedback or "").strip()
    if feedback_format == "plain":
        return feedback
    if feedback_format == "html":
        escaped = html.escape(feedback)
        return escaped.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    if feedback_format == "escaped-newlines":
        return feedback.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
    return feedback


def collect_feedback_yaml(feedback_dir):
    feedback_items = []
    for path in sorted(Path(feedback_dir).glob("*.y*ml")):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            print(f"Warning: ignoring non-dict feedback YAML: {path}")
            continue
        data["_path"] = str(path)
        feedback_items.append(data)
    return feedback_items


def moodle_row_submitted(row, status_col):
    """Whether a worksheet row's status says the student submitted to this assignment
    ("S'ha tramès per qualificar", "Enviado para calificar", "Submitted for grading")."""
    status = str(row.get(status_col, "") or "").strip()
    return bool(status) and not _NOT_SUBMITTED.match(status)


def collect_marks_csv(path):
    """Students of a `pevaluate combine-marks` output as feedback items: final mark, composed
    feedback, every name seen for the student, and the lab group (partners)."""
    items = []
    for row in read_csv_rows(path, encoding="utf-8-sig", delimiter=";"):
        names = [row["name"]] + [a.strip() for a in str(row.get("aliases") or "").split(" | ") if a.strip()]
        group = [n.strip() for n in str(row.get("lab_group") or "").split(" / ") if n.strip()]
        items.append({
            "mark": float(row["final_mark"]) if str(row.get("final_mark", "")).strip() else None,
            "feedback": row.get("feedback", ""),
            "students": [{"full_name": row["name"]}],
            "names": names,
            "partners": [n for n in group if n not in names],
            "has_lab": bool(str(row.get("lab_mark", "")).strip()),
            "_path": path,
        })
    return items


class _Worksheet:
    """The rows of a Moodle grading worksheet and the bookkeeping of what was filled."""

    def __init__(self, rows, fieldnames, grade_col, feedback_col, name_col, args):
        self.rows, self.fieldnames = rows, fieldnames
        self.grade_col, self.feedback_col, self.name_col = grade_col, feedback_col, name_col
        self.args = args
        self.row_by_name = {normalize_name(row.get(name_col, "")): row for row in rows}
        self.updated_row_ids = set()
        self.matched = 0
        self.unmatched = []  # (name, source path, best score)

    def find(self, names):
        return _find_row_any(names, self.row_by_name, self.args.fuzzy_threshold)

    def already_filled(self, row):
        return str(row.get(self.grade_col, "")).strip() or str(row.get(self.feedback_col, "")).strip()

    def fill(self, row, mark, feedback, name, match_type, match_score):
        if match_type != "exact":
            print(f"{match_type.capitalize()} matched '{name}' -> '{row.get(self.name_col, '')}' ({match_score:.1f}/100)")
        row[self.grade_col] = format_moodle_mark(mark)
        row[self.feedback_col] = feedback
        self.updated_row_ids.add(id(row))
        self.matched += 1


def _fill_from_marks(sheet, items, status_col):
    """Fill from a combine-marks CSV. Every student of the course is listed in each assignment's
    worksheet; a student is graded in the assignment where they or a lab partner submitted.
    Returns the students left out (submitted elsewhere, without any lab submission)."""
    args = sheet.args
    elsewhere, no_lab = [], []
    for item in items:
        row, match_type, match_score = sheet.find(item["names"])
        if row is None:
            sheet.unmatched.append((item["names"][0], item.get("_path"), match_score))
            continue
        if status_col and not getattr(args, "all_rows", False):
            here = moodle_row_submitted(row, status_col) or any(
                (p := sheet.find([partner])[0]) is not None and moodle_row_submitted(p, status_col)
                for partner in item["partners"])
            if not here and item["has_lab"]:
                elsewhere.append(row.get(sheet.name_col, ""))
                continue
            if not here and not getattr(args, "include_no_lab", False):
                no_lab.append(row.get(sheet.name_col, ""))
                continue
        if item["mark"] is None or (args.skip_filled and sheet.already_filled(row)):
            continue
        sheet.fill(row, item["mark"], format_moodle_feedback(item.get("feedback", ""), args.feedback_format),
                   item["names"][0], match_type, match_score)
    return elsewhere, no_lab


def _fill_from_feedback(sheet, items):
    """Fill from pevaluate feedback YAML files: every student listed in a file gets its mark."""
    args = sheet.args
    for item in items:
        feedback = format_moodle_feedback(item.get("feedback", ""), args.feedback_format)
        students = item.get("students", [])
        if isinstance(students, str):
            students = [{"full_name": students}]
        for student in students:
            if isinstance(student, dict):
                student_name = student.get("full_name") or student.get("name") or ""
            else:
                student_name = str(student)
            row, match_type, match_score = find_moodle_row(student_name, sheet.row_by_name, args.fuzzy_threshold)
            if row is None:
                sheet.unmatched.append((student_name, item.get("_path"), match_score))
                continue
            if args.skip_filled and sheet.already_filled(row):
                continue
            sheet.fill(row, item.get("mark"), feedback, student_name, match_type, match_score)


def _clear_timestamps(sheet):
    args = sheet.args
    for timestamp_col in (
        resolve_moodle_column(sheet.fieldnames, args.submission_modified_column, "submission_modified", required=False),
        resolve_moodle_column(sheet.fieldnames, args.grade_modified_column, "grade_modified", required=False),
    ):
        if not timestamp_col:
            continue
        if timestamp_col not in sheet.fieldnames:
            print(f"Warning: timestamp column not found, cannot clear it: {timestamp_col}")
            continue
        for row in sheet.rows:
            if id(row) in sheet.updated_row_ids:
                row[timestamp_col] = "-"


def feedback_to_moodle_csv(args):
    marks_csv = getattr(args, "marks", None)
    feedback_items = collect_marks_csv(marks_csv) if marks_csv else collect_feedback_yaml(args.feedback_dir)
    if not feedback_items:
        print(f"No marks found in {marks_csv or args.feedback_dir}")
        return

    with open(args.marks_csv, "r", encoding=args.encoding, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    if not fieldnames:
        print(f"Could not read CSV header from {args.marks_csv}")
        return

    grade_col = resolve_moodle_column(fieldnames, args.grade_column, "grade")
    feedback_col = resolve_moodle_column(fieldnames, args.feedback_column, "feedback")
    name_col = resolve_moodle_column(fieldnames, args.name_column, "name")
    if not grade_col or not feedback_col or not name_col:
        return
    sheet = _Worksheet(rows, fieldnames, grade_col, feedback_col, name_col, args)

    elsewhere, no_lab = [], []
    if marks_csv:
        status_col = resolve_moodle_column(fieldnames, getattr(args, "status_column", None), "status", required=False)
        elsewhere, no_lab = _fill_from_marks(sheet, feedback_items, status_col)
    else:
        _fill_from_feedback(sheet, feedback_items)

    if args.clear_timestamps:
        _clear_timestamps(sheet)

    output_rows = [row for row in rows if id(row) in sheet.updated_row_ids] if args.partial else rows
    with open(args.output, "w", encoding=args.encoding, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Wrote Moodle CSV: {args.output}")
    print(f"Updated {sheet.matched} student row(s) from {len(feedback_items)} {'student(s) in ' + marks_csv if marks_csv else 'feedback YAML file(s)'}.")
    if elsewhere:
        print(f"Not in this assignment (they or their partner submitted to another one): {len(elsewhere)}")
    if no_lab:
        print(f"No lab submission, left out (pass --include-no-lab in the one assignment that should carry their mark): {', '.join(no_lab)}")
    if args.partial:
        print(f"Partial CSV contains {len(output_rows)} row(s).")
    if sheet.unmatched:
        print(f"Unmatched students ({len(sheet.unmatched)}):")
        for name, path, score in sheet.unmatched:
            print(f"  {name} from {path} (best fuzzy score {score:.1f}/100)")


DESCRIPTION = "Compile structured YAML feedback into a Moodle marks CSV."


def build_parser(parser: Optional[argparse.ArgumentParser] = None) -> argparse.ArgumentParser:
    parser = parser or argparse.ArgumentParser(prog="pevaluate moodle-csv", description=DESCRIPTION)
    parser.add_argument("marks_csv", help="Moodle marks CSV to fill.")
    parser.add_argument("--feedback-dir", default="feedback", help="Directory containing feedback YAML files.")
    parser.add_argument("--marks", help="Use the output of `pevaluate combine-marks` (final mark and composed feedback) instead of --feedback-dir. "
                                        "Each student is filled in only if they or a lab partner submitted to this assignment (worksheet status).")
    parser.add_argument("--include-no-lab", action="store_true", help="With --marks: also fill students without any lab submission (do it in one assignment only).")
    parser.add_argument("--all-rows", action="store_true", help="With --marks: fill every matched student, ignoring the submission status.")
    parser.add_argument("--status-column", default=None, help="Moodle worksheet status column (default: Estat/Estado/Status).")
    parser.add_argument("--output", default="marks_filled.csv", help="Output CSV path for Moodle upload.")
    parser.add_argument("--encoding", default="utf-8-sig", help="CSV encoding.")
    parser.add_argument("--name-column", default="Nom complet", help="Moodle CSV full-name column.")
    parser.add_argument("--grade-column", default="Qualificació", help="Moodle CSV grade column.")
    parser.add_argument("--feedback-column", default="Comentaris de retroacció.", help="Moodle CSV feedback comments column.")
    parser.add_argument("--submission-modified-column", default="Darrera modificació (tramesa)", help="Moodle CSV last-submission-modified column.")
    parser.add_argument("--grade-modified-column", default="Darrera modificació (qualificació)", help="Moodle CSV last-grade-modified column.")
    parser.add_argument("--feedback-format", choices=["plain", "html", "escaped-newlines"], default="plain", help="How to write multiline feedback comments in the CSV. Use 'html' if Moodle flattens raw newlines.")
    parser.add_argument("--partial", action="store_true", help="Write only rows that were updated from feedback YAML. Safer for repeated Moodle imports.")
    parser.add_argument("--skip-filled", action="store_true", help="Do not overwrite rows that already have a grade or feedback in the input Moodle CSV.")
    parser.add_argument("--clear-timestamps", action="store_true", help="Set Moodle last-modified timestamp columns to '-' for updated rows.")
    parser.add_argument("--name-threshold", dest="fuzzy_threshold", metavar="THRESHOLD", type=float, default=70.0,
                        help="Minimum name similarity (0-100) for fuzzy name matching. Use 0 to disable.")
    add_hidden_alias(parser, "--fuzzy-threshold", "fuzzy_threshold", type=float)
    return parser


def run(args: argparse.Namespace):
    feedback_to_moodle_csv(args)


def main(argv: Optional[list[str]] = None):
    run(build_parser().parse_args(argv))
