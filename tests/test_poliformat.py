import csv
import zipfile

import xlrd
import xlwt

from autocorrect.poliformat import build_poliformat_zip, format_grade

HEADER = ["Identificador", "ID", "Apellido", "Nombre", "Calificación", "Fecha de envío", "Envío fuera de plazo"]
# (ID, surname, name, folder name): PoliformaT writes the folder names without accents.
STUDENTS = [("11223344", "Núñez Pérez", "Lucía", "Nunez Perez, Lucia(11223344)"),
            ("55667788", "Soler Vidal", "Marta", "Soler Vidal, Marta(55667788)"),
            ("99001122", "Forés Llop", "Inés", "Fores Llop, Ines(99001122)")]


def _download(tmp_path):
    """A 'Descargar todo' zip like PoliformaT's: grades.xls with accents, folders without them."""
    root = tmp_path / "download" / "Tarea 1"
    book = xlwt.Workbook(encoding="utf-8")
    sheet = book.add_sheet("Tarea 1")
    for c, value in enumerate(HEADER):
        sheet.write(0, c, value)
    for r, (sid, surname, name, folder_name) in enumerate(STUDENTS, start=1):
        for c, value in enumerate([sid, sid, surname, name, "", "", "Desconocido"]):
            sheet.write(r, c, value)
        folder = root / folder_name
        for sub in ("Adjuntos al comentario", "Adjuntos de la entrega"):
            (folder / sub).mkdir(parents=True)
        for f in ("comments.txt", "feedbackText.html", f"{folder.name}_submissionText.html"):
            (folder / f).write_text("", encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    book.save(str(root / "grades.xls"))
    path = tmp_path / "Tarea 1_20260101.zip"
    with zipfile.ZipFile(path, "w") as z:
        for p in sorted(root.parent.rglob("*")):
            z.write(p, str(p.relative_to(root.parent)) + ("/" if p.is_dir() else ""))
    return path


def test_poliformat_zip_fills_grades_comments_and_pdfs(tmp_path):
    marks = tmp_path / "overall_marks.csv"
    with open(marks, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["student_id", "student_name", "mark"])
        writer.writerow(["11223344LUNUPE", "Lucía Núñez Pérez", "8.6721"])   # matched by ID (DNI digits)
        writer.writerow(["MSOLVID", "Marta Soler Vidal", "5.1"])                # matched by name
        writer.writerow(["XYZ", "Someone Else", "3"])                             # not in PoliformaT
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    (pdfs / "11223344LUNUPE.pdf").write_bytes(b"%PDF-1.4 fake")

    out = tmp_path / "upload.zip"
    summary = build_poliformat_zip(str(_download(tmp_path)), str(marks), str(out), feedback_pdfs=str(pdfs))

    assert [m[0] for m in summary["matched"]] == ["Núñez Pérez, Lucía", "Soler Vidal, Marta"]
    assert summary["no_mark"] == ["Forés Llop, Inés"]
    assert summary["unmatched_marks"] == ["Someone Else (XYZ)"]
    assert summary["missing_pdf"] == ["Soler Vidal, Marta"]

    extract = tmp_path / "extract"
    zipfile.ZipFile(out).extractall(extract)
    sheet = xlrd.open_workbook(str(extract / "Tarea 1" / "grades.xls")).sheet_by_index(0)
    assert sheet.name == "Tarea 1" and sheet.row_values(0) == HEADER
    assert [sheet.cell_value(r, 4) for r in (1, 2, 3)] == ["8,67", "5,10", ""]
    lucia = extract / "Tarea 1" / "Nunez Perez, Lucia(11223344)"
    assert (lucia / "comments.txt").read_text(encoding="utf-8") == \
        "Nota: 8,67 sobre 10. La corrección de cada pregunta está en el PDF adjunto."
    assert (lucia / "Adjuntos al comentario" / "Correccion Tarea 1.pdf").read_bytes() == b"%PDF-1.4 fake"
    marta = extract / "Tarea 1" / "Soler Vidal, Marta(55667788)"
    assert (marta / "comments.txt").read_text(encoding="utf-8") == "Nota: 5,10 sobre 10."
    assert (extract / "Tarea 1" / "Fores Llop, Ines(99001122)" / "comments.txt").read_text() == ""


def test_format_grade_uses_the_site_decimal_separator():
    assert format_grade(8.6047) == "8,60"
    assert format_grade(7, ".") == "7.00"


def _submission_folder(root, folder_name, files, text=""):
    folder = root / folder_name
    (folder / "Adjuntos de la entrega").mkdir(parents=True)
    (folder / "Adjuntos al comentario").mkdir()
    for name, content in files.items():
        (folder / "Adjuntos de la entrega" / name).write_text(content, encoding="utf-8")
    for name in ("comments.txt", "timestamp.txt", "feedbackText.html"):
        (folder / name).write_text("", encoding="utf-8")
    (folder / f"{folder_name}_submissionText.html").write_text(text, encoding="utf-8")
    return folder


def test_poliformat_download_as_students_dir_one_prompt_per_submission(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from autocorrect import lab
    from autocorrect.submissions import find_student_files, get_student_name_from_path

    root = tmp_path / "Proyecto_ Entrega 2"
    _submission_folder(root, "Nunez Perez, Lucia(11223344)", {"Entrega 2.pdf": "x", "base_datos.sql": "CREATE TABLE t (a INT);"},
                       text="<p>Trabajo de Pau Roig y Lucía Núñez</p>")
    _submission_folder(root, "Roig Mas, Clara(66778899)", {})  # no submission
    files = find_student_files(str(root), r".*\.(sql|html|txt)$", "")
    assert sorted(f.split("/")[-1] for f in files) == ["Nunez Perez, Lucia(11223344)_submissionText.html", "base_datos.sql"]
    assert get_student_name_from_path(files[0]) == "Nunez Perez, Lucia"

    prompts = []
    monkeypatch.setattr(lab, "build_grading_prompt", lambda name, content, *a: prompts.append((name, content)) or content)
    args = SimpleNamespace(no_evaluate=True, rubric="rubric.txt", example="example.txt", markdown_config=None,
                           no_reference=True, reference="", files_regex=r".*\.(sql|html)$", prefer_extensions="",
                           student=None, whole_submission=True, include_images=False, no_cleanup_html=False,
                           no_dedupe_images=False, max_images=20, keep_prompt=False)
    (tmp_path / "rubric.txt").write_text("10 points", encoding="utf-8")
    lab.grade_submissions(str(tmp_path), str(root), args)
    assert len(prompts) == 1 and prompts[0][0] == "Nunez Perez, Lucia"
    assert "File 1 of 2" in prompts[0][1] and "CREATE TABLE t" in prompts[0][1] and "Pau Roig" in prompts[0][1]


def test_group_mark_from_feedback_yamls_goes_to_every_member(tmp_path):
    from autocorrect.poliformat import read_feedback_dir

    feedback = tmp_path / "feedback"
    feedback.mkdir()
    (feedback / "feedback_Lucia_1a2b.yaml").write_text(
        "students:\n- full_name: Lucía Núñez Pérez\n- full_name: Marta Soler Vidal\n"
        "feedback: |\n  **Base de datos:** 3/4.\n  Falta una consulta.\n\n  Nota final: 8/10.\nmark: 8.0\n"
        "submission_file: /x/Tarea 1/Nunez Perez, Lucia(11223344)/Adjuntos de la entrega/a.pdf\n",
        encoding="utf-8")
    rows = read_feedback_dir(str(feedback))
    assert [(r["student_id"], r["name"], r["mark"]) for r in rows] == [
        ("11223344", "Lucia Nunez Perez", 8.0), ("", "Marta Soler Vidal", 8.0)]

    out = tmp_path / "upload.zip"
    summary = build_poliformat_zip(str(_download(tmp_path)), None, str(out), feedback_dir=str(feedback))
    assert [m[0] for m in summary["matched"]] == ["Núñez Pérez, Lucía", "Soler Vidal, Marta"]
    extract = tmp_path / "extract"
    zipfile.ZipFile(out).extractall(extract)
    comment = (extract / "Tarea 1" / "Soler Vidal, Marta(55667788)" / "comments.txt").read_text(encoding="utf-8")
    assert comment == ("<p>Nota: 8,00 sobre 10.</p>\n<p><strong>Base de datos:</strong> 3/4.<br>\nFalta una consulta.</p>\n"
                       "<p>Nota final: 8/10.</p>")


def test_pdf_pages_rendered_as_images(tmp_path):
    import pymupdf

    from autocorrect.parsing.pdf import render_pdf_pages

    document = pymupdf.open()
    for i in range(2):
        page = document.new_page()
        page.draw_rect(pymupdf.Rect(50, 50, 200, 120))  # a vector "diagram", not an embedded image
        page.insert_text((60, 90), f"Router {i}")
    document.save(tmp_path / "memoria.pdf")
    images = render_pdf_pages(str(tmp_path / "memoria.pdf"))
    assert [image.source.rsplit("#", 1)[1] for image in images] == ["page=1", "page=2"]
    assert all(image.mime_type == "image/png" and image.data.startswith(b"\x89PNG") for image in images)
