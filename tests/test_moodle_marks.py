"""`pevaluate moodle-csv --marks`: combine-marks output into each assignment's grading worksheet."""
import csv

from autocorrect.moodle import main as moodle_csv_main

HEADER = ["Identificador", "Nom complet", "Número ID", "Estat", "Qualificació", "Qualificació màxima",
          "Darrera modificació (tramesa)", "Darrera modificació (qualificació)", "Comentaris de retroacció."]


def _worksheet(path, submitted):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for i, name in enumerate(["Pérez Gil, Ana", "Soler, Luis", "Vidal, Marta", "Roig, Pau"]):
            status = "S'ha tramès per qualificar" if name in submitted else "No s'ha tramès - La tasca ha vençut"
            w.writerow([f"Participant{i}", name, f"X{i}", status, "", "10,00", "-", "-", ""])


def _marks(path):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "aliases", "final_mark", "lab_mark", "feedback", "lab_group"], delimiter=";")
        w.writeheader()
        w.writerow({"name": "Ana Pérez Gil", "aliases": "ANA PEREZ", "final_mark": "6.2", "lab_mark": "9", "feedback": "Línea 1\nLínea 2",
                    "lab_group": "Ana Pérez Gil / Luis Soler"})
        w.writerow({"name": "Luis Soler", "aliases": "", "final_mark": "7", "lab_mark": "9", "feedback": "Bien.", "lab_group": "Ana Pérez Gil / Luis Soler"})
        w.writerow({"name": "Marta Vidal", "aliases": "", "final_mark": "5", "lab_mark": "8", "feedback": "Otra.", "lab_group": ""})
        w.writerow({"name": "Pau Roig", "aliases": "", "final_mark": "4", "lab_mark": "", "feedback": "Solo examen.", "lab_group": ""})


def _filled(path):
    return {r["Nom complet"]: r for r in csv.DictReader(open(path, encoding="utf-8-sig"))}


def test_students_go_to_the_assignment_where_they_or_their_partner_submitted(tmp_path, capsys):
    marks = tmp_path / "marks.csv"; _marks(marks)
    l1, l2 = tmp_path / "l1.csv", tmp_path / "l2.csv"
    _worksheet(l1, {"Pérez Gil, Ana"})
    _worksheet(l2, {"Vidal, Marta"})
    moodle_csv_main([str(l1), "--marks", str(marks), "--output", str(tmp_path / "o1.csv"), "--partial", "--feedback-format", "html"])
    moodle_csv_main([str(l2), "--marks", str(marks), "--output", str(tmp_path / "o2.csv"), "--partial", "--include-no-lab"])
    out1, out2 = _filled(tmp_path / "o1.csv"), _filled(tmp_path / "o2.csv")
    # Ana submitted to L1; Luis is her partner; Marta submitted to L2; Pau has no lab and goes where asked.
    assert set(out1) == {"Pérez Gil, Ana", "Soler, Luis"}
    assert set(out2) == {"Vidal, Marta", "Roig, Pau"}
    assert out1["Pérez Gil, Ana"]["Qualificació"] == "6,20"
    assert out1["Pérez Gil, Ana"]["Comentaris de retroacció."] == "Línea 1<br>Línea 2"
    assert out1["Pérez Gil, Ana"]["Identificador"] == "Participant0"
    assert "Roig, Pau" in capsys.readouterr().out  # reported as left out of L1
