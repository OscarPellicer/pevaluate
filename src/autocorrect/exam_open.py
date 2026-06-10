import argparse
import base64
import csv
import html
import json
import math
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Dict, Optional

import yaml
from dotenv import load_dotenv


def load_project_dotenv():
    """Load .env files from the current workspace and package parents."""
    seen = set()
    for start in (Path.cwd(), Path(__file__).resolve()):
        folder = start if start.is_dir() else start.parent
        for candidate in (folder, *folder.parents):
            if candidate in seen:
                continue
            seen.add(candidate)
            load_dotenv(candidate / ".env")


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(value)).strip("_") or "item"


def _load_exam_questions(exam_dir: str) -> Dict[str, Dict[str, dict]]:
    questions_by_model: Dict[str, Dict[str, dict]] = {}
    for path in Path(exam_dir).glob("exam_model_*_questions.json"):
        match = re.match(r"exam_model_(.+)_questions\.json$", path.name)
        if not match:
            continue
        model_id = match.group(1)
        payload = json.loads(path.read_text(encoding="utf-8"))
        questions = payload.get("questions", [])
        questions_by_model[model_id] = {str(q.get("id")): q for q in questions}
    return questions_by_model


def _read_index_rows(index_csv: str) -> list[dict]:
    with open(index_csv, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _resolve_crop_path(row: dict, index_csv: str) -> str:
    crop_path = row.get("crop_path", "")
    if os.path.isabs(crop_path):
        return crop_path
    return os.path.abspath(os.path.join(os.path.dirname(index_csv), crop_path))


def _image_data_url(path: str) -> str:
    ext = Path(path).suffix.lower()
    mime = "image/png"
    if ext in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def build_open_answer_prompt(question: dict, row: dict) -> str:
    max_points = row.get("points") or question.get("points") or 1
    expected_answer = question.get("expected_answer") or question.get("explanation") or ""
    rubric = question.get("rubric") or ""

    return f"""Grade this handwritten open-answer exam response.

Return only valid JSON with this shape:
{{
  "score": <number from 0 to {max_points}>,
  "max_score": {max_points},
  "feedback": "<very brief feedback in the language of the student's response>",
  "response_markdown": "<student response transcribed to Markdown, preserving $math$, `code`, and Mermaid diagrams when possible>",
  "conversion_warnings": ["<short warning for any content that could not be converted to Markdown>"],
  "confidence": <number from 0 to 1>
}}

Question:
{question.get("text", "")}

Expected answer:
{expected_answer}

Rubric:
{rubric}

Student:
{row.get("student_id", "")} {row.get("student_name", "")}
"""


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


def _parse_json_response(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        text = match.group(0)
    return json.loads(text)


def _evaluate_with_llm(client, model: str, prompt: str, crop_path: str) -> dict:
    params = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are an assistant helping a teacher grade open-answer exam responses.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _image_data_url(crop_path)}},
                ],
            },
        ],
        "response_format": {"type": "json_object"},
    }
    response = client.chat.completions.create(**params)
    content = response.choices[0].message.content
    return _parse_json_response(content)


def _artifact_stem(row: dict) -> str:
    return f"{_safe_name(row.get('student_id', 'student'))}_q_{_safe_name(row.get('question_id', 'question'))}"


def _coerce_result(result: dict, base_result: dict) -> dict:
    warnings = result.get("conversion_warnings", [])
    if isinstance(warnings, str):
        warnings = [warnings] if warnings else []
    if warnings is None:
        warnings = []
    return {
        "score": result.get("score", ""),
        "max_score": result.get("max_score", base_result.get("max_score", "")),
        "feedback": result.get("feedback", ""),
        "response_markdown": result.get("response_markdown", ""),
        "conversion_warnings": warnings,
        "confidence": result.get("confidence", ""),
    }


def _evaluations_yaml_path(output_dir: str) -> str:
    return os.path.join(output_dir, "open_evaluations.yaml")


def _load_evaluations_yaml(output_dir: str) -> Dict[tuple[str, str], dict]:
    path = _evaluations_yaml_path(output_dir)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        payload = yaml.safe_load(f) or {}
    items = payload.get("responses", []) if isinstance(payload, dict) else []
    loaded = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("student_id", "")), str(item.get("question_id", "")))
        loaded[key] = item
    return loaded


def _write_evaluations_yaml(output_dir: str, result_rows: list[dict]):
    responses = []
    for row in result_rows:
        responses.append({
            "student_id": row.get("student_id", ""),
            "student_name": row.get("student_name", ""),
            "model_id": row.get("model_id", ""),
            "question_id": row.get("question_id", ""),
            "question_text": row.get("question_text", ""),
            "original_id": row.get("original_id", ""),
            "crop_path": row.get("crop_path", ""),
            "model_input_path": row.get("model_input_path", ""),
            "score": row.get("score", ""),
            "max_score": row.get("max_score", ""),
            "feedback": row.get("feedback", ""),
            "response_markdown": row.get("response_markdown", ""),
            "conversion_warnings": [
                warning.strip()
                for warning in str(row.get("conversion_warnings", "")).split(";")
                if warning.strip()
            ],
            "confidence": row.get("confidence", ""),
            "status": row.get("status", ""),
        })
    with open(_evaluations_yaml_path(output_dir), "w", encoding="utf-8") as f:
        yaml.safe_dump({"responses": responses}, f, allow_unicode=True, sort_keys=False, width=1000)


