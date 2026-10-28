"""Build the zip for a PoliformaT (UPV, Sakai) assignment's "Subir todo" from its "Descargar todo"
(``pevaluate poliformat-zip``): the grade of each student in ``grades.xls``/``grades.csv``, a
comment in their ``comments.txt`` and their feedback PDF in "Adjuntos al comentario".

The download is used as the template, so the zip keeps exactly its structure:

    <assignment>/grades.xls (or grades.csv)       Identificador, ID, Apellido, Nombre, Calificación, ...
    <assignment>/<Apellido, Nombre(ID)>/comments.txt               -> "Comentarios del docente"
    <assignment>/<Apellido, Nombre(ID)>/feedbackText.html          -> "Texto de la realimentación"
    <assignment>/<Apellido, Nombre(ID)>/Adjuntos al comentario/    -> feedback attachments
    <assignment>/<Apellido, Nombre(ID)>/Adjuntos de la entrega/    -> the student's submission
    <assignment>/<Apellido, Nombre(ID)>/<...>_submissionText.html

Folder names have no accents while grades.xls has them, so folders and grade rows are linked by
the ID in brackets. Students are matched to the marks by ID (the ID read from the exam contains
the PoliformaT one, e.g. DNI digits) and then by name.
"""
import argparse
import csv
import html
import re
import shutil
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from typing import Optional

from .common import read_csv_rows, safe_name, to_float
from .names import name_similarity
from .roster import match_people

DESCRIPTION = __doc__

ATTACHMENTS_DIR_NAMES = ("Adjuntos al comentario", "Adjunts al comentari", "Feedback Attachment(s)", "Feedback Attachments")
_FOLDER_ID = re.compile(r"\((?P<id>[^()]*)\)\s*$")

COMMENTS = {
    "es": {"mark": "Nota: {mark} sobre 10.", "pdf": "La corrección de cada pregunta está en el PDF adjunto."},
    "ca": {"mark": "Nota: {mark} sobre 10.", "pdf": "La correcció de cada pregunta és al PDF adjunt."},
    "en": {"mark": "Mark: {mark} out of 10.", "pdf": "The correction of each question is in the attached PDF."},
}


def _key(text) -> str:
    """Lower case, no accents or punctuation: to recognise column names in any language."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    return re.sub(r"[^a-z0-9]+", "", "".join(c for c in text if not unicodedata.combining(c)).lower())


def _column(header: list, *candidates: str) -> Optional[int]:
    keys = [_key(h) for h in header]
    for candidate in candidates:
        if _key(candidate) in keys:
            return keys.index(_key(candidate))
    return None


def format_grade(mark: float, decimal_sep: str = ",") -> str:
    """PoliformaT grade with two decimals, e.g. 8,60 (the decimal separator of the site language)."""
    return f"{float(mark):.2f}".replace(".", decimal_sep)


# --- The download (template) -------------------------------------------------------------------

class GradesFile:
    """grades.xls or grades.csv of a PoliformaT download: header row and data rows, kept as text."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.sheet_name = "Sheet1"
        self.csv_dialect = None
        self.preamble: list[list[str]] = []  # rows above the header (some CSV exports have a title)
        if self.path.suffix.lower() == ".xls":
            import xlrd

            book = xlrd.open_workbook(str(self.path))
            sheet = book.sheet_by_index(0)
            self.sheet_name = sheet.name
            rows = [[self._cell_text(sheet.cell(r, c)) for c in range(sheet.ncols)] for r in range(sheet.nrows)]
        else:
            text = self.path.read_text(encoding="utf-8-sig")
            self.csv_dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
            rows = list(csv.reader(text.splitlines(), self.csv_dialect))
        header_index = next((i for i, row in enumerate(rows) if self._find_columns(row)), None)
        if header_index is None:
            raise ValueError(f"{self.path}: no header with an ID and a grade column (Identificador/ID, Calificación).")
        self.preamble, self.header, self.rows = rows[:header_index], rows[header_index], rows[header_index + 1:]
        self.id_col, self.grade_col = self._find_columns(self.header)
        self.surname_col = _column(self.header, "Apellido", "Cognom", "Last Name")
        self.name_col = _column(self.header, "Nombre", "Nom", "First Name")

    @staticmethod
    def _cell_text(cell) -> str:
        import xlrd

        if cell.ctype == xlrd.XL_CELL_NUMBER and float(cell.value).is_integer():
            return str(int(cell.value))
        return "" if cell.ctype == xlrd.XL_CELL_EMPTY else str(cell.value)

    @staticmethod
    def _find_columns(row):
        id_col = _column(row, "ID", "Identificador", "Display ID")
        grade_col = _column(row, "Calificación", "Qualificació", "Grade")
        return (id_col, grade_col) if id_col is not None and grade_col is not None else None

    def student_name(self, row: list) -> str:
        surname = row[self.surname_col] if self.surname_col is not None else ""
        name = row[self.name_col] if self.name_col is not None else ""
        return f"{surname}, {name}".strip(", ")

    def write(self, path: Path) -> None:
        width = len(self.header)
        rows = self.preamble + [self.header] + [row + [""] * (width - len(row)) for row in self.rows]
        if self.path.suffix.lower() == ".xls":
            import xlwt

            book = xlwt.Workbook(encoding="utf-8")
            sheet = book.add_sheet(self.sheet_name[:31])
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    sheet.write(r, c, value)
            book.save(str(path))
        else:
            with open(path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f, self.csv_dialect).writerows(rows)


