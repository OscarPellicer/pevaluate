"""Everything the review app shows, read from the files the other commands write, as one JSON
model: students (matched to the class list when there is one), questions (statement, options,
expected answer, rubric, statistics), answers (multiple-choice letter or open-answer grade, with
images and the model's original grade) and, for lab work, submissions with their files and the
members of each group.
"""
import csv
import glob
import hashlib
import html
import json
import os
import re
import shlex
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import yaml

from ..common import to_float

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
TEXT_EXTENSIONS = {".txt", ".sql", ".py", ".r", ".m", ".c", ".cpp", ".h", ".java", ".js", ".ts", ".json", ".xml",
                   ".xsd", ".csv", ".tsv", ".yaml", ".yml", ".sh", ".log", ".ini", ".cfg", ".toml"}
RENDERED_EXTENSIONS = {".ipynb", ".docx", ".pptx", ".md"}


@dataclass
class RebuildAction:
    """A button of the app: reruns steps that rebuild reports, marks, PDFs or upload files."""
    id: str
    label: str
    description: str
    run: Callable[[], tuple[bool, str]]


@dataclass
class ReviewConfig:
    title: str = "Review"
    exam_dir: Optional[str] = None
    mc_dir: Optional[str] = None             # pexams correction folder (correction_results.csv)
    open_dir: Optional[str] = None           # exam-open / exam-free folder (open_evaluations.yaml)
    index_csv: Optional[str] = None          # pexams open_responses_index.csv
    feedback_dir: Optional[str] = None       # lab grading feedback/ folder
    rubric: Optional[str] = None             # lab rubric file
    roster: Optional[str] = None             # class list (LMS export)
    roster_id_column: Optional[str] = None   # its columns, when not the usual ones
    roster_name_column: Optional[str] = None
    base_dirs: list = field(default_factory=list)  # where relative paths in the results are resolved
    penalty: Optional[float] = None
    mc_void: list = field(default_factory=list)
    mc_void_nicely: list = field(default_factory=list)
    open_void: list = field(default_factory=list)
    open_void_nicely: list = field(default_factory=list)
    rebuild_actions: list = field(default_factory=list)
    on_edit: Optional[Callable[[], None]] = None   # called after every saved edit (e.g. to update the course record)
    lang: str = "es"


# --- Files ---------------------------------------------------------------------------------------

def file_version(path: Optional[str]) -> str:
    """Changes whenever the file changes: the app refuses to save over a newer version."""
    try:
        stat = os.stat(path)
    except (OSError, TypeError):
        return ""
    return f"{stat.st_mtime_ns}-{stat.st_size}"


def resolve(path, bases) -> str:
    """An existing absolute path for ``path`` (absolute, or relative to one of ``bases``), else ''."""
    if not path:
        return ""
    candidate = Path(str(path))
    if candidate.is_absolute():
        return str(candidate) if candidate.exists() else ""
    for base in bases:
        full = Path(base) / candidate
        if full.exists():
            return str(full.resolve())
    return ""


def read_manifest(folder: Optional[str]) -> dict:
    path = Path(folder or "") / "run_manifest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        return {}


def manifest_option(manifest: dict, option: str) -> Optional[str]:
    command = manifest.get("command") or []
    for i, item in enumerate(command):
        if item == option and i + 1 < len(command):
            return command[i + 1]
        if item.startswith(option + "="):
            return item.split("=", 1)[1]
    return None


def _ancestors(folder: Optional[str], levels: int = 4) -> list[str]:
    if not folder:
        return []
    path = Path(folder).resolve()
    return [str(p) for p in [path, *path.parents][:levels + 1]]


def _read_csv(path: Optional[str]) -> list[dict]:
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _split_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value).split(",") if v.strip()]


