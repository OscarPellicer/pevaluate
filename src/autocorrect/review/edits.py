"""The teacher's edits, written to the same files and fields an agent or the teacher would edit
by hand (see the skill): top-level ``score``/``feedback`` in ``open_evaluations.yaml``,
``mark``/``feedback``/``students`` in a lab feedback YAML, answers and the student of a scanned
exam in ``correction_results.csv``. The ``grader`` blocks are never touched. Every save checks
that the file did not change since the page loaded it, and the first one keeps a copy of the
file (``<file>.before_review``).
"""
import csv
import io
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from ..common import to_float, write_yaml
from .data import ReviewConfig, _review_state_path, file_version, load_review_state


class Conflict(Exception):
    """The file changed on disk since the page loaded it (another tool, an agent, an editor)."""


class Invalid(ValueError):
    """The edit is not valid (score out of range, unknown answer, duplicated student...)."""


def _check(path: str, version: Optional[str]) -> None:
    if not os.path.exists(path):
        raise Invalid(f"{path} not found.")
    if version is not None and version != file_version(path):
        raise Conflict(f"{os.path.basename(path)} changed on disk since the page was loaded. Reload to see the changes.")


def _backup(path: str) -> None:
    backup = f"{path}.before_review"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- Review state (ticks and originals the grader block does not keep) -----------------------------

def _save_state(cfg: ReviewConfig, state: dict) -> None:
    path = _review_state_path(cfg)
    Path(path).write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def set_reviewed(cfg: ReviewConfig, keys: list[str], reviewed: bool) -> dict:
    state = load_review_state(cfg)
    ticks = state.setdefault("reviewed", {})
    for key in keys:
        if reviewed:
            ticks[key] = {"at": _now()}
        else:
            ticks.pop(key, None)
    _save_state(cfg, state)
    return ticks


def _keep_original(cfg: ReviewConfig, key: str, original: dict) -> None:
    """Old results have no model grade in their grader block: keep the first one seen here."""
    state = load_review_state(cfg)
    originals = state.setdefault("originals", {})
    if key not in originals:
        originals[key] = {**original, "kept_at": _now()}
        _save_state(cfg, state)


# --- Open answers -----------------------------------------------------------------------------------

def save_open(cfg: ReviewConfig, student_id: str, question_id: str, score, feedback: str, version: Optional[str]) -> None:
    path = os.path.join(cfg.open_dir, "open_evaluations.yaml")
    _check(path, version)
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    item = next((r for r in data.get("responses", []) if str(r.get("student_id")) == str(student_id)
                 and str(r.get("question_id")) == str(question_id)), None)
    if item is None:
        raise Invalid(f"No answer of {student_id} to question {question_id}.")
    value = to_float(score)
    maximum = to_float(item.get("max_score"))
    if value is None or value < 0 or (maximum is not None and value > maximum + 1e-9):
        raise Invalid(f"The score must be between 0 and {maximum}.")
    if "score" not in (item.get("grader") or {}):
        _keep_original(cfg, f"{student_id}|{item.get('original_id') or question_id}",
                       {"score": item.get("score"), "feedback": item.get("feedback")})
    _backup(path)
    item["score"] = int(value) if float(value).is_integer() and isinstance(item.get("score"), int) else value
    item["feedback"] = str(feedback or "").strip()
    write_yaml(path, data)


# --- Multiple choice and the student of a scanned exam ------------------------------------------------

def _read_table(path: str) -> tuple[list[str], list[list[str]], dict]:
    raw = Path(path).read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    rows = list(csv.reader(io.StringIO(text, newline="")))
    return rows[0], rows[1:], {"bom": bom, "newline": newline}


def _write_table(path: str, header: list[str], rows: list[list[str]], fmt: dict) -> None:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator=fmt["newline"])
    writer.writerow(header)
    writer.writerows(rows)
    Path(path).write_bytes((b"\xef\xbb\xbf" if fmt["bom"] else b"") + buffer.getvalue().encode("utf-8"))


def _row_of_page(header, rows, page: str) -> list[str]:
    col = header.index("page")
    row = next((r for r in rows if str(r[col]) == str(page)), None)
    if row is None:
        raise Invalid(f"No exam on page {page}.")
    return row


