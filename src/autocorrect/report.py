from .pdf_render import head_assets, html_to_pdf
"""HTML/PDF reports of graded open answers: the global report (with score distributions and
percentile samples) and one feedback PDF per student."""
import html
import math
import os
import re
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Dict, Optional

from autocorrect.common import read_csv_rows, safe_name, to_float
from autocorrect.marks import (
    VOID_EXCLUDED,
    combined_totals,
    load_mc_feedback_context,
    resolve_question_voids,
    student_totals,
    write_overall_marks_csv,
)


def _render_inline_markdown(text: str) -> str:
    """Markdown of a short text (e.g. feedback) rendered like the question statements, math
    included, without the wrapping paragraph so it can follow a label on the same line."""
    rendered = _render_markdown(text).strip()
    if rendered.startswith("<p>") and rendered.endswith("</p>") and rendered.count("<p>") == 1:
        rendered = rendered[3:-4]
    return rendered


def _render_markdown(text: str) -> str:
    text = text or ""

    def basic_render(source: str) -> str:
        parts = []
        cursor = 0
        mermaid_pattern = re.compile(r"```mermaid\s*(.*?)```", flags=re.DOTALL)
        for match in mermaid_pattern.finditer(source):
            before = source[cursor:match.start()]
            if before.strip():
                for block in re.split(r"\n\s*\n", before.strip()):
                    lines = [html.escape(line) for line in block.splitlines()]
                    parts.append(f"<p>{'<br>'.join(lines)}</p>")
            parts.append(f'<div class="mermaid">{html.escape(match.group(1).strip())}</div>')
            cursor = match.end()
        tail = source[cursor:]
        if tail.strip():
            for block in re.split(r"\n\s*\n", tail.strip()):
                lines = [html.escape(line) for line in block.splitlines()]
                parts.append(f"<p>{'<br>'.join(lines)}</p>")
        return "\n".join(parts) if parts else "<pre></pre>"

    try:
        import markdown

        rendered = markdown.markdown(
            text,
            extensions=["fenced_code", "tables", "pymdownx.arithmatex"],
            extension_configs={"pymdownx.arithmatex": {"generic": True}},
        )
        return re.sub(
            r'<pre><code class="language-mermaid">(.*?)</code></pre>',
            lambda match: f'<div class="mermaid">{html.unescape(match.group(1)).strip()}</div>',
            rendered,
            flags=re.DOTALL,
        )
    except Exception:
        return basic_render(text)


STUDENT_TEXTS = {
    "en": {"summary": "Summary", "part": "Part", "score": "Score", "max": "Max", "total": "Total", "mark": "Mark",
           "mc": "Multiple choice", "mc_detail": "{correct} correct, {incorrect} incorrect, {blank} blank",
           "question": "Question {id}", "pending": "pending", "void": "voided",
           "void_excluded": "voided: not counted, it would lower the mark",
           "void_counted": "voided: counted because it raises the mark",
           "student_id": "Student ID", "mc_sheet": "Corrected multiple-choice answer sheet",
           "open": "Open questions", "feedback": "Feedback", "converted": "Transcribed answer"},
    "es": {"summary": "Resumen", "part": "Parte", "score": "Puntos", "max": "Máximo", "total": "Total", "mark": "Nota",
           "mc": "Test", "mc_detail": "{correct} correctas, {incorrect} incorrectas, {blank} en blanco",
           "question": "Pregunta {id}", "pending": "pendiente", "void": "anulada",
           "void_excluded": "anulada: no cuenta porque bajaría la nota",
           "void_counted": "anulada: cuenta porque sube la nota",
           "student_id": "Identificación", "mc_sheet": "Hoja de respuestas del test corregida",
           "open": "Preguntas abiertas", "feedback": "Comentario", "converted": "Respuesta transcrita"},
    "ca": {"summary": "Resum", "part": "Part", "score": "Punts", "max": "Màxim", "total": "Total", "mark": "Nota",
           "mc": "Test", "mc_detail": "{correct} correctes, {incorrect} incorrectes, {blank} en blanc",
           "question": "Pregunta {id}", "pending": "pendent", "void": "anul·lada",
           "void_excluded": "anul·lada: no compta perquè baixaria la nota",
           "void_counted": "anul·lada: compta perquè puja la nota",
           "student_id": "Identificació", "mc_sheet": "Full de respostes del test corregit",
           "open": "Preguntes obertes", "feedback": "Comentari", "converted": "Resposta transcrita"},
}


