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
    carlos = extract / "Tarea 1" / "Nunez Perez, Lucia(11223344)"
    assert (carlos / "comments.txt").read_text(encoding="utf-8") == \
        "Nota: 8,67 sobre 10. La corrección de cada pregunta está en el PDF adjunto."
    assert (carlos / "Adjuntos al comentario" / "Correccion Tarea 1.pdf").read_bytes() == b"%PDF-1.4 fake"
    carla = extract / "Tarea 1" / "Soler Vidal, Marta(55667788)"
    assert (carla / "comments.txt").read_text(encoding="utf-8") == "Nota: 5,10 sobre 10."
    assert (extract / "Tarea 1" / "Fores Llop, Ines(99001122)" / "comments.txt").read_text() == ""


def test_format_grade_uses_the_site_decimal_separator():
    assert format_grade(8.6047) == "8,60"
    assert format_grade(7, ".") == "7.00"