def _highlight_model_input(crop_path: str, output_dir: str, row: dict) -> str:
    marked_dir = os.path.join(output_dir, "model_inputs")
    os.makedirs(marked_dir, exist_ok=True)
    marked_path = os.path.join(marked_dir, f"{_artifact_stem(row)}.png")
    try:
        from PIL import Image, ImageDraw, ImageFont

        source = Image.open(crop_path).convert("RGB")
        width, height = source.size
        label_height = max(22, round(height * 0.08))
        image = Image.new("RGB", (width, height + label_height), "white")
        image.paste(source, (0, label_height))
        draw = ImageDraw.Draw(image)
        border = max(6, round(min(width, height) * 0.02))
        for i in range(border):
            draw.rectangle((i, label_height + i, width - 1 - i, label_height + height - 1 - i), outline=(220, 40, 30))
        try:
            font = ImageFont.truetype("arial.ttf", max(11, round(width * 0.014)))
        except Exception:
            font = None
        label = "Model input crop"
        label_width = min(width, 170)
        draw.rectangle((0, 0, label_width, label_height), fill=(220, 40, 30))
        draw.text((6, max(3, round(label_height * 0.18))), label, fill="white", font=font)
        image.save(marked_path)
        return marked_path
    except Exception:
        return crop_path


def _write_result_artifacts(output_dir: str, row: dict, result: dict, model_input_dir: Optional[str] = None) -> dict:
    if model_input_dir:
        existing_path = os.path.join(model_input_dir, f"{_artifact_stem(row)}.png")
        model_input_path = existing_path if os.path.exists(existing_path) else _highlight_model_input(row.get("crop_path", ""), output_dir, row)
    else:
        model_input_path = _highlight_model_input(row.get("crop_path", ""), output_dir, row)
    return {
        "model_input_path": model_input_path,
    }


def _read_existing_result(output_dir: str, row: dict) -> Optional[dict]:
    yaml_items = _load_evaluations_yaml(output_dir)
    item = yaml_items.get((str(row.get("student_id", "")), str(row.get("question_id", ""))))
    if item is not None:
        return item
    return None


def evaluate_open_responses(
    index_csv: str,
    exam_dir: str,
    output_dir: str,
    model: str = "google/gemini-3.1-pro-preview",
    dry_run: bool = False,
    keep_prompts: bool = False,
    force_regrade: bool = False,
    model_input_dir: Optional[str] = None,
    client=None,
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    prompts_dir = os.path.join(output_dir, "prompts")
    if keep_prompts:
        os.makedirs(prompts_dir, exist_ok=True)

    questions_by_model = _load_exam_questions(exam_dir)
    rows = _read_index_rows(index_csv)

    if not dry_run and client is None:
        import openai

        load_project_dotenv()
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY not found. Use --dry-run to prepare prompts without grading.")
        client = openai.OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)

    result_rows = []
    for row in rows:
        model_id = str(row.get("model_id", ""))
        question_id = str(row.get("question_id", ""))
        question = questions_by_model.get(model_id, {}).get(question_id)
        crop_path = _resolve_crop_path(row, index_csv)

        base_result = {
            "student_id": row.get("student_id", ""),
            "student_name": row.get("student_name", ""),
            "model_id": model_id,
            "question_id": question_id,
            "question_text": (question or {}).get("text", ""),
            "original_id": row.get("original_id", ""),
            "crop_path": crop_path,
            "max_score": row.get("points", "") or (question or {}).get("points", ""),
        }

        if question is None:
            result_rows.append({**base_result, "score": "", "feedback": "Question metadata not found.", "response_markdown": "", "conversion_warnings": "", "confidence": "", "status": "missing_question"})
            continue
        if not os.path.exists(crop_path):
            result_rows.append({**base_result, "score": "", "feedback": "Crop image not found.", "response_markdown": "", "conversion_warnings": "", "confidence": "", "status": "missing_crop"})
            continue

        prompt = build_open_answer_prompt(question, row)
        if keep_prompts:
            prompt_path = os.path.join(prompts_dir, f"{_safe_name(row.get('student_id', 'student'))}_q_{_safe_name(question_id)}.md")
            Path(prompt_path).write_text(prompt, encoding="utf-8")

        existing_result = None if force_regrade else _read_existing_result(output_dir, row)
        if existing_result is not None:
            result = _coerce_result(existing_result, base_result)
            status = "cached"
        elif dry_run:
            result = {"score": "", "max_score": base_result["max_score"], "feedback": "", "response_markdown": "", "conversion_warnings": [], "confidence": ""}
            status = "pending"
        else:
            try:
                result = _coerce_result(_evaluate_with_llm(client, model, prompt, crop_path), base_result)
                status = "graded"
            except Exception as e:
                result = {"score": "", "max_score": base_result["max_score"], "feedback": str(e), "response_markdown": "", "conversion_warnings": [], "confidence": ""}
                status = "error"

        artifact_paths = _write_result_artifacts(output_dir, row, result, model_input_dir=model_input_dir)

        result_rows.append({
            **base_result,
            "score": result.get("score", ""),
            "max_score": result.get("max_score", base_result["max_score"]),
            "feedback": result.get("feedback", ""),
            "response_markdown": result.get("response_markdown", ""),
            "conversion_warnings": "; ".join(result.get("conversion_warnings", []) or []),
            "confidence": result.get("confidence", ""),
            **artifact_paths,
            "evaluations_yaml": _evaluations_yaml_path(output_dir),
            "status": status,
        })

    _write_evaluations_yaml(output_dir, result_rows)
    output_csv = os.path.join(output_dir, "open_scores.csv")
    fieldnames = [
        "student_id", "student_name", "model_id", "question_id", "question_text", "original_id",
        "crop_path", "score", "max_score", "feedback", "response_markdown",
        "conversion_warnings", "confidence", "model_input_path", "evaluations_yaml", "status",
    ]
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(result_rows)
    return output_csv