def _open_download(path: str, workdir: str) -> Path:
    """The assignment folder of the download (a zip, or an already extracted folder)."""
    source = Path(path)
    if source.is_file() and zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            archive.extractall(workdir)
        root = Path(workdir)
    elif source.is_dir():
        root = Path(workdir) / source.name
        shutil.copytree(source, root)
    else:
        raise ValueError(f"{path} is not a PoliformaT download (zip or folder).")
    grades = sorted(root.rglob("grades.xls")) + sorted(root.rglob("grades.csv"))
    if not grades:
        raise ValueError(f"{path}: no grades.xls or grades.csv. Download it with 'Archivo de calificaciones' ticked.")
    return grades[0].parent


def student_folders(assignment_dir: Path) -> dict:
    """{ID in brackets: student folder}."""
    folders = {}
    for folder in assignment_dir.iterdir():
        match = _FOLDER_ID.search(folder.name) if folder.is_dir() else None
        if match:
            folders[match.group("id").strip()] = folder
    return folders


# --- Matching ----------------------------------------------------------------------------------

def read_marks(path: str) -> list[dict]:
    """Rows of ``overall_marks.csv`` (exam-open) or of a ``combine-marks`` output, as
    {student_id, name, mark, feedback}."""
    text = Path(path).read_text(encoding="utf-8-sig")
    delimiter = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
    marks = []
    for row in read_csv_rows(path, encoding="utf-8-sig", delimiter=delimiter):
        get = lambda *names: next((row[n] for n in names if n in row and str(row[n]).strip() != ""), "")
        mark = to_float(str(get("mark", "final_mark", "nota_10")).replace(",", "."))
        marks.append({"student_id": get("student_id", "id"), "name": get("student_name", "name"),
                      "mark": mark, "feedback": get("feedback")})
    return marks


def read_feedback_dir(path: str) -> list[dict]:
    """Marks of the submissions graded with ``pevaluate <folder>`` (one ``feedback_*.yaml`` each),
    one row per student: whoever submitted it (the PoliformaT folder of the file, with its ID) and
    every other member of the group named by the grader, all with the group's mark and feedback."""
    import yaml

    from .submissions import POLIFORMAT_FOLDER

    marks = []
    for yaml_path in sorted(Path(path).glob("feedback_*.yaml")):
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        mark = to_float(str(data.get("mark", "")).replace(",", "."))
        feedback = str(data.get("feedback") or "").strip()
        rows = []
        folder = next((part for part in reversed(Path(str(data.get("submission_file", ""))).parts)
                       if POLIFORMAT_FOLDER.match(part)), None)
        if folder:
            match = POLIFORMAT_FOLDER.match(folder)
            surname, _, name = match.group("name").partition(",")
            rows.append({"student_id": match.group("id").strip(), "name": f"{name.strip()} {surname.strip()}"})
        for student in data.get("students") or []:
            full_name = str(student.get("full_name", "") if isinstance(student, dict) else student).strip()
            if full_name and not any(name_similarity(full_name, row["name"]) >= 70 for row in rows):
                rows.append({"student_id": "", "name": full_name})
        for row in rows:
            marks.append({**row, "mark": mark, "feedback": feedback, "source": yaml_path.name})
    return marks


