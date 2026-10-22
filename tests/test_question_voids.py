from autocorrect.exam_open import _student_totals, resolve_question_voids


def _row(student, qid, score, max_score, original_id=""):
    return {"student_id": student, "question_id": str(qid), "original_id": original_id,
            "score": str(score), "max_score": str(max_score)}


def _status(rows):
    return {(r["student_id"], r["question_id"]): r["_void_status"] for r in rows}


MC = {"s1": {"score": "3", "max_score": "5"}}  # 60 % in the multiple-choice part


def test_nicely_voided_question_counts_only_if_it_raises_the_mark():
    rows = [_row("s1", 26, 0.6, 0.75), _row("s1", 27, 0.3, 0.75)]  # 80 % on 26
    resolve_question_voids(rows, MC, void_questions_nicely="26")
    assert _status(rows)[("s1", "26")] == "nicely_counted"

    rows = [_row("s1", 26, 0.15, 0.75), _row("s1", 27, 0.3, 0.75)]  # 20 % on 26
    resolve_question_voids(rows, MC, void_questions_nicely="26")
    assert _status(rows)[("s1", "26")] == "nicely_excluded"
    assert _status(rows)[("s1", "27")] == ""


def test_tie_is_excluded_and_original_id_is_accepted():
    rows = [_row("s1", 26, 0.45, 0.75, "q14_modelo_dual")]  # 60 %, same as the rest
    resolve_question_voids(rows, MC, void_questions_nicely="q14_modelo_dual")
    assert rows[0]["_void_status"] == "nicely_excluded"


def test_void_removes_the_question_for_everyone():
    rows = [_row("s1", 26, 0.75, 0.75), _row("s2", 26, 0.0, 0.75)]
    resolve_question_voids(rows, {}, void_questions="26")
    assert {r["_void_status"] for r in rows} == {"void"}


def test_several_nicely_voided_questions_maximise_the_mark():
    # rest 50 %; q30 at 100 % raises it to 67 %, q31 at 80 % still raises it (70 %), q32 at 10 % does not
    mc = {"s1": {"score": "1", "max_score": "2"}}
    rows = [_row("s1", 31, 0.8, 1), _row("s1", 30, 1, 1), _row("s1", 32, 0.1, 1)]
    resolve_question_voids(rows, mc, void_questions_nicely="30,31,32")
    assert _status(rows) == {("s1", "30"): "nicely_counted", ("s1", "31"): "nicely_counted",
                             ("s1", "32"): "nicely_excluded"}


def test_excluded_rows_leave_the_totals():
    rows = [_row("s1", 26, 0.0, 0.75), _row("s1", 27, 0.5, 0.75)]
    for r in rows:
        r["_score"], r["_max_score"] = float(r["score"]), float(r["max_score"])
    resolve_question_voids(rows, MC, void_questions_nicely="26")
    (total,) = _student_totals(rows)
    assert (total["score"], total["max_score"], total["voided_questions"]) == (0.5, 0.75, "26")
