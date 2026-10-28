"""pevaluate review: the model read from the result files, the edits written back to them (only the
fields a teacher may edit), and the local server (token, files behind tokens, JSON API).
All names and IDs are fictitious."""
import csv
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
import yaml

from autocorrect.review import edits
from autocorrect.review.data import detect_config, file_version, load_review
from autocorrect.review.server import ReviewServer, open_answers_pending

MC_OPTIONS = ["Jurídica", "Didáctica", "Semántica", "Técnica"]  # "Didáctica" is the right one


def _question_files(exam_dir):
    exam_dir.mkdir()
    # Model 2 prints the options in another order: its "A" is model 1's "B".
    for model, order in (("1", [0, 1, 2, 3]), ("2", [1, 0, 3, 2])):
        questions = [
            {"id": 1, "original_id": "q_eif", "question_type": "multiple_choice", "points": 0.5,
             "text": "Señala cuál **no** es una capa:", "explanation": "Son cuatro capas.",
             "options": [{"text": MC_OPTIONS[i], "is_correct": i == 1} for i in order]},
            {"id": 2, "original_id": "q_uso", "question_type": "open_answer", "points": 1.0,
             "text": "Explica el uso secundario de los datos ($n$ ejemplos).", "options": [],
             "expected_answer": "Reutilización para **investigación**.", "rubric": "- 1 pt: definición."},
        ]
        (exam_dir / f"exam_model_{model}_questions.json").write_text(json.dumps({"questions": questions}), encoding="utf-8")


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def exam(tmp_path):
    _question_files(tmp_path / "exam")
    mc = tmp_path / "correccion"
    (mc / "open_responses").mkdir(parents=True)
    (mc / "scanned_pages").mkdir()
    _write_csv(mc / "correction_results.csv", [
        {"page": "1", "student_id": "11223344", "student_name": "Lucía Núñez Pérez", "ocr_student_id": "11223344",
         "ocr_student_name": "Lucía Núñez", "model_id": "1", "answer_1": "B"},
        {"page": "3", "student_id": "MSOLVID", "student_name": "Marta Soler Vid?", "ocr_student_id": "MSOLVID",
         "ocr_student_name": "Marta Soler Vid?", "model_id": "2", "answer_1": "B"}])
    _write_csv(mc / "final_marks.csv", [
        {"student_id": "11223344", "student_name": "Lucía Núñez Pérez", "score": "0.5", "max_score": "0.5", "mark": "10"},
        {"student_id": "MSOLVID", "student_name": "Marta Soler Vid?", "score": "-0.17", "max_score": "0.5", "mark": "0"}])
    for sid in ("11223344", "MSOLVID"):
        (mc / "open_responses" / f"{sid}_q_2.png").write_bytes(b"\x89PNG fake")
    _write_csv(mc / "open_responses_index.csv", [
        {"student_id": sid, "student_name": name, "model_id": m, "question_id": "2", "original_id": "q_uso",
         "answer_sheet_page": page, "crop_path": f"open_responses/{sid}_q_2.png", "layout_check": "ok"}
        for sid, name, m, page in (("11223344", "Lucía Núñez Pérez", "1", "1"), ("MSOLVID", "Marta Soler Vid?", "2", "3"))])
    opened = tmp_path / "correccion_abiertas"
    opened.mkdir()
    responses = []
    for sid, name, m, score, conf in (("11223344", "Lucía Núñez Pérez", "1", 1.0, 0.95), ("MSOLVID", "Marta Soler Vid?", "2", 0.25, 0.5)):
        responses.append({
            "student_id": sid, "student_name": name, "model_id": m, "question_id": "2", "original_id": "q_uso",
            "crop_path": str(mc / "open_responses" / f"{sid}_q_2.png"), "score": score, "max_score": 1.0,
            "feedback": "" if score == 1.0 else "Falta un ejemplo.", "response_markdown": "Uso **secundario**...",
            "conversion_warnings": [], "confidence": conf, "status": "cached", "graded_from": "box",
            "grader": {"model": "claude", "score": score, "feedback": "" if score == 1.0 else "Falta un ejemplo."}})
    (opened / "open_evaluations.yaml").write_text(yaml.safe_dump({"responses": responses}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    roster = tmp_path / "grades.csv"
    roster.write_text("Identificador,ID,Apellido,Nombre,Calificación\n11223344,11223344,Núñez Pérez,Lucía,\n"
                      "55667788,55667788,Soler Vidal,Marta,\n99001122,99001122,Forés Llop,Inés,\n", encoding="utf-8")
    cfg = detect_config([str(opened)], exam_dir=str(tmp_path / "exam"), roster=str(roster))
    cfg.mc_dir, cfg.index_csv = str(mc), str(mc / "open_responses_index.csv")
    return cfg


def test_exam_model_letters_per_model_roster_and_flags(exam):
    model = load_review(exam)
    q = {q["key"]: q for q in model["questions"]}
    assert [q["key"] for q in model["questions"]] == ["q_eif", "q_uso"]
    assert q["q_eif"]["type"] == "mc" and [o["correct"] for o in q["q_eif"]["options"]] == [False, True, False, False]
    assert "<strong>no</strong>" in q["q_eif"]["text_html"] and "investigación" in q["q_uso"]["expected_html"]
    mc = {a["student"]: a for a in model["answers"] if a["type"] == "mc"}
    # Both wrote "B": right in model 1, but model 2's "B" is "Jurídica".
    assert mc["11223344"]["correct"] is True and mc["MSOLVID"]["correct"] is False
    assert mc["MSOLVID"]["correct_letter"] == "A" and mc["11223344"]["correct_letter"] == "B"
    assert q["q_eif"]["stats"]["counts"] == [1, 1, 0, 0]
    opens = {a["student"]: a for a in model["answers"] if a["type"] == "open"}
    assert opens["MSOLVID"]["reasons"] and not opens["11223344"]["reasons"]  # low confidence
    assert opens["11223344"]["images"][0]["url"].startswith("/f/")
    students = {s["key"]: s for s in model["students"]}
    assert students["11223344"]["match"] == "id" and students["MSOLVID"]["match"] == "name"
    assert model["roster"]["students"][2]["name"] == "Inés Forés Llop" and 2 not in model["roster"]["matched"]


def test_open_edit_keeps_grader_and_refuses_stale_versions(exam):
    path = f"{exam.open_dir}/open_evaluations.yaml"
    version = file_version(path)
    edits.save_open(exam, "MSOLVID", "2", 0.5, "Falta un **ejemplo** concreto.", version)
    item = [r for r in yaml.safe_load(open(path, encoding="utf-8"))["responses"] if r["student_id"] == "MSOLVID"][0]
    assert item["score"] == 0.5 and item["feedback"] == "Falta un **ejemplo** concreto."
    assert item["grader"] == {"model": "claude", "score": 0.25, "feedback": "Falta un ejemplo."}
    with pytest.raises(edits.Conflict):
        edits.save_open(exam, "MSOLVID", "2", 0.75, "x", version)
    with pytest.raises(edits.Invalid):
        edits.save_open(exam, "MSOLVID", "2", 1.5, "x", file_version(path))
    answer = [a for a in load_review(exam)["answers"] if a["type"] == "open" and a["student"] == "MSOLVID"][0]
    assert answer["edited"] and answer["llm_score"] == 0.25 and answer["reasons"] == []
    assert open(f"{path}.before_review", encoding="utf-8").read().count("Falta un ejemplo.") == 2  # the copy kept


def test_mc_answer_and_student_change_carry_to_open_grades(exam):
    results = f"{exam.mc_dir}/correction_results.csv"
    edits.save_mc(exam, "3", "1", "a", 4, file_version(results))
    assert list(csv.DictReader(open(results, encoding="utf-8")))[1]["answer_1"] == "A"
    edits.set_reviewed(exam, ["MSOLVID|q_uso"], True)
    versions = {"mc": file_version(results), "open": file_version(f"{exam.open_dir}/open_evaluations.yaml")}
    edits.save_student(exam, "3", "55667788", "Marta Soler Vidal", versions)
    row = list(csv.DictReader(open(results, encoding="utf-8")))[1]
    assert (row["student_id"], row["student_name"], row["ocr_student_name"]) == ("55667788", "Marta Soler Vidal", "Marta Soler Vid?")
    opens = yaml.safe_load(open(f"{exam.open_dir}/open_evaluations.yaml", encoding="utf-8"))["responses"]
    assert {r["student_id"] for r in opens} == {"11223344", "55667788"}
    index = list(csv.DictReader(open(exam.index_csv, encoding="utf-8")))
    assert index[1]["student_id"] == "55667788" and open_answers_pending(exam) == []  # nothing to grade again
    assert "55667788|q_uso" in json.load(open(f"{exam.open_dir}/review_state.json"))["reviewed"]
    with pytest.raises(edits.Invalid):  # two exams cannot share an ID
        edits.save_student(exam, "3", "11223344", "X", {"mc": file_version(results)})


@pytest.fixture
def lab(tmp_path):
    root = tmp_path / "Memoria"
    folder = root / "Nunez Perez, Lucia(11223344)" / "Adjuntos de la entrega"
    folder.mkdir(parents=True)
    (folder / "memoria.pdf").write_bytes(b"%PDF-1.4 fake")
    (folder / "base_datos.sql").write_text("CREATE TABLE t (a INT);", encoding="utf-8")
    (root / "grades.csv").write_text("Identificador,ID,Apellido,Nombre,Calificación\n11223344,11223344,Núñez Pérez,Lucía,\n"
                                     "55667788,55667788,Soler Vidal,Marta,\n66778899,66778899,Roig Mas,Clara,\n", encoding="utf-8")
    feedback = tmp_path / "session" / "feedback"
    feedback.mkdir(parents=True)
    record = {"students": [{"full_name": "Lucía Núñez Pérez"}], "feedback": "1. Diagrama: 1/1.\n2. Consultas: 0.5/1. Falta una.",
              "mark": 7.5, "submission_file": str(folder / "memoria.pdf"),
              "submission_files": [str(folder / "memoria.pdf"), str(folder / "base_datos.sql")],
              "grader": {"model": "claude", "mark": 7.5, "feedback": "1. Diagrama: 1/1.\n2. Consultas: 0.5/1. Falta una."}}
    (feedback / "feedback_Lucia_1a2b3c4d.yaml").write_text(yaml.safe_dump(record, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return detect_config([str(feedback)], roster=str(root))


def test_lab_groups_files_and_members(lab):
    model = load_review(lab)
    sub = model["submissions"][0]
    assert [f["kind"] for f in sub["files"]] == ["pdf", "text"]
    assert sub["submitter"] == {"id": "11223344", "name": "Lucia Nunez Perez"}
    assert sub["feedback_html"].count("<br>") == 1  # line breaks kept, as the LMS shows the comment
    edits.save_lab(lab, sub["key"], 8, "Bien.", ["Lucía Núñez Pérez", "Marta Soler Vidal"], sub["version"])
    sub = load_review(lab)["submissions"][0]
    assert [m["name"] for m in sub["members"]] == ["Lucía Núñez Pérez", "Marta Soler Vidal"]
    assert [m.get("roster") for m in sub["members"]] == [0, 1] and sub["edited"] and sub["llm_mark"] == 7.5
    stored = yaml.safe_load(open(sub["file"], encoding="utf-8"))
    assert stored["grader"]["mark"] == 7.5 and stored["mark"] == 8.0
    with pytest.raises(edits.Invalid):
        edits.save_lab(lab, "../evil", 5, "", None, None)


def test_server_requires_token_and_serves_model_files_and_edits(exam):
    srv = ReviewServer(exam)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.handler())
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(f"{base}/api/model")
        assert denied.value.code == 403
        headers = {"X-Review-Token": srv.token, "Content-Type": "application/json"}
        get = lambda path: urllib.request.urlopen(urllib.request.Request(f"{base}{path}", headers=headers))
        post = lambda path, body: urllib.request.urlopen(urllib.request.Request(
            f"{base}{path}", data=json.dumps(body).encode(), headers=headers, method="POST"))
        model = json.load(get("/api/model"))
        image = [a for a in model["answers"] if a["type"] == "open"][0]["images"][0]["url"]
        assert get(image).read() == b"\x89PNG fake"
        post("/api/edit/open", {"student_id": "11223344", "question_id": "2", "score": 0.75, "feedback": "Casi.",
                                "version": model["versions"]["open"]})
        with pytest.raises(urllib.error.HTTPError) as conflict:
            post("/api/edit/open", {"student_id": "11223344", "question_id": "2", "score": 0.5, "feedback": "x",
                                    "version": model["versions"]["open"]})
        assert conflict.value.code == 409
        assert "<br>" in json.load(post("/api/markdown", {"text": "a\nb", "mode": "comment"}))["html"]
    finally:
        httpd.shutdown()


def test_one_server_several_parts(exam, lab):
    srv = ReviewServer(parts=[("exam", "Examen", exam), ("lab", "Prácticas", lab)], initial="lab")
    assert srv.model()["kind"] == "lab" and srv.model()["parts"] == [{"id": "exam", "label": "Examen"}, {"id": "lab", "label": "Prácticas"}]
    exam_model = srv.model("exam")
    assert exam_model["kind"] == "exam" and exam_model["part"] == "exam"
    srv.edit("reviewed", {"keys": ["11223344|q_uso"], "reviewed": True}, "exam")
    assert "11223344|q_uso" in srv.model("exam")["reviewed"] and not srv.model("lab")["reviewed"]
    with pytest.raises(edits.Invalid):
        srv.model("free")


def test_blank_paper_exam_pages_from_older_results(tmp_path):
    free = tmp_path / "abierto"
    (free / "pages").mkdir(parents=True)
    for i in range(1, 5):
        (free / "pages" / f"page_{i:03d}.png").write_bytes(b"\x89PNG")
    (free / "run_manifest.json").write_text(json.dumps({"tool": "pevaluate exam-free", "pages_per_exam": 2}), encoding="utf-8")
    responses = [{"student_id": f"exam_00{k}", "student_name": name, "model_id": "", "question_id": "1", "original_id": "q1",
                  "question_text": "¿Qué es un falso negativo?", "crop_path": str(free / "pages" / f"page_{2 * k - 1:03d}.png"),
                  "score": 1, "max_score": 1, "feedback": "", "status": "graded", "grader": {"score": 1, "feedback": ""}}
                 for k, name in ((1, "Pau Roig"), (2, "Clara Roig Mas"))]
    (free / "open_evaluations.yaml").write_text(yaml.safe_dump({"responses": responses}, allow_unicode=True), encoding="utf-8")
    model = load_review(detect_config([str(free)]))
    pages = {a["student"]: [i["label"] for i in a["images"]] for a in model["answers"]}
    assert pages == {"exam_001": ["page 1", "page 2"], "exam_002": ["page 1", "page 2"]}
    second = [a for a in model["answers"] if a["student"] == "exam_002"][0]["images"][1]["url"]
    assert second != [a for a in model["answers"] if a["student"] == "exam_001"][0]["images"][1]["url"]


def test_exam_free_keeps_the_pages_in_the_yaml(tmp_path):
    from autocorrect.open_results import write_evaluations_yaml

    write_evaluations_yaml(str(tmp_path), [{"student_id": "exam_001", "question_id": "1", "pages": ["/x/page_001.png", "/x/page_002.png"]},
                                           {"student_id": "S1", "question_id": "2", "crop_path": "c.png"}])
    stored = yaml.safe_load(open(tmp_path / "open_evaluations.yaml"))["responses"]
    assert stored[0]["pages"] == ["/x/page_001.png", "/x/page_002.png"] and "pages" not in stored[1]


def test_roster_command_writes_one_class_list_csv(tmp_path):
    from types import SimpleNamespace

    from autocorrect import roster

    export = tmp_path / "grades.csv"
    export.write_text("Identificador,ID,Apellido,Nombre,Calificación\n11223344,11223344,Núñez Pérez,Lucía,\n", encoding="utf-8")
    roster.run(SimpleNamespace(export=str(export), output=str(tmp_path / "lista_clase.csv"), id_column=None, name_column=None))
    assert list(csv.DictReader(open(tmp_path / "lista_clase.csv", encoding="utf-8"))) == [
        {"id": "11223344", "name": "Lucía Núñez Pérez", "email": ""}]


def test_edits_call_the_hook_and_the_server_stops_when_the_page_closes(exam):
    import time

    calls = []
    exam.on_edit = lambda: calls.append(1)
    srv = ReviewServer(exam)
    srv.edit("reviewed", {"keys": ["11223344|q_uso"], "reviewed": True})
    srv.edit("open", {"student_id": "11223344", "question_id": "2", "score": 1, "feedback": "Bien.",
                      "version": file_version(f"{exam.open_dir}/open_evaluations.yaml")})
    assert calls == [1]  # ticks are not edits of a grade
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.handler())
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    srv.last_seen, srv.closing_since = time.time(), time.time() - 20  # a page said goodbye 20 s ago
    srv.watch(httpd, grace=1)
    thread.join(timeout=6)
    assert not thread.is_alive()
