"""Open a local web app to review and edit the corrections: by question, by student, the
answers flagged for review, the overall results; multiple-choice answers and the student read
from a scan, open-answer grades, and lab submissions (with their files and group members).

    pevaluate review correccion_abiertas            # exam-open (+ the pexams folder it used)
    pevaluate review correccion                     # multiple choice only (pexams correction folder)
    pevaluate review entrega2/feedback --roster "Entrega 2_20260101.zip"   # lab submissions + class list

Edits go to the same fields an agent would edit (top-level score/feedback, mark/feedback/students,
answers in correction_results.csv); the model's grades stay in the grader blocks. With a course
record, `ptestgen course review ASSESSMENT` opens it with everything filled in and rebuild buttons
for the assessment's steps.
"""
import argparse
from typing import Optional

from .data import detect_config

DESCRIPTION = __doc__


def build_parser(parser: Optional[argparse.ArgumentParser] = None) -> argparse.ArgumentParser:
    parser = parser or argparse.ArgumentParser(prog="pevaluate review", description=DESCRIPTION,
                                               formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folders", nargs="+", help="Result folders: exam-open/exam-free output, pexams correction folder, "
                                                   "lab feedback/ folder (or its session folder).")
    parser.add_argument("--exam-dir", help="The exam folder with exam_model_*_questions.json (default: from the run manifest).")
    parser.add_argument("--roster", help="Class list: PoliformaT 'Descargar todo' zip/folder or grades.xls/csv, Moodle "
                                         "export, or any CSV/XLSX with ID and name columns. Every student is matched to it.")
    parser.add_argument("--rubric", help="Rubric of lab submissions (default: from the run manifest).")
    parser.add_argument("--title", help="Title shown in the app.")
    parser.add_argument("--penalty", type=float, help="Multiple-choice penalty, for the points shown (default: from the run manifest).")
    parser.add_argument("--lang", choices=["es", "en"], help="Language of the app (default: the exam's --lang, else es).")
    parser.add_argument("--port", type=int, default=0, help="Port on 127.0.0.1 (default: any free port).")
    parser.add_argument("--no-browser", action="store_true", help="Print the URL without opening the browser.")
    parser.add_argument("--keep-open", action="store_true", help="Keep the server running when the page is closed (default: it stops).")
    return parser


def run(args: argparse.Namespace):
    from .server import serve

    cfg = detect_config(args.folders, exam_dir=args.exam_dir, roster=args.roster, rubric=args.rubric,
                        title=args.title, penalty=args.penalty)
    if args.lang:
        cfg.lang = args.lang
    serve(cfg, port=args.port, open_browser=not args.no_browser, keep_open=args.keep_open)


def main(argv: Optional[list[str]] = None):
    run(build_parser().parse_args(argv))
