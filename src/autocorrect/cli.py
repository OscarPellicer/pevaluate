"""pevaluate: grade lab submissions and handwritten exams with an LLM.

    pevaluate <session folder | submission file> [options]   grade lab submissions (= pevaluate grade ...)
    pevaluate exam-open ...       grade the open answers of pexams exams (crops of the answer boxes)
    pevaluate exam-free ...       grade exams written on blank paper
    pevaluate combine-marks ...   lab + exam marks per student, and fill a gradebook export
    pevaluate moodle-csv ...      fill a Moodle assignment grading worksheet
    pevaluate poliformat-zip ...  build the 'Subir todo' zip of a PoliformaT (UPV) assignment
    pevaluate test-open ...       offline smoke test of the open-answer pipeline

The API key goes in a .env file (e.g. ANTHROPIC_API_KEY, or the variable named by --api-key-env).
"""
import argparse
import sys
from typing import Optional

from . import combine_marks, exam_free, exam_open, lab, moodle, poliformat, smoke

# name: (module with build_parser/run, aliases, help)
SUBCOMMANDS = {
    "grade": (lab, [], "Grade lab submissions with an LLM (the default: `pevaluate <folder> ...`)."),
    "exam-open": (exam_open, [], "Grade the open answers of pexams exams (answer-box crops)."),
    "exam-free": (exam_free, [], "Grade handwritten exams written on blank paper."),
    "combine-marks": (combine_marks, ["combine"], "Combine lab and exam marks per student; fill a gradebook export."),
    "moodle-csv": (moodle, ["feedback-csv"], "Fill a Moodle assignment grading worksheet with marks and feedback."),
    "poliformat-zip": (poliformat, ["sakai-zip"], "Build the 'Subir todo' zip of a PoliformaT (UPV, Sakai) assignment: grades, comments, feedback PDFs."),
    "test-open": (smoke, ["exam-open-test"], "Offline smoke test of the open-answer pipeline."),
}
DEFAULT_COMMAND = "grade"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pevaluate", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    for name, (module, aliases, help_text) in SUBCOMMANDS.items():
        description = module.__doc__ if module is combine_marks else module.DESCRIPTION
        subparser = subparsers.add_parser(name, aliases=aliases, help=help_text, description=description,
                                          formatter_class=argparse.RawDescriptionHelpFormatter)
        module.build_parser(subparser)
        subparser.set_defaults(func=module.run)
    return parser


def _with_default_command(argv: list[str]) -> list[str]:
    """``pevaluate <folder> ...`` (or ``pevaluate --option ... <folder>``) means ``pevaluate grade ...``."""
    known = set(SUBCOMMANDS) | {alias for _, aliases, _ in SUBCOMMANDS.values() for alias in aliases}
    if argv and argv[0] not in known and argv[0] not in ("-h", "--help"):
        return [DEFAULT_COMMAND, *argv]
    return argv


def main(argv: Optional[list[str]] = None):
    argv = _with_default_command(sys.argv[1:] if argv is None else list(argv))
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
