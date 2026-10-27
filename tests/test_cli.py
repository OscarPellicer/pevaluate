"""The argparse front end: subcommands, the default lab-grading command and old option spellings."""
import pytest

from autocorrect import combine_marks, exam_free, exam_open, lab, moodle, smoke
from autocorrect.cli import _with_default_command, build_parser, main


def parse(*argv):
    return build_parser().parse_args(_with_default_command(list(argv)))


def test_folder_without_subcommand_means_grade():
    assert _with_default_command(["session", "--no-unzip"]) == ["grade", "session", "--no-unzip"]
    assert _with_default_command(["--no-unzip", "session"]) == ["grade", "--no-unzip", "session"]
    assert _with_default_command(["exam-open", "--index-csv", "x"])[0] == "exam-open"
    assert _with_default_command(["--help"]) == ["--help"]
    args = parse("session", "--no-unzip", "--keep-prompts")
    assert args.func is lab.run and args.session_folder == "session" and args.no_unzip and args.keep_prompt


@pytest.mark.parametrize("argv, module", [
    (["exam-open", "--index-csv", "i.csv", "--exam-dir", "e", "--output-dir", "o"], exam_open),
    (["exam-free", "--input-path", "s.pdf", "--exam-dir", "e", "--output-dir", "o"], exam_free),
    (["combine-marks", "--lab-feedback", "f", "--exam-scores", "s.csv", "--output", "o.csv"], combine_marks),
    (["combine", "--lab-feedback", "f", "--exam-scores", "s.csv", "--output", "o.csv"], combine_marks),
    (["moodle-csv", "w.csv"], moodle),
    (["feedback-csv", "w.csv"], moodle),
    (["test-open"], smoke),
    (["exam-open-test"], smoke),
])
def test_subcommands_and_aliases(argv, module):
    assert parse(*argv).func is module.run


def test_name_threshold_and_old_spellings():
    base = ["combine-marks", "--lab-feedback", "f", "--exam-scores", "s.csv", "--output", "o.csv"]
    assert parse(*base).threshold == 75.0
    assert parse(*base, "--name-threshold", "80").threshold == 80.0
    assert parse(*base, "--threshold", "60").threshold == 60.0
    assert parse("moodle-csv", "w.csv").fuzzy_threshold == 70.0
    assert parse("moodle-csv", "w.csv", "--name-threshold", "50").fuzzy_threshold == 50.0
    assert parse("moodle-csv", "w.csv", "--fuzzy-threshold", "40").fuzzy_threshold == 40.0
    assert parse("session").no_cleanup_html is False
    assert parse("session", "--not-cleanup-html").no_cleanup_html is True
    assert parse("session", "--no-cleanup-html").no_cleanup_html is True
    assert parse("exam-open", "--index-csv", "i", "--exam-dir", "e", "--output-dir", "o", "--keep-prompt").keep_prompts


def test_old_spellings_are_hidden_from_help(capsys):
    with pytest.raises(SystemExit):
        main(["moodle-csv", "--help"])
    out = capsys.readouterr().out
    assert "--name-threshold" in out and "--fuzzy-threshold" not in out
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for name in ("exam-open", "exam-free", "combine-marks", "moodle-csv", "test-open"):
        assert name in out


def test_no_arguments_prints_help(capsys):
    assert main([]) == 2
    assert "usage: pevaluate" in capsys.readouterr().out


def test_grading_prompt_and_rubric_fallback(tmp_path, capsys):
    prompt = lab.build_grading_prompt("Ana", "My notebook", "Rubric text", "Example", "Reference text")
    assert "Submitted in Moodle by: Ana" in prompt
    assert "Here is the reference solution:\n\nReference text\n" in prompt
    assert prompt.endswith("Please provide the feedback now:\n")

    (tmp_path / "Rubrica P1.txt").write_text("10 points", encoding="utf-8")
    path, text = lab._load_rubric(str(tmp_path), "rubric.txt")
    assert path.endswith("Rubrica P1.txt") and text == "10 points"
    assert "Found alternative rubric file" in capsys.readouterr().out
    assert lab._load_example(str(tmp_path), "example.txt") == (None, "[No example feedback provided]")