class Files:
    """The files the page may load, each behind an opaque token (no paths in URLs)."""

    def __init__(self):
        self.by_token: dict[str, str] = {}

    def url(self, path: Optional[str], kind: str = "f") -> str:
        if not path:
            return ""
        path = os.path.abspath(path)
        token = hashlib.sha1(path.encode("utf-8")).hexdigest()[:20]
        self.by_token[token] = path
        return f"/{kind}/{token}"


# --- Markdown ------------------------------------------------------------------------------------

def render_markdown(text, files: Files, base_dir: Optional[str] = None, inline: bool = False) -> str:
    """Markdown with math and images, rendered as in the reports and student PDFs."""
    from ..report import _render_inline_markdown, _render_markdown

    if not text:
        return ""
    rendered = (_render_inline_markdown if inline else _render_markdown)(str(text))

    def image(match):
        src = html.unescape(match.group(2))
        if re.match(r"^(https?:|data:)", src):
            return match.group(0)
        full = resolve(src, [base_dir] if base_dir else [])
        return f'{match.group(1)}{files.url(full)}{match.group(3)}' if full else match.group(0)

    return re.sub(r'(<img[^>]*?src=")([^"]+)(")', image, rendered)


def render_comment(text) -> str:
    """Lab feedback as the LMS shows the uploaded comment (paragraphs and line breaks kept)."""
    from ..poliformat import feedback_html

    return feedback_html(str(text or "")) if text else ""


# --- Exams: questions ----------------------------------------------------------------------------

def _letter(index: int) -> str:
    return chr(ord("A") + index)