def save_mc(cfg: ReviewConfig, page: str, number: str, letter: str, n_options: int, version: Optional[str]) -> None:
    path = os.path.join(cfg.mc_dir, "correction_results.csv")
    _check(path, version)
    header, rows, fmt = _read_table(path)
    column = f"answer_{number}"
    if column not in header:
        raise Invalid(f"No column {column}.")
    letter = (letter or "").strip().upper()
    valid = [chr(ord("A") + i) for i in range(n_options)]
    if letter not in valid + [""]:
        raise Invalid(f"The answer must be one of {', '.join(valid)} or blank.")
    row = _row_of_page(header, rows, page)
    _backup(path)
    row[header.index(column)] = letter or "NA"
    _write_table(path, header, rows, fmt)


def save_student(cfg: ReviewConfig, page: str, new_id: str, new_name: str, versions: dict) -> None:
    """The student of a scanned exam (a misread ID or name, or the class-list name). A new ID is
    carried to the open-answer grades and the crops index, so nothing is graded again."""
    path = os.path.join(cfg.mc_dir, "correction_results.csv")
    _check(path, versions.get("mc"))
    header, rows, fmt = _read_table(path)
    row = _row_of_page(header, rows, page)
    id_col, name_col = header.index("student_id"), header.index("student_name")
    old_id = row[id_col]
    new_id, new_name = (new_id or "").strip(), (new_name or "").strip()
    if not new_id:
        raise Invalid("The student ID cannot be empty.")
    if new_id != old_id and any(r[id_col] == new_id for r in rows):
        raise Invalid(f"Another exam already has the ID {new_id}.")
    open_path = os.path.join(cfg.open_dir, "open_evaluations.yaml") if cfg.open_dir else None
    if open_path and os.path.exists(open_path):
        _check(open_path, versions.get("open"))
    _backup(path)
    row[id_col], row[name_col] = new_id, new_name
    _write_table(path, header, rows, fmt)

    if open_path and os.path.exists(open_path):
        data = yaml.safe_load(Path(open_path).read_text(encoding="utf-8")) or {}
        changed = False
        for item in data.get("responses", []):
            if str(item.get("student_id")) == old_id:
                item["student_id"], item["student_name"] = new_id, new_name
                changed = True
        if changed:
            _backup(open_path)
            write_yaml(open_path, data)
    if cfg.index_csv and os.path.exists(cfg.index_csv):
        header_i, rows_i, fmt_i = _read_table(cfg.index_csv)
        if "answer_sheet_page" in header_i:
            page_col = header_i.index("answer_sheet_page")
            for r in rows_i:
                if str(r[page_col]) == str(page):
                    r[header_i.index("student_id")], r[header_i.index("student_name")] = new_id, new_name
            _write_table(cfg.index_csv, header_i, rows_i, fmt_i)
    if new_id != old_id:
        state = load_review_state(cfg)
        for section in ("reviewed", "originals"):
            items = state.get(section, {})
            for key in [k for k in items if k.startswith(f"{old_id}|")]:
                items[f"{new_id}|{key.split('|', 1)[1]}"] = items.pop(key)
        if state:
            _save_state(cfg, state)


# --- Lab submissions ----------------------------------------------------------------------------------

def save_lab(cfg: ReviewConfig, key: str, mark, feedback: str, members: Optional[list[str]], version: Optional[str]) -> None:
    from ..lab import write_feedback_yaml

    path = os.path.join(cfg.feedback_dir, f"{key}.yaml")
    if os.path.dirname(os.path.abspath(path)) != os.path.abspath(cfg.feedback_dir):
        raise Invalid("Unknown submission.")
    _check(path, version)
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    value = to_float(mark)
    if value is None or not 0 <= value <= 10:
        raise Invalid("The mark must be between 0 and 10.")
    if "mark" not in (data.get("grader") or {}):
        _keep_original(cfg, key, {"mark": data.get("mark"), "feedback": data.get("feedback")})
    _backup(path)
    data["mark"] = value
    data["feedback"] = str(feedback or "").strip()
    if members is not None:
        data["students"] = [{"full_name": m.strip()} for m in members if m and m.strip()]
    write_feedback_yaml(path, data)