def feedback_html(text: str) -> str:
    """The grader's feedback for comments.txt, which PoliformaT shows as HTML: paragraphs at
    blank lines, line breaks kept, **bold** kept."""
    paragraphs = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    rendered = []
    for paragraph in paragraphs:
        lines = [re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(line.rstrip()))
                 for line in paragraph.splitlines()]
        rendered.append("<p>" + "<br>\n".join(lines) + "</p>")
    return "\n".join(rendered)


def match_students(grades: GradesFile, marks: list[dict], name_threshold: float = 70.0) -> tuple[dict, list]:
    """{grade row index: marks row}, one-to-one: first by ID (one contains the other, e.g. the DNI
    digits inside a DNI read with its letter), then by the most similar name. Returns also the
    list of (row index, mark row, method, score) for the record."""
    people = [{"id": row[grades.id_col], "name": grades.student_name(row)} for row in grades.rows]
    found = match_people(people, [{"id": m["student_id"], "name": m["name"]} for m in marks], name_threshold)
    matched = {i: marks[j] for i, (j, _, _) in found.items()}
    record = [(i, marks[j], method, score) for i, (j, method, score) in found.items()]
    return matched, record


# --- Building the upload -----------------------------------------------------------------------

def build_poliformat_zip(download: str, marks_csv: Optional[str], output: str, feedback_pdfs: Optional[str] = None,
                         lang: str = "es", comment: Optional[str] = None, attachment_name: Optional[str] = None,
                         decimal_sep: str = ",", name_threshold: float = 70.0,
                         feedback_dir: Optional[str] = None) -> dict:
    """Fill the download with grades, comments and feedback PDFs and zip it for "Subir todo".
    The marks come from a CSV (``marks_csv``) or from graded submissions (``feedback_dir``).
    Returns a summary: matched students, students without mark, marks without student."""
    marks = read_feedback_dir(feedback_dir) if feedback_dir else read_marks(marks_csv)
    texts = COMMENTS.get(lang, COMMENTS["es"])
    with tempfile.TemporaryDirectory() as workdir:
        assignment_dir = _open_download(download, workdir)
        grades_path = next(p for p in (assignment_dir / "grades.xls", assignment_dir / "grades.csv") if p.exists())
        grades = GradesFile(grades_path)
        folders = student_folders(assignment_dir)
        matched, record = match_students(grades, marks, name_threshold)

        pdf_name = attachment_name or f"Correccion {safe_name(assignment_dir.name).replace('_', ' ')}.pdf"
        summary = {"assignment": assignment_dir.name, "matched": [], "no_mark": [], "unmatched_marks": [],
                   "missing_pdf": [], "missing_folder": []}
        for i, row in enumerate(grades.rows):
            name = grades.student_name(row)
            item = matched.get(i)
            if item is None or item["mark"] is None:
                summary["no_mark"].append(name)
                continue
            row += [""] * (len(grades.header) - len(row))
            row[grades.grade_col] = format_grade(item["mark"], decimal_sep)
            method, score = next((m, s) for r, it, m, s in record if r == i)
            summary["matched"].append((name, item["name"], item["student_id"], method, round(score, 1), row[grades.grade_col]))

            folder = folders.get(str(row[grades.id_col]).strip())
            if folder is None:
                summary["missing_folder"].append(name)
                continue
            pdf = Path(feedback_pdfs) / f"{safe_name(item['student_id'])}.pdf" if feedback_pdfs else None
            has_pdf = bool(pdf and pdf.exists())
            if feedback_pdfs and not has_pdf:
                summary["missing_pdf"].append(name)
            text = comment.format(mark=row[grades.grade_col]) if comment else " ".join(
                [texts["mark"].format(mark=row[grades.grade_col])] + ([texts["pdf"]] if has_pdf else []))
            if item.get("feedback"):
                text = f"<p>{html.escape(text)}</p>\n{feedback_html(item['feedback'])}"
            (folder / "comments.txt").write_text(text, encoding="utf-8")
            if has_pdf:
                attachments = next((folder / d for d in ATTACHMENTS_DIR_NAMES if (folder / d).is_dir()),
                                   folder / ATTACHMENTS_DIR_NAMES[0])
                attachments.mkdir(exist_ok=True)
                shutil.copyfile(pdf, attachments / pdf_name)
        matched_marks = {id(it) for it in matched.values()}
        summary["unmatched_marks"] = [f"{m['name']} ({m['student_id'] or m.get('source', '')})"
                                      for m in marks if id(m) not in matched_marks]

        grades.write(grades_path)
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(assignment_dir.rglob("*")):
                arcname = str(Path(assignment_dir.name) / path.relative_to(assignment_dir))
                if path.is_dir():
                    if not any(path.iterdir()):  # like PoliformaT: entries only for empty folders
                        archive.write(path, arcname + "/")
                elif path.name != ".DS_Store":
                    archive.write(path, arcname)
    return summary


