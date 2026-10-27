import csv
import json
import zipfile
from pathlib import Path

import nbformat
import pytest
import yaml
from PIL import Image

from autocorrect import exam_free
from autocorrect.submissions import select_preferred_student_files, get_student_name_from_path
from autocorrect.combine_marks import main as combine_main
from autocorrect.exam_open import image_for_model
from autocorrect.flatunzip import load_submissions_index, unpack_and_flatten
from autocorrect.utils import _read_ipynb, compact_notebook


def _notebook(tmp_path):
    nb = nbformat.v4.new_notebook()
    cell = nbformat.v4.new_code_cell("model.fit(X, y)")
    cell.outputs = [
        nbformat.v4.new_output("stream", name="stderr", text="FutureWarning: penalty is deprecated\n" * 5000),
        nbformat.v4.new_output("execute_result", data={"text/plain": "   a  b\n0  1  2", "text/html": "<table>" + "<tr><td>1</td></tr>" * 500 + "</table>"}),
    ]
    nb.cells = [nbformat.v4.new_markdown_cell("# Lab"), cell]
    path = tmp_path / "nb.ipynb"
    nbformat.write(nb, path)
    return path


def test_compact_notebook_keeps_plain_text_and_collapses_repeats(tmp_path):
    path = _notebook(tmp_path)
    text = _read_ipynb(str(path))
    assert "repeated 4999 more times" in text
    assert "0 1 2" in text and "<table>" not in text
    assert len(text) < 2000
    # Disabled with max_output_chars=None
    assert len(_read_ipynb(str(path), max_output_chars=None)) > 100000


def test_compact_notebook_truncates_long_output():
    nb = nbformat.v4.new_notebook()
    cell = nbformat.v4.new_code_cell("print(x)")
    cell.outputs = [nbformat.v4.new_output("stream", name="stdout", text="".join(f"line {i}\n" for i in range(5000)))]
    nb.cells = [cell]
    out = compact_notebook(nb, max_output_chars=1000).cells[0].outputs[0]["text"]
    assert "characters omitted" in out and "line 0" in out and "line 4999" in out and len(out) < 1200


class _MoodleZipInfo(zipfile.ZipInfo):
    """Writes UTF-8 names without the zip UTF-8 flag, as Moodle does."""
    __slots__ = ()

    def _encodeFilenameFlags(self):
        return self.filename.encode("utf-8"), self.flag_bits & ~0x800


def test_flatunzip_recovers_moodle_names_and_groups_exports(tmp_path):
    # Moodle stores UTF-8 names without the zip UTF-8 flag; zipfile reads them as CP437.
    folder = "Martínez Núñez, Iñaki_12345_assignsubmission_file"
    zip_path = tmp_path / "moodle.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name in ("lab.ipynb", "lab.html"):
            zf.writestr(_MoodleZipInfo(f"{folder}/{name}"), b"{}")
    out = tmp_path / "students"
    unpack_and_flatten(str(zip_path), str(out))
    index = load_submissions_index(str(out))
    assert {entry["student"] for entry in index.values()} == {"Martínez Núñez, Iñaki"}
    files = sorted(str(out / name) for name in index)
    assert all("Martinez Nunez, Inaki" in Path(f).name for f in files)
    selected = select_preferred_student_files(files, str(out), [".ipynb", ".html"])
    assert len(selected) == 1 and selected[0].endswith(".ipynb")
    assert get_student_name_from_path(selected[0]) == "Martínez Núñez, Iñaki"


def test_image_for_model_downscales(tmp_path):
    path = tmp_path / "crop.png"
    Image.new("RGB", (1760, 1000), "white").save(path)
    data, mime = image_for_model(str(path), 900)
    from io import BytesIO
    assert mime == "image/png" and Image.open(BytesIO(data)).size == (900, 511)
    data, _ = image_for_model(str(path), None)
    assert Image.open(BytesIO(data)).size == (1760, 1000)


