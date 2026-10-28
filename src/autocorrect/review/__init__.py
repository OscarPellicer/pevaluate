"""``pevaluate review``: a local web app where the teacher reviews and edits the corrections.

It reads the files the other commands write (pexams ``correction_results.csv``, exam-open and
exam-free ``open_evaluations.yaml``, lab grading ``feedback/*.yaml``) and edits only what the
teacher may edit by hand: the top-level score/feedback (or mark/feedback/students) and the
answers or student read from a scan. The model's own grade stays in each ``grader`` block, and
the "reviewed" ticks go to ``review_state.json`` next to the results, so nothing changes for the
tools. Rebuilding the reports and PDFs reruns the same steps (cached grades, no LLM calls).
"""
from .data import ReviewConfig, load_review  # noqa: F401