def _read_scores(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _read_optional_csv(path: str) -> list[dict]:
    if not path or not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _find_student_image(directory: str, student_id: str) -> str:
    if not directory or not os.path.isdir(directory):
        return ""
    safe_id = str(student_id).lower()
    for suffix in ("*.png", "*.jpg", "*.jpeg"):
        for path in Path(directory).glob(suffix):
            stem = path.stem.lower()
            if stem == safe_id or safe_id in stem:
                return str(path)
    return ""


def _load_mc_feedback_context(mc_correction_dir: Optional[str]) -> Dict[str, dict]:
    if not mc_correction_dir:
        return {}
    correction_dir = os.path.abspath(mc_correction_dir)
    final_rows = _read_optional_csv(os.path.join(correction_dir, "final_marks.csv"))
    raw_rows = _read_optional_csv(os.path.join(correction_dir, "correction_results.csv"))
    rows = final_rows or raw_rows
    images_dir = os.path.join(correction_dir, "scanned_pages")
    if not os.path.isdir(images_dir):
        images_dir = correction_dir

    context: Dict[str, dict] = {}
    for row in rows:
        student_id = str(row.get("student_id", "")).strip()
        if not student_id:
            continue
        score = row.get("score", "") or row.get("score_adjusted", "")
        max_score = row.get("max_score", "") or row.get("max_score_adjusted", "") or row.get("total_points", "")
        mark = row.get("mark", "") or row.get("mark_clipped", "")
        context[student_id] = {
            "student_id": student_id,
            "student_name": row.get("student_name", ""),
            "score": score,
            "max_score": max_score,
            "mark": mark,
            "correct": row.get("correct", "") or row.get("correct_count", ""),
            "incorrect": row.get("incorrect", "") or row.get("incorrect_count", ""),
            "na": row.get("NA", "") or row.get("na_count", ""),
            "image_path": _find_student_image(images_dir, student_id),
        }
    if not context and os.path.isdir(images_dir):
        for path in Path(images_dir).glob("*.png"):
            context[path.stem] = {"student_id": path.stem, "image_path": str(path)}
    return context


def _student_totals(graded_rows: list[dict]) -> list[dict]:
    grouped: Dict[str, dict] = {}
    for row in graded_rows:
        key = row.get("student_id", "")
        item = grouped.setdefault(
            key,
            {
                "student_id": key,
                "student_name": row.get("student_name", ""),
                "score": 0.0,
                "max_score": 0.0,
            },
        )
        item["score"] += row["_score"]
        item["max_score"] += row["_max_score"]
    return list(grouped.values())


def _plot_score_distribution(graded_rows: list[dict], output_dir: str) -> Optional[str]:
    totals = _student_totals(graded_rows)
    if not totals:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception:
        return None

    max_score = max(item["max_score"] for item in totals) or 1.0
    max_tick = max(1, math.ceil(max_score))
    binned = [min(max_tick, max(0, math.floor(item["score"] + 0.5))) for item in totals]
    counts = Counter(binned)
    all_scores = np.arange(0, max_tick + 1)
    frequencies = [counts.get(int(score), 0) for score in all_scores]

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(all_scores, frequencies, width=1.0, edgecolor="black", align="center", color="skyblue")
    ax.set_title("Distribution of Open-Answer Scores", fontsize=14, loc="left")
    ax.set_xlabel(f"Score (0-{max_score:g})", fontsize=11)
    ax.set_ylabel("Number of Students", fontsize=11)
    ax.set_xticks(all_scores)
    ax.set_xlim(-0.5, max_tick + 0.5)
    ax.set_ylim(top=max(frequencies, default=0) * 1.1 if any(frequencies) else 1)
    ax.grid(axis="y", linestyle="--", alpha=0.7)
    mean_score = mean(item["score"] for item in totals)
    median_score = sorted(item["score"] for item in totals)[len(totals) // 2]
    ax.axvline(mean_score, color="red", linestyle="dashed", linewidth=1.5, label=f"Mean: {mean_score:.2f}")
    ax.axvline(median_score, color="green", linestyle="dashed", linewidth=1.5, label=f"Median: {median_score:.2f}")
    ax.legend()
    plt.tight_layout()
    plot_path = os.path.join(output_dir, "open_score_distribution.png")
    plt.savefig(plot_path, dpi=300)
    plt.close(fig)
    return plot_path


def _plot_question_distribution(question_rows: list[dict], output_dir: str, question_id: str) -> Optional[str]:
    if not question_rows:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception:
        return None

    max_score = max(row["_max_score"] for row in question_rows) or 1.0
    max_tick = max(1, math.ceil(max_score))
    binned = [min(max_tick, max(0, math.floor(row["_score"] + 0.5))) for row in question_rows]
    counts = Counter(binned)
    all_scores = np.arange(0, max_tick + 1)
    frequencies = [counts.get(int(score), 0) for score in all_scores]

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.bar(all_scores, frequencies, width=1.0, edgecolor="black", align="center", color="skyblue")
    ax.set_title(f"Question {question_id} Score Distribution", fontsize=14, loc="left")
    ax.set_xlabel(f"Score (0-{max_score:g})", fontsize=11)
    ax.set_ylabel("Number of Students", fontsize=11)
    ax.set_xticks(all_scores)
    ax.set_xlim(-0.5, max_tick + 0.5)
    ax.set_ylim(top=max(frequencies, default=0) * 1.1 if any(frequencies) else 1)
    ax.grid(axis="y", linestyle="--", alpha=0.7)
    scores = [row["_score"] for row in question_rows]
    mean_score = mean(scores)
    median_score = sorted(scores)[len(scores) // 2]
    ax.axvline(mean_score, color="red", linestyle="dashed", linewidth=1.5, label=f"Mean: {mean_score:.2f}")
    ax.axvline(median_score, color="green", linestyle="dashed", linewidth=1.5, label=f"Median: {median_score:.2f}")
    ax.legend()
    plt.tight_layout()

    safe_qid = _safe_name(question_id)
    plot_path = os.path.join(output_dir, f"question_{safe_qid}_score_distribution.png")
    plt.savefig(plot_path, dpi=300)
    plt.close(fig)
    return plot_path


def _plot_overall_mark_distribution(items: list[dict], output_dir: str) -> Optional[str]:
    if not items:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception:
        return None

    marks = []
    for item in items:
        max_score = float(item.get("max_score", 0) or 0)
        score = float(item.get("score", 0) or 0)
        marks.append((score / max_score) * 10 if max_score else 0)

    binned = [min(10, max(0, math.floor(mark + 0.5))) for mark in marks]
    counts = Counter(binned)
    all_scores = np.arange(0, 11)
    frequencies = [counts.get(int(score), 0) for score in all_scores]

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(all_scores, frequencies, width=1.0, edgecolor="black", align="center", color="skyblue")
    ax.set_title("Distribution of Overall Marks", fontsize=14, loc="left")
    ax.set_xlabel("Mark (0-10 Scale)", fontsize=11)
    ax.set_ylabel("Number of Students", fontsize=11)
    ax.set_xticks(all_scores)
    ax.set_xlim(-0.5, 10.5)
    ax.set_ylim(top=max(frequencies, default=0) * 1.1 if any(frequencies) else 1)
    ax.grid(axis="y", linestyle="--", alpha=0.7)
    mean_mark = mean(marks)
    median_mark = sorted(marks)[len(marks) // 2]
    ax.axvline(mean_mark, color="red", linestyle="dashed", linewidth=1.5, label=f"Mean: {mean_mark:.2f}")
    ax.axvline(median_mark, color="green", linestyle="dashed", linewidth=1.5, label=f"Median: {median_mark:.2f}")
    ax.legend()
    plt.tight_layout()
    plot_path = os.path.join(output_dir, "overall_mark_distribution.png")
    plt.savefig(plot_path, dpi=300)
    plt.close(fig)
    return plot_path


def _write_pdf_from_html(html_path: str, pdf_path: str) -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(Path(html_path).resolve().as_uri(), wait_until="networkidle")
            try:
                page.evaluate("() => MathJax.typesetPromise()")
                page.wait_for_timeout(500)
            except Exception:
                pass
            try:
                page.wait_for_timeout(1000)
            except Exception:
                pass
            page.pdf(
                path=pdf_path,
                format="A4",
                print_background=True,
                margin={"top": "12mm", "bottom": "12mm", "left": "12mm", "right": "12mm"},
            )
            browser.close()
        return os.path.exists(pdf_path)
    except Exception:
        return False


def _combined_totals(open_totals: list[dict], mc_feedback: Dict[str, dict]) -> list[dict]:
    combined: Dict[str, dict] = {}
    for item in open_totals:
        combined[item["student_id"]] = {
            "student_id": item["student_id"],
            "student_name": item.get("student_name", ""),
            "score": float(item.get("score", 0) or 0),
            "max_score": float(item.get("max_score", 0) or 0),
        }
    for student_id, item in mc_feedback.items():
        target = combined.setdefault(
            student_id,
            {"student_id": student_id, "student_name": item.get("student_name", ""), "score": 0.0, "max_score": 0.0},
        )
        if not target.get("student_name") and item.get("student_name"):
            target["student_name"] = item.get("student_name", "")
        try:
            target["score"] += float(item.get("score", "") or 0)
            target["max_score"] += float(item.get("max_score", "") or 0)
        except ValueError:
            pass
    return list(combined.values())


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


def generate_open_response_report(
    scores_csv: str,
    output_dir: str,
    title: str = "Open-Answer Report",
    mc_correction_dir: Optional[str] = None,
) -> str:
    rows = _read_scores(scores_csv)
    os.makedirs(output_dir, exist_ok=True)
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

    by_question: Dict[str, list[dict]] = {}
    for row in graded_rows:
        by_question.setdefault(row.get("question_id", ""), []).append(row)
    totals = _student_totals(graded_rows)
    total_scores = [item["score"] for item in totals]
    total_max = max((item["max_score"] for item in totals), default=0.0)
    mc_feedback = _load_mc_feedback_context(mc_correction_dir)
    combined = _combined_totals(totals, mc_feedback)
    overall_plot = _plot_overall_mark_distribution(combined, output_dir)
    mc_report_styles, mc_report_html = _extract_html_fragment(os.path.join(os.path.abspath(mc_correction_dir), "stats_report.html")) if mc_correction_dir else ("", "")

    def img_html(path: str) -> str:
        if not path or not os.path.exists(path):
            return "<em>Missing image</em>"
        return f'<img src="{Path(path).resolve().as_uri()}" class="response-img">'

    def md_text(row: dict) -> str:
        return row.get("response_markdown", "")

    def render_md(text: str) -> str:
        return _render_markdown(text)

    css = """
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
    parts = [f"""<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Open+Sans:ital,wght@0,300..800;1,300..800&display=swap">
<script src="https://polyfill.io/v3/polyfill.min.js?features=es6"></script>
<script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
<script type="module">import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs'; mermaid.initialize({{startOnLoad: true}}); window.mermaid = mermaid;</script>
{mc_report_styles}
<style>{css}</style></head><body>"""]
    parts.append(f"<h1>{html.escape(title)}</h1>")
    if combined:
        marks = [(item["score"] / item["max_score"]) * 10 if item["max_score"] else 0 for item in combined]
        parts.append("<div class='report-section'>")
        parts.append("<h2 class='section-title'>Overall Results</h2>")
        parts.append("<div class='stats-grid'>")
        parts.append(f"<div class='stat-item'><span class='stat-label'>Students</span><span class='stat-value'>{len(combined)}</span></div>")
        parts.append(f"<div class='stat-item'><span class='stat-label'>Mean Mark</span><span class='stat-value'>{mean(marks):.2f}/10</span></div>")
        parts.append(f"<div class='stat-item'><span class='stat-label'>Median Mark</span><span class='stat-value'>{sorted(marks)[len(marks) // 2]:.2f}/10</span></div>")
        parts.append("</div>")
        if overall_plot and os.path.exists(overall_plot):
            parts.append(f"<img src='{Path(overall_plot).resolve().as_uri()}' class='distribution-img' alt='Overall Mark Distribution'>")
        parts.append("<table class='overall-table'><tr><th>Student</th><th>Total Score</th><th>Max Score</th><th>Mark</th></tr>")
        for item in sorted(combined, key=lambda row: row.get("student_id", "")):
            mark = (item["score"] / item["max_score"]) * 10 if item["max_score"] else 0
            label = f"{item.get('student_id', '')} {item.get('student_name', '')}".strip()
            parts.append(f"<tr><td>{html.escape(label)}</td><td>{item['score']:.2f}</td><td>{item['max_score']:.2f}</td><td>{mark:.2f}</td></tr>")
        parts.append("</table>")
        parts.append("</div>")
    else:
        parts.append("<p>No graded open-answer rows found.</p>")

    if mc_report_html:
        parts.append("<div class='report-section embedded-mc-report'>")
        parts.append("<h2 class='section-title'>Multiple-Choice Report</h2>")
        parts.append(mc_report_html)
        parts.append("</div>")

    if graded_rows:
        parts.append("<h2 class='section-title'>Open-Answer Report</h2>")

    percentiles = [0, 25, 75, 100]
    for question_id, question_rows in sorted(by_question.items()):
        question_rows = sorted(question_rows, key=lambda row: row["_mark"])
        parts.append("<div class='question-block'>")
        question_text = next((row.get("question_text", "") for row in question_rows if row.get("question_text", "")), "")
        parts.append(f"<h2 class='section-title'>Question {html.escape(question_id)}</h2>")
        if question_text:
            parts.append(f"<div class='question-text'>{render_md(question_text)}</div>")
        q_marks = [row["_mark"] for row in question_rows]
        if q_marks:
            parts.append("<div class='stats-grid'>")
            parts.append(f"<div class='stat-item'><span class='stat-label'>Students</span><span class='stat-value'>{len({row.get('student_id', '') for row in question_rows})}</span></div>")
            parts.append(f"<div class='stat-item'><span class='stat-label'>Responses</span><span class='stat-value'>{len(question_rows)}</span></div>")
            parts.append(f"<div class='stat-item'><span class='stat-label'>Mean</span><span class='stat-value'>{mean(q_marks):.2f}/10</span></div>")
            parts.append(f"<div class='stat-item'><span class='stat-label'>Min / Max</span><span class='stat-value'>{min(q_marks):.2f} / {max(q_marks):.2f}</span></div>")
            parts.append("</div>")
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
                f"<td>{html.escape(row.get('feedback', ''))}</td>"
                f"<td>{html.escape(row.get('conversion_warnings', ''))}</td>"
                "</tr>"
            )
        parts.append("</table>")
        parts.append("<h3>Percentile Samples</h3>")
        used = set()
        non_empty_rows = [row for row in question_rows if md_text(row).strip()]
        sample_rows = non_empty_rows or question_rows
        for pct in percentiles:
            if not sample_rows:
                continue
            idx = round((pct / 100) * (len(sample_rows) - 1))
            row = sample_rows[idx]
            key = (row.get("student_id"), row.get("question_id"))
            if key in used:
                continue
            used.add(key)
            parts.append("<div class='sample'>")
            parts.append(f"<h4>p{pct}: {html.escape(row.get('student_id', ''))} ({row['_score']:.2f}/{row['_max_score']:.2f})</h4>")
            parts.append("<h5>Highlighted Model Input</h5>")
            parts.append(img_html(row.get("model_input_path", "") or row.get("crop_path", "")))
            parts.append("<h5>Converted Markdown Rendered</h5>")
            parts.append(f"<div class='rendered-md'>{render_md(md_text(row))}</div>")
            parts.append("<h5>Converted Markdown Source</h5>")
            parts.append(f"<pre>{html.escape(md_text(row))}</pre>")
            parts.append(f"<p><strong>Feedback:</strong> {html.escape(row.get('feedback', ''))}</p>")
            parts.append("</div>")
        parts.append("</div>")

    parts.append("</body></html>")
    html_path = os.path.join(output_dir, "open_responses_report.html")
    Path(html_path).write_text("\n".join(parts), encoding="utf-8")
    pdf_path = os.path.join(output_dir, "open_responses_report.pdf")
    _write_pdf_from_html(html_path, pdf_path)
    generate_student_feedback_pdfs(scores_csv, output_dir, mc_correction_dir=mc_correction_dir)
    return html_path


def generate_student_feedback_pdfs(scores_csv: str, output_dir: str, mc_correction_dir: Optional[str] = None) -> str:
    rows = _read_scores(scores_csv)
    grouped: Dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row.get("student_id", "unknown"), []).append(row)
    out_dir = os.path.join(output_dir, "student_feedback_pdfs")
    os.makedirs(out_dir, exist_ok=True)
    mc_feedback = _load_mc_feedback_context(mc_correction_dir)

    def render_md(text: str) -> str:
        return _render_markdown(text)

    def img(path: str) -> str:
        if path and os.path.exists(path):
            return f'<img src="{Path(path).resolve().as_uri()}" class="crop">'
        return "<em>Missing image</em>"

    css = """
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
    """
    html_paths = []
    for student_id, student_rows in grouped.items():
        parts = [f"""<!doctype html><html><head><meta charset='utf-8'>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Open+Sans:ital,wght@0,300..800;1,300..800&display=swap">
<script src="https://polyfill.io/v3/polyfill.min.js?features=es6"></script>
<script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
<script type="module">import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs'; mermaid.initialize({{startOnLoad: true}}); window.mermaid = mermaid;</script>
<style>{css}</style></head><body>"""]
        student_name = student_rows[0].get("student_name", "")
        parts.append("<div class='header'>")
        parts.append(f"<h1>{html.escape(student_name or student_id)}</h1>")
        parts.append(f"<div class='muted'>Student ID: {html.escape(student_id)}</div>")
        parts.append("</div>")
        mc_row = mc_feedback.get(student_id, {})
        if mc_row and mc_row.get("image_path"):
            parts.append("<div class='section'>")
            parts.append("<h2>Corrected Multiple-Choice Template</h2>")
            parts.append(img(mc_row.get("image_path", "")).replace("class=\"crop\"", "class=\"mc-sheet\""))
            parts.append("</div>")
        parts.append("<div class='section'>")
        parts.append("<h2>Open-Answer Feedback</h2>")
        for row in student_rows:
            parts.append("<div class='item'>")
            parts.append(f"<h3>Question {html.escape(row.get('question_id', ''))}</h3>")
            if row.get("question_text"):
                parts.append(f"<div class='question-text'>{render_md(row.get('question_text', ''))}</div>")
            parts.append(f"<div class='score-pill'>{html.escape(row.get('score', ''))}/{html.escape(row.get('max_score', ''))}</div>")
            parts.append(img(row.get("crop_path", "")))
            parts.append(f"<div class='feedback'><strong>Feedback:</strong> {html.escape(row.get('feedback', ''))}</div>")
            parts.append("<h3>Converted response</h3>")
            parts.append(f"<div class='md'>{render_md(row.get('response_markdown', ''))}</div>")
            parts.append("</div>")
        parts.append("</div>")
        parts.append("</body></html>")
        html_path = os.path.join(out_dir, f"{_safe_name(student_id)}.html")
        pdf_path = os.path.join(out_dir, f"{_safe_name(student_id)}.pdf")
        Path(html_path).write_text("\n".join(parts), encoding="utf-8")
        html_paths.append(html_path)
        _write_pdf_from_html(html_path, pdf_path)
    return out_dir


def _post_analysis_yaml_path(output_dir: str) -> str:
    return os.path.join(output_dir, "post_analysis.yaml")


def _reevaluation_output_dir(output_dir: str) -> str:
    path = Path(output_dir)
    if path.name.lower() == "evaluation":
        return str(path.parent / "reevaluation")
    return str(path / "reevaluation")


def run_post_analysis(scores_csv: str, output_dir: str, model: str = "google/gemini-3.1-pro-preview", force: bool = False, client=None) -> str:
    output_path = _post_analysis_yaml_path(output_dir)
    if os.path.exists(output_path) and not force:
        return output_path
    os.makedirs(output_dir, exist_ok=True)

    rows = _read_scores(scores_csv)
    responses = [
        {
            "question_id": row.get("question_id", ""),
            "score": row.get("score", ""),
            "max_score": row.get("max_score", ""),
            "response_markdown": row.get("response_markdown", ""),
            "feedback": row.get("feedback", ""),
        }
        for row in rows
    ]

    if client is None:
        import openai

        load_project_dotenv()
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY not found.")
        client = openai.OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)

    prompt = (
        "Analyze these graded open-answer exam responses. Return JSON with keys "
        "typical_errors (list of strings), suggested_rubric_markdown (string), "
        "and notes (string).\n\n"
        + json.dumps(responses, ensure_ascii=False)
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You help teachers analyze graded exam responses."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )
    data = _parse_json_response(response.choices[0].message.content)
    payload = {
        "source_scores_csv": os.path.abspath(scores_csv),
        "responses_count": len(rows),
        "typical_errors": data.get("typical_errors", []),
        "notes": data.get("notes", ""),
        "suggested_rubric_markdown": data.get("suggested_rubric_markdown", ""),
    }
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False, width=1000)
    return output_path


class _SmokeMessage:
    def __init__(self, content: str):
        self.content = content


class _SmokeChoice:
    def __init__(self, content: str):
        self.message = _SmokeMessage(content)


class _SmokeResponse:
    def __init__(self, content: str):
        self.choices = [_SmokeChoice(content)]


class _SmokeCompletions:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        prompt = json.dumps(kwargs.get("messages", ""), ensure_ascii=False)
        if "Analyze these graded open-answer exam responses" in prompt:
            return _SmokeResponse(json.dumps({
                "typical_errors": ["Some answers mention overfitting but omit validation performance."],
                "suggested_rubric_markdown": "4 points: 2 complexity penalty, 1 overfitting/generalization, 1 train-validation contrast.",
                "notes": "The original rubric is mostly aligned.",
            }))
        samples = [
            (0.5, "Needs the core idea of regularization.", "Regularization changes the model.\n\nI am not sure how.", ["Handwriting had one unclear word."]),
            (2.0, "Mentions overfitting but misses validation.", "Regularization reduces overfitting.\n\nIt adds a penalty $\\lambda\\|w\\|^2$ to discourage large weights.", []),
            (3.0, "Good answer; mention validation performance more explicitly.", "Regularization reduces overfitting by penalizing complex models.\n\n```mermaid\ngraph LR\n    Complex[Complex model] --> Penalty[Penalty term]\n    Penalty --> Generalization[Better generalization]\n```\n\nIt may lower training score but improve validation performance.", []),
            (4.0, "Complete and precise.", "Regularization adds a penalty $\\lambda$ to model complexity.\n\nTraining may go down while validation improves.", []),
        ]
        score, feedback, response_md, warnings = samples[self.calls % len(samples)]
        self.calls += 1
        return _SmokeResponse(json.dumps({
            "score": score,
            "max_score": 4,
            "feedback": feedback,
            "response_markdown": response_md,
            "conversion_warnings": warnings,
            "confidence": 0.85,
        }))


class _SmokeChat:
    def __init__(self):
        self.completions = _SmokeCompletions()


class _SmokeClient:
    def __init__(self):
        self.chat = _SmokeChat()


def _write_smoke_png(path: str, lines: list[str]):
    try:
        from PIL import Image, ImageDraw
        from PIL import ImageFont

        image = Image.new("RGB", (900, 260), "white")
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype("arial.ttf", 18)
        except Exception:
            font = None
        y = 28
        for line in lines:
            draw.text((24, y), line, fill="black", font=font)
            y += 34
        image.save(path)
    except Exception:
        Path(path).write_bytes(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAAC0lEQVR4nGNg+A8AAwMBAY+ip1sAAAAASUVORK5CYII="
            )
        )


def _write_smoke_scan_page(path: str, student_id: str, student_name: str, score: float):
    try:
        from PIL import Image, ImageDraw
        from PIL import ImageFont

        image = Image.new("RGB", (1654, 2339), "white")
        draw = ImageDraw.Draw(image)
        try:
            title_font = ImageFont.truetype("arial.ttf", 44)
            body_font = ImageFont.truetype("arial.ttf", 28)
        except Exception:
            title_font = None
            body_font = None
        draw.rectangle((90, 100, 1564, 360), outline="black", width=4)
        draw.text((130, 150), "Corrected Multiple-Choice Template", fill="black", font=title_font)
        draw.text((130, 230), f"Student: {student_name} ({student_id})", fill="black", font=body_font)
        draw.text((130, 290), f"Score: {score:.2f}/3.00", fill="black", font=body_font)
        y = 460
        for question_no in range(1, 4):
            draw.rectangle((140, y, 1514, y + 320), outline="#334155", width=3)
            draw.text((180, y + 40), f"Question {question_no}", fill="black", font=body_font)
            draw.text((180, y + 120), "Detected answer and correction preview", fill="#475569", font=body_font)
            draw.line((920, y + 70, 1320, y + 70), fill="#16a34a", width=8)
            draw.line((920, y + 140, 1320, y + 140), fill="#dc2626", width=8)
            y += 420
        image.save(path)
    except Exception:
        _write_smoke_png(path, [student_name, "MC correction placeholder"])


def _write_smoke_mc_report(mc_dir: str, students: list[tuple[str, str, float, list[str]]]):
    scans_dir = os.path.join(mc_dir, "scanned_pages")
    os.makedirs(scans_dir, exist_ok=True)
    for student_id, student_name, mc_score, _lines in students:
        _write_smoke_scan_page(os.path.join(scans_dir, f"{student_id}.png"), student_id, student_name, mc_score)

    _write_smoke_png(
        os.path.join(mc_dir, "mark_distribution_0_10.png"),
        ["Mark distribution", "MC smoke artifact"],
    )
    stats_html_path = os.path.join(mc_dir, "stats_report.html")
    Path(stats_html_path).write_text(
        "<!doctype html><html><body><h1>Exam Statistics Report</h1><p>Deterministic MC smoke report generated by pevaluate.</p><h2>Question Analysis</h2><p>Placeholder question analysis for smoke testing.</p></body></html>",
        encoding="utf-8",
    )
    _write_pdf_from_html(stats_html_path, os.path.join(mc_dir, "stats_report.pdf"))
    with open(os.path.join(mc_dir, "final_marks.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["student_id", "student_name", "score", "max_score", "correct", "incorrect", "NA", "mark"])
        writer.writeheader()
        for student_id, student_name, mc_score, _lines in students:
            writer.writerow({
                "student_id": student_id,
                "student_name": student_name,
                "score": mc_score,
                "max_score": 3,
                "correct": int(mc_score),
                "incorrect": 3 - int(mc_score),
                "NA": 0,
                "mark": round((mc_score / 3) * 10, 2),
            })


def run_open_answer_smoke_test(output_dir: Optional[str] = None, real_llm: bool = False, model: str = "google/gemini-3.1-pro-preview") -> str:
    root = output_dir or tempfile.mkdtemp(prefix="pevaluate_open_smoke_")
    os.makedirs(root, exist_ok=True)
    exam_dir = os.path.join(root, "exam")
    crops_dir = os.path.join(root, "open_responses")
    eval_dir = os.path.join(root, "evaluation")
    mc_dir = os.path.join(root, "mc_correction")
    mc_scans_dir = os.path.join(mc_dir, "scanned_pages")
    os.makedirs(exam_dir, exist_ok=True)
    os.makedirs(crops_dir, exist_ok=True)
    os.makedirs(mc_scans_dir, exist_ok=True)

    Path(os.path.join(exam_dir, "exam_model_1_questions.json")).write_text(
        json.dumps({
            "questions": [
                {
                    "id": 2,
                    "question_type": "open_answer",
                    "text": "Explain why regularization with a penalty λ can improve generalization.",
                    "points": 4,
                    "expected_answer": "Regularization uses a penalty λ to discourage overly complex models and can reduce overfitting.",
                    "rubric": "2 points for model complexity, 1 for overfitting/generalization, 1 for train/validation contrast.",
                }
            ]
        }, indent=2),
        encoding="utf-8",
    )
    index_csv = os.path.join(root, "open_responses_index.csv")
    with open(index_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["student_id", "student_name", "model_id", "question_id", "original_id", "points", "crop_path"],
        )
        writer.writeheader()
        smoke_students = [
            ("student-1", "Student One", 1.0, ["Regularization changes the model.", "I am not sure how."]),
            ("student-2", "Student Two", 2.0, ["Regularization reduces overfitting.", "It adds λ||w||² to penalize large weights."]),
            ("student-3", "Student Three", 3.0, ["Regularization reduces overfitting by penalizing complex models.", "complex model → penalty → better validation"]),
            ("student-4", "Student Four", 3.0, ["Regularization adds a penalty λ to model complexity.", "Training may go down while validation improves."]),
        ]
        _write_smoke_mc_report(mc_dir, smoke_students)

        for student_id, student_name, _mc_score, lines in smoke_students:
            crop_path = os.path.join(crops_dir, f"{student_id}_model_1_q_2.png")
            _write_smoke_png(crop_path, lines)
            writer.writerow({
                "student_id": student_id,
                "student_name": student_name,
                "model_id": "1",
                "question_id": "2",
                "original_id": "open_regularization",
                "points": "4",
                "crop_path": crop_path,
            })

    client = None if real_llm else _SmokeClient()
    scores_csv = evaluate_open_responses(
        index_csv=index_csv,
        exam_dir=exam_dir,
        output_dir=eval_dir,
        model=model,
        client=client,
        force_regrade=True,
    )
    reeval_dir = os.path.join(root, "reevaluation")
    run_post_analysis(scores_csv, reeval_dir, model=model, force=True, client=client)
    evaluate_open_responses(
        index_csv=index_csv,
        exam_dir=exam_dir,
        output_dir=reeval_dir,
        model=model,
        client=client,
        force_regrade=True,
        model_input_dir=os.path.join(eval_dir, "model_inputs"),
    )
    generate_open_response_report(os.path.join(reeval_dir, "open_scores.csv"), reeval_dir, title="Open-Answer Re-Evaluation Report", mc_correction_dir=mc_dir)
    generate_open_response_report(scores_csv, eval_dir, mc_correction_dir=mc_dir)
    return eval_dir


def main(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(description="Grade pexams open-answer response crops with an LLM.")
    parser.add_argument("--index-csv", required=True, help="Path to pexams open_responses_index.csv.")
    parser.add_argument("--exam-dir", required=True, help="Directory containing exam_model_*_questions.json.")
    parser.add_argument("--output-dir", required=True, help="Directory for open_scores.csv, prompts, and feedback.")
    parser.add_argument("--model", default="google/gemini-3.1-pro-preview", help="OpenRouter model to use.")
    parser.add_argument("--dry-run", action="store_true", help="Write prompts and pending score rows without calling an LLM.")
    parser.add_argument("--keep-prompts", action="store_true", help="Save generated grading prompts.")
    parser.add_argument("--force-regrade", action="store_true", help="Ignore existing per-response evaluation JSON files and call the model again.")
    parser.add_argument("--post-analysis", action="store_true", help="Analyze graded responses and suggest rubric refinements.")
    parser.add_argument("--re-evaluate", action="store_true", help="Reserved for regrading with a revised rubric after post-analysis.")
    parser.add_argument("--mc-correction-dir", help="Optional pexams correction-results directory to merge multiple-choice feedback into per-student PDFs.")
    args = parser.parse_args(argv)

    output_csv = evaluate_open_responses(
        index_csv=args.index_csv,
        exam_dir=args.exam_dir,
        output_dir=args.output_dir,
        model=args.model,
        dry_run=args.dry_run,
        keep_prompts=args.keep_prompts,
        force_regrade=args.force_regrade,
    )
    report_path = generate_open_response_report(output_csv, args.output_dir, mc_correction_dir=args.mc_correction_dir)
    print(f"Open-answer scores saved to: {output_csv}")
    print(f"Open-answer report saved to: {report_path}")
    if args.post_analysis:
        analysis_dir = _reevaluation_output_dir(args.output_dir) if args.re_evaluate else args.output_dir
        analysis_path = run_post_analysis(output_csv, analysis_dir, model=args.model, force=args.force_regrade)
        print(f"Post-analysis saved to: {analysis_path}")
    if args.re_evaluate:
        if not args.post_analysis:
            analysis_path = run_post_analysis(output_csv, _reevaluation_output_dir(args.output_dir), model=args.model, force=args.force_regrade)
            print(f"Post-analysis saved to: {analysis_path}")
        reeval_dir = _reevaluation_output_dir(args.output_dir)
        reeval_csv = evaluate_open_responses(
            index_csv=args.index_csv,
            exam_dir=args.exam_dir,
            output_dir=reeval_dir,
            model=args.model,
            dry_run=args.dry_run,
            keep_prompts=args.keep_prompts,
            force_regrade=args.force_regrade,
            model_input_dir=os.path.join(args.output_dir, "model_inputs"),
        )
        reeval_report = generate_open_response_report(reeval_csv, reeval_dir, title="Open-Answer Re-Evaluation Report", mc_correction_dir=args.mc_correction_dir)
        print(f"Re-evaluation scores saved to: {reeval_csv}")
        print(f"Re-evaluation report saved to: {reeval_report}")


def smoke_main(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(description="Run a small open-answer evaluation smoke test.")
    parser.add_argument("--output-dir", help="Directory where smoke artifacts will be written.")
    parser.add_argument("--real-llm", action="store_true", help="Call OpenRouter instead of the built-in fake client. This burns tokens.")
    parser.add_argument("--model", default="google/gemini-3.1-pro-preview", help="OpenRouter model for --real-llm.")
    args = parser.parse_args(argv)
    output_dir = run_open_answer_smoke_test(args.output_dir, real_llm=args.real_llm, model=args.model)
    print(f"Open-answer smoke artifacts saved to: {output_dir}")


if __name__ == "__main__":
    main()