def load_questions(exam_dir: Optional[str], files: Files) -> tuple[dict, dict]:
    """``(questions by key, {model id: {exam number: question key}})``. A question's key is its
    original id (the same in every model); options are listed in the order of the first model,
    and ``letters[model][letter]`` maps a model's printed letter to that order."""
    questions, numbers = {}, {}
    if not exam_dir:
        return questions, numbers
    paths = sorted(Path(exam_dir).glob("exam_model_*_questions.json"),
                   key=lambda p: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", p.name)])
    for path in paths:
        model_id = re.match(r"exam_model_(.+)_questions\.json$", path.name).group(1)
        payload = json.loads(path.read_text(encoding="utf-8"))
        numbers[model_id] = {}
        for q in payload.get("questions", []):
            key = str(q.get("original_id") or f"q{q.get('id')}")
            number = str(q.get("id"))
            numbers[model_id][number] = key
            options = [str(o.get("text", "")) for o in q.get("options") or []]
            question = questions.get(key)
            if question is None:
                is_mc = q.get("question_type", "multiple_choice") != "open_answer" and bool(options)
                image = resolve(q.get("image_source"), [exam_dir]) if q.get("image_source") else ""
                question = questions[key] = {
                    "key": key, "number": number, "numbers": {}, "type": "mc" if is_mc else "open",
                    "points": to_float(q.get("points")),
                    "text_html": render_markdown(q.get("text"), files, exam_dir),
                    "image": files.url(image) if image else "",
                    "options": [{"letter": _letter(i), "text_html": render_markdown(t, files, exam_dir, inline=True),
                                 "text": t, "correct": bool((q.get("options") or [])[i].get("is_correct"))}
                                for i, t in enumerate(options)],
                    "expected_html": render_markdown(q.get("expected_answer"), files, exam_dir),
                    "rubric_html": render_markdown(q.get("rubric"), files, exam_dir),
                    "explanation_html": render_markdown(q.get("explanation"), files, exam_dir),
                    "letters": {},
                }
            question["numbers"][model_id] = number
            if question["type"] == "mc":
                canonical = [o["text"] for o in question["options"]]
                question["letters"][model_id] = {
                    _letter(i): canonical.index(t) if t in canonical else i for i, t in enumerate(options)}
    for question in questions.values():
        distinct = sorted(set(question["numbers"].values()), key=lambda n: int(n) if n.isdigit() else 0)
        question["number"] = distinct[0] if len(distinct) == 1 else "/".join(distinct)
    return questions, numbers


# --- Exams: answers --------------------------------------------------------------------------------

def _void_kind(question: dict, void_all: list, void_nicely: list) -> str:
    ids = {question["key"], *question["numbers"].values()}
    if ids & set(void_all):
        return "all"
    if ids & set(void_nicely):
        return "nicely"
    return ""


def _mc_answers(cfg: ReviewConfig, questions: dict, numbers: dict, students: dict, answers: list):
    rows = _read_csv(os.path.join(cfg.mc_dir, "correction_results.csv"))
    marks = {r.get("student_id", ""): r for r in _read_csv(os.path.join(cfg.mc_dir, "final_marks.csv"))}
    sheets = os.path.join(cfg.mc_dir, "scanned_pages")
    for row in rows:
        sid = str(row.get("student_id", "")).strip()
        model_id = str(row.get("model_id", ""))
        sheet = os.path.join(sheets, f"{sid}.png")
        student = students.setdefault(sid, {"key": sid, "id": sid, "name": row.get("student_name", "")})
        student.update({
            "page": row.get("page", ""), "model_id": model_id,
            "read_id": row.get("ocr_student_id", ""), "read_name": row.get("ocr_student_name", ""),
            "sheet": cfg._files.url(sheet) if os.path.exists(sheet) else "",
            "mc": {"score": to_float(marks.get(sid, {}).get("score")), "max": to_float(marks.get(sid, {}).get("max_score")),
                   "correct": 0, "incorrect": 0, "blank": 0},
            "multiple_marks": row.get("multiple_marks", ""),
        })
        for number, key in (numbers.get(model_id) or {}).items():
            question = questions.get(key)
            if not question or question["type"] != "mc" or f"answer_{number}" not in row:
                continue
            letter = str(row.get(f"answer_{number}", "")).strip().upper()
            blank = letter in ("", "NA", "NONE", "-")
            index = None if blank else question["letters"].get(model_id, {}).get(letter)
            correct = None if index is None else question["options"][index]["correct"]
            student["mc"]["blank" if blank else ("correct" if correct else "incorrect")] += 1
            points = question["points"] or 0
            score = 0.0 if blank or correct is None else (points if correct else -(cfg.penalty or 0) * points)
            printed = question["letters"].get(model_id, {})
            right = next((i for i, o in enumerate(question["options"]) if o["correct"]), None)
            correct_letter = next((l for l, i in printed.items() if i == right), "")
            answers.append({"key": f"{sid}|{key}", "student": sid, "question": key, "type": "mc",
                            "number": number, "letter": "" if blank else letter, "option": index,
                            "correct": correct, "correct_letter": correct_letter, "score": score, "max": points})


def _free_pages(first_page, bases, pages_per_exam: int) -> list[str]:
    """The pages of a blank-paper exam from its first page (``page_007.png``) and the run's
    ``--pages-per-exam``: results written before exam-free kept the list of pages."""
    full = resolve(first_page, bases)
    match = re.match(r"^(.*page_)(\d+)(\.\w+)$", full or "")
    if not match:
        return [first_page] if first_page else []
    start, width = int(match.group(2)), len(match.group(2))
    return [p for p in (f"{match.group(1)}{start + i:0{width}d}{match.group(3)}" for i in range(pages_per_exam)) if os.path.exists(p)]


def _open_answers(cfg: ReviewConfig, questions: dict, numbers: dict, students: dict, answers: list):
    from ..exam_open import _review_reasons

    manifest = read_manifest(cfg.open_dir)
    cfg._pages_per_exam = int(manifest.get("pages_per_exam") or 1) if manifest.get("tool") == "pevaluate exam-free" else 0

    path = os.path.join(cfg.open_dir, "open_evaluations.yaml")
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) if os.path.exists(path) else {}
    scores = {(r.get("student_id", ""), r.get("question_id", "")): r
              for r in _read_csv(os.path.join(cfg.open_dir, "open_scores.csv"))}
    index = {(r.get("student_id", ""), r.get("question_id", "")): r for r in _read_csv(cfg.index_csv)}
    index_dir = os.path.dirname(cfg.index_csv) if cfg.index_csv else None
    bases = [b for b in [cfg.open_dir, index_dir, *cfg.base_dirs] if b]
    for item in (data or {}).get("responses", []) or []:
        sid, qid = str(item.get("student_id", "")), str(item.get("question_id", ""))
        model_id = str(item.get("model_id", ""))
        key = str(item.get("original_id") or (numbers.get(model_id) or {}).get(qid) or f"q{qid}")
        question = questions.get(key)
        if question is None:  # exam-free without exam_dir, or a question missing from the exam folder
            question = questions[key] = {
                "key": key, "number": qid, "numbers": {model_id: qid}, "type": "open",
                "points": to_float(item.get("max_score")),
                "text_html": render_markdown(item.get("question_text"), cfg._files), "image": "", "options": [],
                "expected_html": "", "rubric_html": "", "explanation_html": "", "letters": {}}
        student = students.setdefault(sid, {"key": sid, "id": sid, "name": item.get("student_name", "")})
        student.setdefault("model_id", model_id)
        extra = {**index.get((sid, qid), {}), **scores.get((sid, qid), {})}
        images = []
        for label, value in (("answer", item.get("crop_path")), ("with surroundings", extra.get("context_crop_path"))):
            full = resolve(value, bases)
            if full and full not in [i["path"] for i in images]:
                images.append({"label": label, "path": full})
        pages = item.get("pages") or (_free_pages(item.get("crop_path"), bases, cfg._pages_per_exam) if cfg._pages_per_exam else [])
        if pages:  # a blank-paper exam: the student's whole pages, not a crop of one answer
            images = []
            for i, page in enumerate(pages):
                full = resolve(page, bases)
                if full:
                    images.append({"label": f"page {i + 1}", "path": full})
        grader = item.get("grader") or {}
        warnings = item.get("conversion_warnings") or []
        row = {**extra, **item, "conversion_warnings": "; ".join(warnings) if isinstance(warnings, list) else str(warnings)}
        if "score" not in grader and f"{sid}|{key}" in cfg._originals:
            grader = cfg._originals[f"{sid}|{key}"]
        has_original = "score" in grader
        edited = has_original and (to_float(grader.get("score")) != to_float(item.get("score")) or
                                   str(grader.get("feedback") or "").strip() != str(item.get("feedback") or "").strip())
        answers.append({
            "key": f"{sid}|{key}", "student": sid, "question": key, "type": "open", "number": qid,
            "score": to_float(item.get("score")), "max": to_float(item.get("max_score")) or question.get("points"),
            "feedback": str(item.get("feedback") or ""),
            "feedback_html": render_markdown(item.get("feedback"), cfg._files),
            "response_html": render_markdown(item.get("response_markdown"), cfg._files),
            "warnings": warnings if isinstance(warnings, list) else [str(warnings)],
            "confidence": to_float(item.get("confidence")), "status": item.get("status", ""),
            "graded_from": item.get("graded_from", "box"),
            "images": [{"label": i["label"], "url": cfg._files.url(i["path"])} for i in images],
            "llm_score": to_float(grader.get("score")) if has_original else None,
            "llm_feedback": str(grader.get("feedback") or "") if has_original else None,
            "edited": bool(edited), "reasons": [] if edited else _review_reasons(row),
            "source": {"file": "open", "student_id": sid, "question_id": qid},
        })