def _t(lang: str, key: str, **values) -> str:
    text = STUDENT_TEXTS.get(lang, STUDENT_TEXTS["en"]).get(key) or STUDENT_TEXTS["en"][key]
    return text.format(**values) if values else text


def _student_summary_table(mc_row: dict, student_rows: list[dict], lang: str = "en") -> str:
    """Summary of the student's marks (multiple choice + each open answer + total) for the
    first page of the per-student feedback PDF."""
    lines = []
    total, total_max = 0.0, 0.0
    mc_score, mc_max = to_float(mc_row.get("score")), to_float(mc_row.get("max_score"))
    if mc_score is not None and mc_max:
        detail = ""
        if mc_row.get("correct", "") != "":
            detail = " (" + _t(lang, "mc_detail", correct=mc_row.get("correct"), incorrect=mc_row.get("incorrect"),
                                blank=mc_row.get("na")) + ")"
        lines.append(f"<tr><td>{html.escape(_t(lang, 'mc') + detail)}</td><td>{mc_score:.2f}</td><td>{mc_max:.2f}</td></tr>")
        total, total_max = total + mc_score, total_max + mc_max
    for row in student_rows:
        score, max_score = to_float(row.get("score")), to_float(row.get("max_score"))
        if max_score is None:
            continue
        shown = f"{score:.2f}" if score is not None else _t(lang, "pending")
        label = _t(lang, "question", id=row.get("question_id", ""))
        status = row.get("_void_status", "")
        if status in VOID_EXCLUDED:
            note = _t(lang, "void" if status == "void" else "void_excluded")
            lines.append(f"<tr class='voided'><td>{html.escape(label)} ({html.escape(note)})</td><td>{shown}</td><td>—</td></tr>")
            continue
        if status == "nicely_counted":
            label += f" ({_t(lang, 'void_counted')})"
        lines.append(f"<tr><td>{html.escape(label)}</td><td>{shown}</td><td>{max_score:.2f}</td></tr>")
        total, total_max = total + (score or 0.0), total_max + max_score
    if not lines:
        return ""
    mark = f"{10 * total / total_max:.2f}/10" if total_max else ""
    lines.append(f"<tr class='total'><td>{_t(lang, 'total')}</td><td>{total:.2f}</td><td>{total_max:.2f}</td></tr>")
    return (
        f"<div class='section'><h2>{_t(lang, 'summary')}</h2>"
        f"<table class='summary-table'><tr><th>{_t(lang, 'part')}</th><th>{_t(lang, 'score')}</th><th>{_t(lang, 'max')}</th></tr>"
        + "".join(lines)
        + f"</table><p><strong>{_t(lang, 'mark')}: {mark}</strong></p></div>"
    )