class _FakeClient:
    def __init__(self):
        self.calls = []

    def complete(self, prompt, images=(), **kwargs):
        self.calls.append((prompt, len(images)))
        answer = {
            "student_name": "Ana Pérez", "student_id": "12345678A",
            "answers": [{"question_id": "1", "student_label": "3", "score": 0.5, "max_score": 1,
                         "feedback": "Falta el AUC.", "response_markdown": "Por el desbalance.", "confidence": 0.9}],
        }
        meta = {"provider": "anthropic", "model_requested": "claude-haiku-5-5", "model_served": "claude-haiku-5-5",
                "effort": "medium", "fallback_used": False, "request_id": "req_1", "timestamp_utc": "2026-10-22T00:00:00+00:00",
                "tool_version": "test"}
        return json.dumps(answer), meta


def test_exam_free_matches_answers_by_content(tmp_path):
    exam_dir = tmp_path / "exam"; exam_dir.mkdir()
    questions = [{"id": "1", "original_id": "q_auc", "text": "¿Por qué 88 %?", "points": "1", "expected_answer": "Desbalance.", "rubric": "- 100 %: desbalance"},
                 {"id": "2", "original_id": "q_sign", "text": "¿Qué indica el signo?", "points": "1", "expected_answer": "Riesgo.", "rubric": "- 100 %: riesgo"}]
    (exam_dir / "exam_model_1_questions.json").write_text(json.dumps({"questions": questions}), encoding="utf-8")
    pages = tmp_path / "pages"; pages.mkdir()
    for i in range(2):
        Image.new("RGB", (1240, 1754), "white").save(pages / f"p{i}.png")
    client = _FakeClient()
    out = tmp_path / "out"
    scores = exam_free.evaluate_free_exams(str(pages), str(exam_dir), str(out), pages_per_exam=2, client=client)
    assert len(client.calls) == 1 and client.calls[0][1] == 2
    assert "match them by content" in client.calls[0][0]
    rows = list(csv.DictReader(open(scores, encoding="utf-8")))
    assert [(r["student_id"], r["question_id"], r["score"]) for r in rows] == [("12345678A", "1", "0.5"), ("12345678A", "2", "")]
    assert rows[1]["feedback"] == "No answer found for this question."
    assert rows[0]["grader_model"] == "claude-haiku-5-5"
    # A teacher edit in the YAML survives a rerun (raw response cached, no new call).
    data = yaml.safe_load(open(out / "open_evaluations.yaml", encoding="utf-8"))
    data["responses"][0]["score"] = 1
    yaml.safe_dump(data, open(out / "open_evaluations.yaml", "w", encoding="utf-8"), allow_unicode=True)
    scores = exam_free.evaluate_free_exams(str(pages), str(exam_dir), str(out), pages_per_exam=2, client=client)
    assert len(client.calls) == 1
    assert list(csv.DictReader(open(scores, encoding="utf-8")))[0]["score"] == "1"


def test_combine_marks_merges_names_and_pairs(tmp_path, capsys):
    feedback = tmp_path / "feedback"; feedback.mkdir()
    yaml.safe_dump({"students": [{"full_name": "Ana Pérez Gil"}, {"full_name": "Luis Soler"}], "feedback": "Bien.", "mark": 8.5,
                    "submission_file": "a.ipynb"}, open(feedback / "feedback_a.yaml", "w"), allow_unicode=True)
    yaml.safe_dump({"students": [{"full_name": "Luis Soler"}], "feedback": "Solo.", "mark": 5.0, "submission_file": "b.ipynb"},
                   open(feedback / "feedback_b.yaml", "w"), allow_unicode=True)
    scores = tmp_path / "open_scores.csv"
    with open(scores, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["student_id", "student_name", "question_id", "score", "max_score", "feedback"])
        w.writeheader()
        w.writerow({"student_id": "1", "student_name": "ANA PEREZ GIL", "question_id": "1", "score": "1", "max_score": "1", "feedback": "Correcto."})
        w.writerow({"student_id": "1", "student_name": "ANA PEREZ GIL", "question_id": "2", "score": "0.5", "max_score": "1", "feedback": "Falta X."})
    output = tmp_path / "marks.csv"
    combine_main(["--lab-feedback", str(feedback), "--exam-scores", str(scores), "--output", str(output)])
    rows = {r["name"]: r for r in csv.DictReader(open(output, encoding="utf-8-sig"), delimiter=";")}
    assert rows["Ana Pérez Gil"]["exam_mark"] == "7.5" and rows["Ana Pérez Gil"]["lab_mark"] == "8.5"
    assert rows["Luis Soler"]["lab_conflict"] and rows["Luis Soler"]["exam_mark"] == ""
    assert "Two lab submissions: Luis Soler" in capsys.readouterr().out