def _question_stats(questions: dict, answers: list, students: dict) -> None:
    totals = {s["key"]: s.get("mark") for s in students.values()}
    for question in questions.values():
        rows = [a for a in answers if a["question"] == question["key"]]
        stats = {"n": len(rows)}
        if question["type"] == "mc":
            counts = [0] * len(question["options"])
            for a in rows:
                if a["option"] is not None:
                    counts[a["option"]] += 1
            answered = [a for a in rows if a["option"] is not None]
            stats.update({
                "counts": counts, "blank": len(rows) - len(answered),
                "correct": sum(1 for a in answered if a["correct"]),
                "p_correct": (sum(1 for a in answered if a["correct"]) / len(rows)) if rows else None,
            })
            # Discrimination: correlation between answering right and the student's mark.
            pairs = [(1.0 if a["correct"] else 0.0, totals.get(a["student"])) for a in rows]
            pairs = [(x, y) for x, y in pairs if y is not None]
            if len(pairs) >= 3 and len({x for x, _ in pairs}) > 1 and len({y for _, y in pairs}) > 1:
                stats["discrimination"] = round(statistics.correlation([x for x, _ in pairs], [y for _, y in pairs]), 2)
        else:
            graded = [a for a in rows if a["score"] is not None]
            points = question.get("points") or (graded[0]["max"] if graded else None)
            stats.update({
                "graded": len(graded),
                "mean": statistics.mean(a["score"] for a in graded) if graded else None,
                "full": sum(1 for a in graded if points and a["score"] >= points - 1e-9),
                "zero": sum(1 for a in graded if a["score"] == 0),
                "edited": sum(1 for a in rows if a["edited"]), "flagged": sum(1 for a in rows if a["reasons"]),
            })
        question["stats"] = stats