def build_parser(parser: Optional[argparse.ArgumentParser] = None) -> argparse.ArgumentParser:
    parser = parser or argparse.ArgumentParser(prog="pevaluate poliformat-zip", description=DESCRIPTION,
                                               formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("download", help="The assignment's 'Descargar todo' zip (or its extracted folder), with "
                                         "'Archivo de calificaciones' and 'Incluir estudiantes que no han realizado un envío' ticked.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--marks", help="overall_marks.csv from exam-open (or a combine-marks output): student_id, student_name, mark.")
    source.add_argument("--feedback-dir", help="feedback/ folder of submissions graded with 'pevaluate <folder>': each group's mark "
                                               "and feedback go to whoever submitted and to every member named by the grader.")
    parser.add_argument("--feedback-pdfs", help="Folder with one PDF per student named <student_id>.pdf (exam-open's student_feedback_pdfs/), "
                                                "attached to each student's comment.")
    parser.add_argument("--output", required=True, help="The zip to upload with 'Subir todo'.")
    parser.add_argument("--lang", choices=sorted(COMMENTS), default="es", help="Language of the default comment (default: es).")
    parser.add_argument("--comment", help="Comment for every student instead of the default; {mark} is replaced by the grade.")
    parser.add_argument("--attachment-name", help="File name of the attached PDF (default: 'Correccion <assignment>.pdf').")
    parser.add_argument("--decimal-sep", default=",", help="Decimal separator of the grades (default ',' for a site in Spanish or Valencian).")
    parser.add_argument("--name-threshold", type=float, default=70.0, help="Minimum name similarity (0-100) when the ID does not match.")
    return parser


def run(args: argparse.Namespace):
    summary = build_poliformat_zip(args.download, args.marks, args.output, feedback_pdfs=args.feedback_pdfs,
                                   lang=args.lang, comment=args.comment, attachment_name=args.attachment_name,
                                   decimal_sep=args.decimal_sep, name_threshold=args.name_threshold,
                                   feedback_dir=args.feedback_dir)
    print(f"Assignment: {summary['assignment']}")
    print(f"Graded: {len(summary['matched'])} student(s)")
    for poliformat_name, our_name, our_id, method, score, grade in summary["matched"]:
        print(f"  {poliformat_name:<40} {grade:>6}  <- {our_name} ({our_id}) [{method}{'' if method == 'id' else f' {score}'}]")
    for key, label in (("no_mark", "In PoliformaT without a mark (left ungraded)"),
                       ("unmatched_marks", "Marks not matched to any PoliformaT student"),
                       ("missing_pdf", "Graded without a feedback PDF"),
                       ("missing_folder", "Graded but without a folder in the download (comment and PDF not added)")):
        if summary[key]:
            print(f"{label} ({len(summary[key])}): " + "; ".join(summary[key]))
    print(f"Zip for 'Subir todo': {args.output}")


def main(argv: Optional[list[str]] = None):
    run(build_parser().parse_args(argv))