def test_llm_module_identical_to_pexams_copy():
    pexams_llm = pytest.importorskip("pexams.llm")
    import autocorrect.llm as ours
    assert Path(ours.__file__).read_bytes() == Path(pexams_llm.__file__).read_bytes()


def test_combine_marks_weights_feedback_and_roster(tmp_path):
    import pandas as pd
    feedback = tmp_path / "feedback"; feedback.mkdir()
    yaml.safe_dump({"students": [{"full_name": "Ana Pérez Gil"}], "feedback": "- Análisis 1 (1 / 1)", "mark": 6.0,
                    "submission_file": "solo.ipynb"}, open(feedback / "feedback_a.yaml", "w"), allow_unicode=True)
    yaml.safe_dump({"students": [{"full_name": "Ana Pérez Gil"}, {"full_name": "Luis Soler"}], "feedback": "Completo.", "mark": 9.0,
                    "submission_file": "pair.ipynb"}, open(feedback / "feedback_b.yaml", "w"), allow_unicode=True)
    scores = tmp_path / "open_scores.csv"
    with open(scores, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["student_id", "student_name", "question_id", "score", "max_score", "feedback"])
        w.writeheader()
        w.writerow({"student_id": "12345678A", "student_name": "Ana Perez", "question_id": "1", "score": "1", "max_score": "2", "feedback": "Falta X."})
    roster = tmp_path / "grades.xlsx"
    pd.DataFrame({"Número de identificación": ["12345678", "87654321", "11111111"],
                  "Nombre alumno": ["Pérez Gil, Ana", "Soler, Luis", "Nadie, Nemo"], "Nota numérica": [None] * 3}).to_excel(roster, index=False)
    out = tmp_path / "filled.xlsx"
    combine_main(["--lab-feedback", str(feedback), "--exam-scores", str(scores), "--output", str(tmp_path / "m.csv"),
                  "--notice", "Aviso.", "--roster", str(roster), "--roster-output", str(out)])
    filled = pd.read_excel(out).set_index("Nombre alumno")
    # Ana: higher of her two lab marks (9), exam 5/10 -> 0.3*9 + 0.7*5 = 6.2; Luis: lab only -> 2.7.
    assert filled.loc["Pérez Gil, Ana", "Nota numérica"] == 6.2
    assert filled.loc["Soler, Luis", "Nota numérica"] == 2.7
    assert pd.isna(filled.loc["Nadie, Nemo", "Nota numérica"])
    text = filled.loc["Pérez Gil, Ana", "Retroalimentación"]
    assert "Práctica (notebook) (30%): 9/10" in text and "Examen (70%): 5/10" in text and "= 6.20/10" in text and text.endswith("Aviso.")
    assert "no presentado" in filled.loc["Soler, Luis", "Retroalimentación"]


def test_name_similarity_is_symmetric():
    from autocorrect.combine_marks import similarity
    assert similarity("Arnau Julio", "Arnau Julio Candel") == similarity("Arnau Julio Candel", "Arnau Julio") >= 75
    assert similarity("Valentina Medina Gallazi", "Valentina Elisa Medna Gallazzi") >= 75


def test_names_module_identical_to_pexams_copy():
    pexams_names = pytest.importorskip("pexams.names")
    import autocorrect.names as ours
    assert Path(ours.__file__).read_bytes() == Path(pexams_names.__file__).read_bytes()


def test_pdf_render_identical_to_pexams_copy():
    pexams_pdf = pytest.importorskip("pexams.pdf_render")
    import autocorrect.pdf_render as ours
    assert Path(ours.__file__).read_bytes() == Path(pexams_pdf.__file__).read_bytes()


def test_moodle_columns_identical_to_pexams_copy():
    pexams_cols = pytest.importorskip("pexams.moodle_columns")
    import autocorrect.moodle_columns as ours
    assert Path(ours.__file__).read_bytes() == Path(pexams_cols.__file__).read_bytes()