def _exam_marks(cfg: ReviewConfig, students: dict, answers: list) -> None:
    overall = {r.get("student_id", ""): r for r in _read_csv(os.path.join(cfg.open_dir, "overall_marks.csv"))} if cfg.open_dir else {}
    for sid, student in students.items():
        row = overall.get(sid)
        opens = [a for a in answers if a["student"] == sid and a["type"] == "open"]
        open_score = sum(a["score"] or 0 for a in opens)
        open_max = sum(a["max"] or 0 for a in opens)
        student["open"] = {"score": open_score, "max": open_max} if opens else None
        if row:
            student["mark"] = to_float(row.get("mark"))
            student["voided"] = row.get("voided_questions", "")
        elif student.get("mc") and student["mc"].get("score") is not None and not opens:
            mc = student["mc"]
            student["mark"] = 10 * mc["score"] / mc["max"] if mc.get("max") else None
        elif opens and open_max:
            mc = student.get("mc") or {}
            total = open_score + (mc.get("score") or 0)
            student["mark"] = 10 * total / (open_max + (mc.get("max") or 0))
        else:
            student["mark"] = None


# --- Lab submissions -----------------------------------------------------------------------------

def _file_kind(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in (".html", ".htm"):
        return "html"
    if suffix in RENDERED_EXTENSIONS:
        return "rendered"
    if suffix in TEXT_EXTENSIONS:
        return "text"
    return "other"


def _submitter(path: str) -> dict:
    from ..submissions import POLIFORMAT_FOLDER, get_student_name_from_path

    for part in reversed(Path(path).parts):
        match = POLIFORMAT_FOLDER.match(part)
        if match:
            surname, _, name = match.group("name").partition(",")
            return {"id": match.group("id").strip(), "name": f"{name.strip()} {surname.strip()}".strip()}
    return {"id": "", "name": get_student_name_from_path(path) if path else ""}


def _lab(cfg: ReviewConfig, model: dict) -> None:
    from ..names import name_similarity

    manifest = read_manifest(cfg.feedback_dir)
    session = (manifest.get("session_folder") or "")
    bases = [b for b in [*cfg.base_dirs, manifest.get("cwd"), os.path.dirname(session) if session else None,
                         *_ancestors(cfg.feedback_dir)] if b]
    rubric = cfg.rubric or next((p for p in (manifest.get("inputs_sha256") or {}) if "rubric" in Path(p).name.lower()), None)
    rubric = resolve(rubric, bases) if rubric else ""
    if rubric:
        text = Path(rubric).read_text(encoding="utf-8", errors="replace")
        model["rubric_html"] = f"<pre class='rubric'>{html.escape(text)}</pre>"
    submissions = []
    for path in sorted(glob.glob(os.path.join(cfg.feedback_dir, "feedback_*.yaml"))):
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        grader = data.get("grader") or {}
        sources = data.get("submission_files") or [data.get("submission_file")]
        files = []
        for source in sources:
            full = resolve(source, bases)
            name = Path(str(source or "")).name
            kind = _file_kind(full or name)
            files.append({"name": name, "kind": kind if full else "missing",
                          "url": cfg._files.url(full) if full else "",
                          "render": cfg._files.url(full, "r") if full and kind == "rendered" else ""})
        submitter = _submitter(str(sources[0] or ""))
        members = [{"name": str(s.get("full_name", s) if isinstance(s, dict) else s)} for s in data.get("students") or []]
        people = list(members)
        if submitter["name"] and not any(name_similarity(submitter["name"], m["name"]) >= 70 for m in members):
            people.insert(0, {"name": submitter["name"], "added": "submitter"})
        if "mark" not in grader and Path(path).stem in cfg._originals:
            grader = cfg._originals[Path(path).stem]
        has_original = "mark" in grader
        edited = has_original and (to_float(grader.get("mark")) != to_float(data.get("mark")) or
                                   str(grader.get("feedback") or "").strip() != str(data.get("feedback") or "").strip())
        submissions.append({
            "key": Path(path).stem, "file": path, "version": file_version(path),
            "submitter": submitter, "members": people,
            "mark": to_float(data.get("mark")), "feedback": str(data.get("feedback") or ""),
            "feedback_html": render_comment(data.get("feedback")),
            "llm_mark": to_float(grader.get("mark")) if has_original else None,
            "llm_feedback": str(grader.get("feedback") or "") if has_original else None,
            "edited": bool(edited), "files": files,
        })
    model["submissions"] = submissions


# --- Roster ----------------------------------------------------------------------------------------

def _match_roster(cfg: ReviewConfig, model: dict) -> None:
    from ..roster import load_roster, match_people

    if not cfg.roster:
        return
    try:
        roster = load_roster(cfg.roster, cfg.roster_id_column, cfg.roster_name_column)
    except Exception as e:  # a wrong export should not stop the review
        model["warnings"].append(f"Class list not read ({cfg.roster}): {e}")
        return
    model["roster"] = {"source": cfg.roster, "students": roster}
    if model["kind"] == "lab":
        people = [(s, m) for s in model["submissions"] for m in s["members"]]
        for m in [m for _, m in people]:
            m.setdefault("id", "")
        submitters = {id(s): s["submitter"] for s in model["submissions"]}
        for s, m in people:  # the submitter's folder gives the ID
            if m.get("added") == "submitter" or (submitters[id(s)]["name"] and m["name"] == submitters[id(s)]["name"]):
                m["id"] = submitters[id(s)]["id"]
        found = match_people([m for _, m in people], roster)
        for i, (_, m) in enumerate(people):
            if i in found:
                j, method, score = found[i]
                m.update({"roster": j, "match": method, "match_score": round(score)})
        # A roster student found in more than one submission (a group that submitted twice).
        seen = {}
        for s, m in people:
            if "roster" in m:
                seen.setdefault(m["roster"], []).append(s["key"])
        model["roster"]["in_submissions"] = seen
    else:
        students = model["students"]
        found = match_people([{"id": s["id"], "name": s["name"]} for s in students], roster)
        for i, s in enumerate(students):
            if i in found:
                j, method, score = found[i]
                s.update({"roster": j, "match": method, "match_score": round(score)})
        model["roster"]["matched"] = sorted(j for j, _, _ in found.values())


# --- Model -----------------------------------------------------------------------------------------

def _review_state_path(cfg: ReviewConfig) -> Optional[str]:
    folder = cfg.feedback_dir or cfg.open_dir or cfg.mc_dir
    return os.path.join(folder, "review_state.json") if folder else None


def load_review_state(cfg: ReviewConfig) -> dict:
    path = _review_state_path(cfg)
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")) if path and os.path.exists(path) else {}
    except (OSError, ValueError):
        return {}


STALE = {
    "es": {"mc": "Las respuestas del test o los estudiantes han cambiado desde el último análisis.",
           "open": "Las notas de las preguntas abiertas han cambiado desde que se generaron las notas y los PDF.",
           "both": "Las notas del test son más recientes que las notas finales."},
    "en": {"mc": "Multiple-choice answers or students changed since the last analysis.",
           "open": "Open-answer grades changed since the marks and PDFs were built.",
           "both": "The multiple-choice marks are newer than the overall marks."},
}


def _stale(cfg: ReviewConfig) -> list[str]:
    """Edited results newer than the marks and PDFs built from them."""
    texts = STALE.get(cfg.lang, STALE["en"])
    messages = []
    newer = lambda a, b: os.path.exists(a) and (not os.path.exists(b) or os.path.getmtime(a) > os.path.getmtime(b) + 1)
    if cfg.mc_dir and newer(os.path.join(cfg.mc_dir, "correction_results.csv"), os.path.join(cfg.mc_dir, "final_marks.csv")):
        messages.append(texts["mc"])
    if cfg.open_dir and newer(os.path.join(cfg.open_dir, "open_evaluations.yaml"), os.path.join(cfg.open_dir, "open_scores.csv")):
        messages.append(texts["open"])
    overall = os.path.join(cfg.open_dir, "overall_marks.csv") if cfg.open_dir else ""
    if cfg.mc_dir and overall and os.path.exists(overall) and newer(os.path.join(cfg.mc_dir, "final_marks.csv"), overall):
        messages.append(texts["both"])
    return messages


def load_review(cfg: ReviewConfig) -> dict:
    """The whole model the page shows (re-read from disk on every call)."""
    cfg._files = Files()
    state = load_review_state(cfg)
    cfg._originals = state.get("originals", {})
    model = {"title": cfg.title, "kind": "lab" if cfg.feedback_dir else "exam", "lang": cfg.lang,
             "warnings": [], "students": [], "questions": [], "answers": [], "submissions": [], "roster": None,
             "rebuild": [{"id": a.id, "label": a.label, "description": a.description} for a in cfg.rebuild_actions],
             "versions": {}, "stale": _stale(cfg), "penalty": cfg.penalty}
    if cfg.feedback_dir:
        _lab(cfg, model)
    else:
        questions, numbers = load_questions(cfg.exam_dir, cfg._files)
        students, answers = {}, []
        if cfg.mc_dir:
            _mc_answers(cfg, questions, numbers, students, answers)
            model["versions"]["mc"] = file_version(os.path.join(cfg.mc_dir, "correction_results.csv"))
        if cfg.open_dir:
            _open_answers(cfg, questions, numbers, students, answers)
            model["versions"]["open"] = file_version(os.path.join(cfg.open_dir, "open_evaluations.yaml"))
        _exam_marks(cfg, students, answers)
        for question in questions.values():
            void_all, void_nicely = ((cfg.mc_void, cfg.mc_void_nicely) if question["type"] == "mc"
                                     else (cfg.open_void, cfg.open_void_nicely))
            question["voided"] = _void_kind(question, void_all, void_nicely)
        _question_stats(questions, answers, students)
        order = lambda q: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", str(q["number"]))]
        model["questions"] = sorted(questions.values(), key=order)
        for q in model["questions"]:
            q.pop("letters", None)
            for o in q["options"]:
                o.pop("text", None)
        model["students"] = sorted(students.values(), key=lambda s: (s.get("name") or s["id"]).lower())
        model["answers"] = answers
    _match_roster(cfg, model)
    model["reviewed"] = state.get("reviewed", {})
    model["review_state_file"] = _review_state_path(cfg)
    return model


# --- Standalone: find the folders from what the user points at -------------------------------------

def detect_config(paths: list[str], **overrides) -> ReviewConfig:
    """A configuration from result folders (exam-open/exam-free output, pexams correction folder,
    lab ``feedback/`` folder, or a lab session folder), completed from their run manifests."""
    cfg = ReviewConfig()
    for raw in paths:
        folder = os.path.abspath(raw)
        if os.path.exists(os.path.join(folder, "open_evaluations.yaml")):
            cfg.open_dir = folder
        elif os.path.exists(os.path.join(folder, "correction_results.csv")):
            cfg.mc_dir = folder
        elif glob.glob(os.path.join(folder, "feedback_*.yaml")):
            cfg.feedback_dir = folder
        elif glob.glob(os.path.join(folder, "feedback", "feedback_*.yaml")):
            cfg.feedback_dir = os.path.join(folder, "feedback")
        else:
            raise ValueError(f"{raw}: no open_evaluations.yaml, correction_results.csv or feedback_*.yaml found.")
    for which in ("open_dir", "mc_dir"):  # the open-answer manifest may name the pexams folder
        folder = getattr(cfg, which)
        manifest = read_manifest(folder)
        if not manifest:
            continue
        bases = [b for b in [manifest.get("cwd"), *_ancestors(folder)] if b]
        cfg.base_dirs += [b for b in bases if b not in cfg.base_dirs]
        exam_dir = manifest.get("exam_dir") or manifest_option(manifest, "--exam-dir")
        cfg.exam_dir = cfg.exam_dir or resolve(exam_dir, bases) or None
        if folder == cfg.open_dir:
            cfg.mc_dir = cfg.mc_dir or resolve(manifest_option(manifest, "--mc-correction-dir"), bases) or None
            cfg.index_csv = cfg.index_csv or resolve(manifest_option(manifest, "--index-csv"), bases) or None
            cfg.open_void = cfg.open_void or _split_list(manifest_option(manifest, "--void-questions"))
            cfg.open_void_nicely = cfg.open_void_nicely or _split_list(manifest_option(manifest, "--void-questions-nicely"))
            cfg.lang = manifest_option(manifest, "--lang") or cfg.lang
        if folder == cfg.mc_dir and cfg.penalty is None:
            cfg.penalty = to_float(manifest_option(manifest, "--penalty"))
    if cfg.mc_dir and not cfg.index_csv and os.path.exists(os.path.join(cfg.mc_dir, "open_responses_index.csv")):
        cfg.index_csv = os.path.join(cfg.mc_dir, "open_responses_index.csv")
    for key, value in overrides.items():
        if value not in (None, [], ""):
            setattr(cfg, key, value)
    cfg.title = overrides.get("title") or Path(cfg.feedback_dir or cfg.open_dir or cfg.mc_dir).parent.name
    return cfg


def manifest_rebuild_command(folder: str) -> Optional[tuple[list[str], str]]:
    """The exam-open/exam-free command of the last run (``argv``, working folder), to rebuild
    the marks and PDFs from the saved grades. None if the manifest has no usable command."""
    manifest = read_manifest(folder)
    command = list(manifest.get("command") or [])
    if not command or manifest.get("tool") not in ("pevaluate exam-open", "pevaluate exam-free"):
        return None
    cwd = manifest.get("cwd")
    if not cwd:
        # Older manifests have no cwd: the folder from which --output-dir resolves to this folder.
        output = manifest_option(manifest, "--output-dir") or ""
        cwd = next((b for b in _ancestors(folder) if os.path.abspath(os.path.join(b, output)) == os.path.abspath(folder)), None)
    if not cwd:
        return None
    command = [c for c in command if c != "--force-regrade"]
    return command, cwd


def describe_command(argv: list[str], cwd: str) -> str:
    return f"cd {shlex.quote(cwd)} && {shlex.join(argv)}"