def _plot_histogram(values: list[float], max_tick: int, title: str, xlabel: str, figsize: tuple,
                    plot_path: str) -> Optional[str]:
    """Bar chart of ``values`` rounded to integers 0..max_tick, with mean and median lines."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception:
        return None

    binned = [min(max_tick, max(0, math.floor(value + 0.5))) for value in values]
    counts = Counter(binned)
    all_scores = np.arange(0, max_tick + 1)
    frequencies = [counts.get(int(score), 0) for score in all_scores]

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=figsize)
    ax.bar(all_scores, frequencies, width=1.0, edgecolor="black", align="center", color="skyblue")
    ax.set_title(title, fontsize=14, loc="left")
    ax.set_xlabel(xlabel, fontsize=11)
    ax.set_ylabel("Number of Students", fontsize=11)
    ax.set_xticks(all_scores)
    ax.set_xlim(-0.5, max_tick + 0.5)
    ax.set_ylim(top=max(frequencies, default=0) * 1.1 if any(frequencies) else 1)
    ax.grid(axis="y", linestyle="--", alpha=0.7)
    mean_value = mean(values)
    median_value = sorted(values)[len(values) // 2]
    ax.axvline(mean_value, color="red", linestyle="dashed", linewidth=1.5, label=f"Mean: {mean_value:.2f}")
    ax.axvline(median_value, color="green", linestyle="dashed", linewidth=1.5, label=f"Median: {median_value:.2f}")
    ax.legend()
    plt.tight_layout()
    plt.savefig(plot_path, dpi=300)
    plt.close(fig)
    return plot_path


def _plot_question_distribution(question_rows: list[dict], output_dir: str, question_id: str) -> Optional[str]:
    if not question_rows:
        return None
    max_score = max(row["_max_score"] for row in question_rows) or 1.0
    return _plot_histogram(
        [row["_score"] for row in question_rows], max(1, math.ceil(max_score)),
        f"Question {question_id} Score Distribution", f"Score (0-{max_score:g})", (7, 3.6),
        os.path.join(output_dir, f"question_{safe_name(question_id)}_score_distribution.png"),
    )


def _plot_overall_mark_distribution(items: list[dict], output_dir: str) -> Optional[str]:
    if not items:
        return None
    return _plot_histogram(
        [_mark_10(item) for item in items], 10, "Distribution of Overall Marks", "Mark (0-10 Scale)", (7, 4),
        os.path.join(output_dir, "overall_mark_distribution.png"),
    )


def _mark_10(item: dict) -> float:
    max_score = float(item.get("max_score", 0) or 0)
    score = float(item.get("score", 0) or 0)
    return (score / max_score) * 10 if max_score else 0


def _write_pdf_from_html(html_path: str, pdf_path: str) -> bool:
    """Report PDF; False (no PDF) if Chromium is not available. Math is typeset when MathJax loads."""
    try:
        html_to_pdf(html_path, pdf_path, math_required=False, settle_ms=1500,
                    margin={"top": "12mm", "bottom": "12mm", "left": "12mm", "right": "12mm"})
        return os.path.exists(pdf_path)
    except Exception:
        return False


def _extract_html_fragment(path: str) -> tuple[str, str]:
    if not path or not os.path.exists(path):
        return "", ""
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    head_match = re.search(r"<head[^>]*>(.*?)</head>", text, flags=re.DOTALL | re.IGNORECASE)
    body_match = re.search(r"<body[^>]*>(.*)</body>", text, flags=re.DOTALL | re.IGNORECASE)
    head = head_match.group(1).strip() if head_match else ""
    body = body_match.group(1).strip() if body_match else text
    styles = "\n".join(re.findall(r"<style[^>]*>.*?</style>", head, flags=re.DOTALL | re.IGNORECASE))
    return styles, body


# Fonts, MathJax (for $math$ in questions, answers and feedback) and Mermaid (diagrams).
_HEAD_ASSETS = head_assets(mermaid=True)


def _html_head(css: str, title: Optional[str] = None, extra_head: Optional[str] = None) -> str:
    title_tag = f"<title>{html.escape(title)}</title>" if title is not None else ""
    extra = f"{extra_head}\n" if extra_head is not None else ""
    return (f"<!doctype html><html><head><meta charset='utf-8'>{title_tag}\n{_HEAD_ASSETS}\n"
            f"{extra}<style>{css}</style></head><body>")


def _img(path: str, css_class: str) -> str:
    if path and os.path.exists(path):
        return f'<img src="{Path(path).resolve().as_uri()}" class="{css_class}">'
    return "<em>Missing image</em>"


def _stat(label: str, value) -> str:
    return f"<div class='stat-item'><span class='stat-label'>{label}</span><span class='stat-value'>{value}</span></div>"


REPORT_CSS = """
    body {
        font-family: 'Open Sans', 'Segoe UI', Tahoma, sans-serif;
        margin: 0;
        padding: 20px 30px;
        color: #333;
        background-color: #fff;
        font-size: 13px;
    }
    h1 { text-align: left; color: #2c3e50; margin-bottom: 25px; font-size: 24px; }
    h2, h3, h4, h5 { color: #2c3e50; }
    .stats-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 15px;
        margin-bottom: 30px;
        background: #f8f9fa;
        padding: 15px;
        border-radius: 8px;
    }
    .stat-item { display: flex; flex-direction: column; }
    .stat-label {
        font-size: 11px;
        color: #6c757d;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .stat-value { font-size: 18px; font-weight: 600; color: #2c3e50; }
    .section-title {
        border-bottom: 2px solid #2c3e50;
        padding-bottom: 8px;
        margin-top: 30px;
        margin-bottom: 15px;
        color: #2c3e50;
        font-size: 18px;
        text-align: left;
    }
    table { border-collapse: collapse; width: 100%; margin: 12px 0; }
    th, td { border: 1px solid #ddd; padding: 6px; text-align: left; }
    th { background: #f2f5f8; }
    .distribution-section { text-align: center; margin-bottom: 35px; page-break-after: always; }
    .distribution-img { max-width: 80%; height: auto; border: 1px solid #ddd; padding: 5px; border-radius: 4px; }
    .report-section { page-break-after: always; }
    .overall-table td, .overall-table th { text-align: right; }
    .overall-table td:first-child, .overall-table th:first-child { text-align: left; }
    .embedded-mc-report { border-top: 2px solid #2c3e50; margin-top: 18px; padding-top: 8px; }
    .question-block {
        margin-bottom: 15px;
        background: #fff;
        border: 1px solid #e0e0e0;
        border-radius: 6px;
        padding: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        page-break-inside: avoid;
    }
    .question-text {
        background: #f8fafc;
        border-left: 3px solid #94a3b8;
        padding: 9px 11px;
        margin: 8px 0 12px;
    }
    .sample { border: 1px solid #d8dee6; border-radius: 6px; padding: 12px; margin: 12px 0; page-break-inside: avoid; }
    .response-img { max-width: 100%; border: 1px solid #ccc; }
    .rendered-md { background: #f7f7f7; padding: 10px; border-left: 3px solid #8aa0b6; }
    .rendered-md p { margin-top: 0; }
    pre { white-space: pre-wrap; }
    """

STUDENT_CSS = """
    body {
        font-family: 'Open Sans', 'Segoe UI', Tahoma, sans-serif;
        margin: 0;
        padding: 22px 30px;
        color: #1f2937;
        background: #fff;
        font-size: 13px;
    }
    h1 { color: #2c3e50; margin: 0 0 4px; font-size: 24px; }
    h2 { color: #2c3e50; font-size: 17px; margin: 0 0 10px; }
    h3 { color: #2c3e50; font-size: 14px; margin: 14px 0 8px; }
    .muted { color: #64748b; }
    .header {
        border-bottom: 3px solid #2c3e50;
        padding-bottom: 12px;
        margin-bottom: 18px;
    }
    .section {
        margin: 16px 0;
        page-break-inside: avoid;
    }
    .item {
        border: 1px solid #d8dee6;
        border-radius: 6px;
        padding: 12px;
        margin: 12px 0;
        page-break-inside: avoid;
        box-shadow: 0 1px 3px rgba(0,0,0,.04);
    }
    .question-text {
        background: #f8fafc;
        border-left: 3px solid #94a3b8;
        padding: 9px 11px;
        margin-bottom: 10px;
    }
    .score-pill {
        display: inline-block;
        background: #e8f2ff;
        color: #1e3a8a;
        border: 1px solid #bfdbfe;
        border-radius: 999px;
        padding: 3px 9px;
        font-weight: 700;
        margin-bottom: 8px;
    }
    .feedback {
        background: #fff7ed;
        border-left: 3px solid #f97316;
        padding: 9px 11px;
        margin: 10px 0;
    }
    .crop { max-width: 100%; border: 1px solid #cbd5e1; border-radius: 4px; }
    .mc-sheet { max-width: 100%; border: 1px solid #cbd5e1; border-radius: 4px; }
    .md { background: #f7f7f7; padding: 10px; border-left: 3px solid #8aa0b6; }
    .md p { margin-top: 0; }
    img { max-width: 100%; height: auto; }
    .summary-table { border-collapse: collapse; margin: 8px 0; }
    .summary-table td, .summary-table th { border-bottom: 1px solid #e2e8f0; padding: 4px 12px; text-align: right; }
    .summary-table td:first-child, .summary-table th:first-child { text-align: left; }
    .summary-table tr.total td { font-weight: 700; }
    .summary-table tr.voided td { color: #718096; font-style: italic; }
    """


def _graded_rows(rows: list[dict]) -> list[dict]:
    """Rows with a numeric score, with ``_score``, ``_max_score`` and ``_mark`` (/10) added."""
    graded_rows = []
    for row in rows:
        try:
            score = float(row.get("score", ""))
            max_score = float(row.get("max_score", "") or 1)
        except ValueError:
            continue
        row["_score"] = score
        row["_max_score"] = max_score
        row["_mark"] = (score / max_score) * 10 if max_score else 0
        graded_rows.append(row)
    return graded_rows


def _overall_section(combined: list[dict], overall_plot: Optional[str]) -> list[str]:
    if not combined:
        return ["<p>No graded open-answer rows found.</p>"]
    marks = [(item["score"] / item["max_score"]) * 10 if item["max_score"] else 0 for item in combined]
    parts = [
        "<div class='report-section'>",
        "<h2 class='section-title'>Overall Results</h2>",
        "<div class='stats-grid'>",
        _stat("Students", len(combined)),
        _stat("Mean Mark", f"{mean(marks):.2f}/10"),
        _stat("Median Mark", f"{sorted(marks)[len(marks) // 2]:.2f}/10"),
        "</div>",
    ]
    if overall_plot and os.path.exists(overall_plot):
        parts.append(f"<img src='{Path(overall_plot).resolve().as_uri()}' class='distribution-img' alt='Overall Mark Distribution'>")
    parts.append("<table class='overall-table'><tr><th>Student</th><th>Total Score</th><th>Max Score</th><th>Mark</th></tr>")
    for item in sorted(combined, key=lambda row: row.get("student_id", "")):
        mark = (item["score"] / item["max_score"]) * 10 if item["max_score"] else 0
        label = f"{item.get('student_id', '')} {item.get('student_name', '')}".strip()
        parts.append(f"<tr><td>{html.escape(label)}</td><td>{item['score']:.2f}</td><td>{item['max_score']:.2f}</td><td>{mark:.2f}</td></tr>")
    parts.append("</table>")
    parts.append("</div>")
    return parts


SAMPLE_PERCENTILES = (0, 25, 75, 100)


def _question_section(question_id: str, question_rows: list[dict], output_dir: str) -> list[str]:
    """Statistics, distribution plot, score table and percentile samples of one question."""
    question_rows = sorted(question_rows, key=lambda row: row["_mark"])
    parts = ["<div class='question-block'>"]
    question_text = next((row.get("question_text", "") for row in question_rows if row.get("question_text", "")), "")
    parts.append(f"<h2 class='section-title'>Question {html.escape(question_id)}</h2>")
    if question_text:
        parts.append(f"<div class='question-text'>{_render_markdown(question_text)}</div>")
    q_marks = [row["_mark"] for row in question_rows]
    if q_marks:
        parts += [
            "<div class='stats-grid'>",
            _stat("Students", len({row.get('student_id', '') for row in question_rows})),
            _stat("Responses", len(question_rows)),
            _stat("Mean", f"{mean(q_marks):.2f}/10"),
            _stat("Min / Max", f"{min(q_marks):.2f} / {max(q_marks):.2f}"),
            "</div>",
        ]
        question_plot = _plot_question_distribution(question_rows, output_dir, question_id)
        if question_plot and os.path.exists(question_plot):
            parts.append("<h3>Score Distribution</h3>")
            parts.append(f"<img src='{Path(question_plot).resolve().as_uri()}' class='distribution-img' alt='Question {html.escape(question_id)} Score Distribution'>")
    parts.append("<table><tr><th>Student</th><th>Score</th><th>Feedback</th><th>Warnings</th></tr>")
    for row in question_rows:
        parts.append(
            "<tr>"
            f"<td>{html.escape(row.get('student_id', ''))} {html.escape(row.get('student_name', ''))}</td>"
            f"<td>{row['_score']:.2f}/{row['_max_score']:.2f}</td>"
            f"<td>{_render_inline_markdown(row.get('feedback', ''))}</td>"
            f"<td>{html.escape(row.get('conversion_warnings', ''))}</td>"
            "</tr>"
        )
    parts.append("</table>")
    parts.append("<h3>Percentile Samples</h3>")
    used = set()
    sample_rows = [row for row in question_rows if row.get("response_markdown", "").strip()] or question_rows
    for pct in SAMPLE_PERCENTILES:
        if not sample_rows:
            continue
        row = sample_rows[round((pct / 100) * (len(sample_rows) - 1))]
        key = (row.get("student_id"), row.get("question_id"))
        if key in used:
            continue
        used.add(key)
        response = row.get("response_markdown", "")
        parts += [
            "<div class='sample'>",
            f"<h4>p{pct}: {html.escape(row.get('student_id', ''))} ({row['_score']:.2f}/{row['_max_score']:.2f})</h4>",
            "<h5>Highlighted Model Input</h5>",
            _img(row.get("model_input_path", "") or row.get("crop_path", ""), "response-img"),
            "<h5>Converted Markdown Rendered</h5>",
            f"<div class='rendered-md'>{_render_markdown(response)}</div>",
            "<h5>Converted Markdown Source</h5>",
            f"<pre>{html.escape(response)}</pre>",
            f"<p><strong>Feedback:</strong> {_render_inline_markdown(row.get('feedback', ''))}</p>",
            "</div>",
        ]
    parts.append("</div>")
    return parts


def generate_open_response_report(
    scores_csv: str,
    output_dir: str,
    title: str = "Open-Answer Report",
    mc_correction_dir: Optional[str] = None,
    student_converted_response: bool = False,
    void_questions=None,
    void_questions_nicely=None,
    lang: str = "en",
) -> str:
    """Global report, per-student PDFs and ``overall_marks.csv``. ``void_questions`` and
    ``void_questions_nicely`` (exam numbers or original ids) are applied as described in
    :func:`autocorrect.marks.resolve_question_voids`; void multiple-choice questions in pexams instead."""
    rows = read_csv_rows(scores_csv)
    os.makedirs(output_dir, exist_ok=True)
    mc_feedback = load_mc_feedback_context(mc_correction_dir)
    resolve_question_voids(rows, mc_feedback, void_questions, void_questions_nicely)
    graded_rows = _graded_rows(rows)

    by_question: Dict[str, list[dict]] = {}
    for row in graded_rows:
        by_question.setdefault(row.get("question_id", ""), []).append(row)
    combined = combined_totals(student_totals(graded_rows), mc_feedback)
    write_overall_marks_csv(combined, mc_feedback, output_dir, rows=rows)
    overall_plot = _plot_overall_mark_distribution(combined, output_dir)
    mc_report_styles, mc_report_html = _extract_html_fragment(os.path.join(os.path.abspath(mc_correction_dir), "stats_report.html")) if mc_correction_dir else ("", "")

    parts = [_html_head(REPORT_CSS, title=title, extra_head=mc_report_styles)]
    parts.append(f"<h1>{html.escape(title)}</h1>")
    parts += _overall_section(combined, overall_plot)
    if mc_report_html:
        parts.append("<div class='report-section embedded-mc-report'>")
        parts.append("<h2 class='section-title'>Multiple-Choice Report</h2>")
        parts.append(mc_report_html)
        parts.append("</div>")
    if graded_rows:
        parts.append("<h2 class='section-title'>Open-Answer Report</h2>")
    for question_id, question_rows in sorted(by_question.items()):
        parts += _question_section(question_id, question_rows, output_dir)
    parts.append("</body></html>")

    html_path = os.path.join(output_dir, "open_responses_report.html")
    Path(html_path).write_text("\n".join(parts), encoding="utf-8")
    _write_pdf_from_html(html_path, os.path.join(output_dir, "open_responses_report.pdf"))
    generate_student_feedback_pdfs(scores_csv, output_dir, mc_correction_dir=mc_correction_dir,
                                   include_converted_response=student_converted_response,
                                   void_questions=void_questions, void_questions_nicely=void_questions_nicely,
                                   lang=lang)
    return html_path


def _student_feedback_html(student_id: str, student_rows: list[dict], mc_row: dict,
                           include_converted_response: bool, lang: str) -> str:
    parts = [_html_head(STUDENT_CSS)]
    student_name = student_rows[0].get("student_name", "")
    parts.append("<div class='header'>")
    parts.append(f"<h1>{html.escape(student_name or student_id)}</h1>")
    parts.append(f"<div class='muted'>{_t(lang, 'student_id')}: {html.escape(student_id)}</div>")
    parts.append("</div>")
    parts.append(_student_summary_table(mc_row, student_rows, lang))
    if mc_row and mc_row.get("image_path"):
        parts.append("<div class='section'>")
        parts.append(f"<h2>{_t(lang, 'mc_sheet')}</h2>")
        parts.append(_img(mc_row.get("image_path", ""), "mc-sheet"))
        parts.append("</div>")
    parts.append("<div class='section'>")
    parts.append(f"<h2>{_t(lang, 'open')}</h2>")
    for row in student_rows:
        parts.append("<div class='item'>")
        parts.append(f"<h3>{html.escape(_t(lang, 'question', id=row.get('question_id', '')))}</h3>")
        if row.get("question_text"):
            parts.append(f"<div class='question-text'>{_render_markdown(row.get('question_text', ''))}</div>")
        parts.append(f"<div class='score-pill'>{html.escape(row.get('score', ''))}/{html.escape(row.get('max_score', ''))}</div>")
        # The image the grade is based on: with writing outside the box, the box and its surroundings.
        shown_crop = row.get("context_crop_path") if row.get("graded_from") == "context" else ""
        parts.append(_img(shown_crop if shown_crop and os.path.exists(shown_crop) else row.get("crop_path", ""), "crop"))
        # No feedback for a blank answer: the score says it all.
        if str(row.get("feedback", "")).strip():
            parts.append(f"<div class='feedback'><strong>{_t(lang, 'feedback')}:</strong> {_render_inline_markdown(row.get('feedback', ''))}</div>")
        # The transcription is mostly useful to the teacher (cheaper text-only re-grading),
        # so students only get it when explicitly requested.
        if include_converted_response:
            parts.append(f"<h3>{_t(lang, 'converted')}</h3>")
            parts.append(f"<div class='md'>{_render_markdown(row.get('response_markdown', ''))}</div>")
        parts.append("</div>")
    parts.append("</div>")
    parts.append("</body></html>")
    return "\n".join(parts)


def generate_student_feedback_pdfs(scores_csv: str, output_dir: str, mc_correction_dir: Optional[str] = None,
                                   include_converted_response: bool = False,
                                   void_questions=None, void_questions_nicely=None, lang: str = "en") -> str:
    """One HTML + PDF per student in ``<output_dir>/student_feedback_pdfs``: summary of marks,
    corrected multiple-choice sheet (if any) and each open answer with its feedback."""
    rows = read_csv_rows(scores_csv)
    mc_feedback = load_mc_feedback_context(mc_correction_dir)
    resolve_question_voids(rows, mc_feedback, void_questions, void_questions_nicely)
    grouped: Dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row.get("student_id", "unknown"), []).append(row)
    out_dir = os.path.join(output_dir, "student_feedback_pdfs")
    os.makedirs(out_dir, exist_ok=True)

    for student_id, student_rows in grouped.items():
        html_path = os.path.join(out_dir, f"{safe_name(student_id)}.html")
        Path(html_path).write_text(
            _student_feedback_html(student_id, student_rows, mc_feedback.get(student_id, {}),
                                   include_converted_response, lang),
            encoding="utf-8")
        _write_pdf_from_html(html_path, os.path.join(out_dir, f"{safe_name(student_id)}.pdf"))
    return out_dir
