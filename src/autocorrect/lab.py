"""Grade lab submissions (notebooks, HTML, PDF, Office files...) against a rubric with an LLM
(``pevaluate <session folder>``). One YAML per submission goes to ``<session>/feedback``."""
import argparse
import glob
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Optional

import yaml

from . import utils
from .common import add_hidden_alias
from .parsing.pdf import render_pdf_pages
from .submissions import (
    convert_notebooks_batch,
    extract_nested_zips,
    filter_by_student,
    find_student_files,
    get_student_name_from_path,
    get_submission_group_key,
    get_submission_output_slug,
    get_submission_source_id,
    remove_matching_files,
    resolve_reference_file,
    unzip_submissions,
)
from .utils import load_project_dotenv

NO_REFERENCE = "[No reference content provided]"
GRADING_SYSTEM = "You are a teaching assistant for a data science course."

PROMPT_TEMPLATE = """You are a helpful assistant that grades University assignments. You are given the student submission (mandatory), a rubric (mandatory), an example feedback (optional), a reference solution (optional), and the images extracted from the submission (optional). You need to grade the submission according to the rubric. Provide the feedback in the same language as the ones the student(s) used to answer the questions, written impersonally in the passive voice (e.g. "the model is trained but not evaluated", "falta evaluar el modelo"), not addressing the student(s) as "you". The feedback goes to the students as if written by the teacher: never mention that the grading is automatic, the conversion of the files to text or the extracted images. Be brief: an item with full marks gets only its score, with no explanation of why it is right; explain only the deductions, in one or two concrete sentences each.

Submitted by: {student_name} (in a group assignment, the submission may name the other members).

Here is the student's submission to grade:

{student_content}

--------------------------------

Here is the rubric:

{rubric}

--------------------------------

Here is an example of review (optional, note that the exercises might be completely different, this is just an example of the expected format):

{example_review}

--------------------------------

Here is the reference solution (if provided):

{reference_section}

--------------------------------

Return only valid YAML with this schema:

students:
  - full_name: "Nombre Apellido Apellido"
feedback: |
  Feedback comments for the student, can be multiline.
mark: 0.0

The `students` list must include all members of the work group (if more than one). The `mark` must be the final numeric mark from 0 to 10.

Please provide the feedback now:
"""


def build_grading_prompt(student_name, student_content, rubric, example_review, reference_content):
    reference_section = ""
    if reference_content:
        reference_section = f"""
Here is the reference solution:

{reference_content}
--------------------------------
"""
    return PROMPT_TEMPLATE.format(student_name=student_name, student_content=student_content, rubric=rubric,
                                  example_review=example_review, reference_section=reference_section)


def _limit_images(images, max_images):
    if max_images is None or max_images <= 0:
        return images, 0
    return images[:max_images], max(0, len(images) - max_images)


def save_prompt_markdown(prompt_path, prompt):
    prompt_path = Path(prompt_path)
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text("# pevaluate LLM Prompt\n\n" + prompt.rstrip() + "\n", encoding="utf-8")


def parse_markdown_config(value):
    if not value:
        return {}
    candidate = Path(value)
    if candidate.exists():
        return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(value)


def clean_asset_dir(path):
    path = Path(path)
    if not path.exists():
        return
    for item in path.iterdir():
        if item.is_file():
            item.unlink()


def estimate_prompt_tokens(text):
    try:
        import tiktoken
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text)), "tiktoken:cl100k_base"
    except Exception:
        return max(1, round(len(text) / 4)), "chars/4 estimate"


def extract_structured_feedback(response_text):
    """The grader's YAML answer (students, feedback, mark), tolerating code fences and plain text."""
    text = response_text.strip()
    fence_match = re.search(r"```(?:yaml|yml|json)?\s*(.*?)```", text, flags=re.S | re.I)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        data = yaml.safe_load(text)
    except Exception:
        data = None

    if not isinstance(data, dict):
        mark_match = re.search(r"(?i)(?:nota\s+final|mark|nota)\D{0,20}(\d+(?:[.,]\d+)?)", response_text)
        mark = float(mark_match.group(1).replace(",", ".")) if mark_match else None
        data = {
            "students": [],
            "feedback": response_text.strip(),
            "mark": mark,
        }

    students = data.get("students", [])
    if students is None:
        students = []
    if isinstance(students, str):
        students = [students]
    normalized_students = []
    for student in students:
        if isinstance(student, dict):
            name = student.get("full_name") or student.get("name") or student.get("student") or ""
            normalized_students.append({"full_name": str(name).strip()})
        else:
            normalized_students.append({"full_name": str(student).strip()})
    data["students"] = [s for s in normalized_students if s["full_name"]]

    try:
        data["mark"] = float(str(data.get("mark", "")).replace(",", "."))
    except Exception:
        data["mark"] = None

    data["feedback"] = str(data.get("feedback", response_text)).strip()
    return data


class FeedbackYamlDumper(yaml.SafeDumper):
    """Writes multiline strings as ``|`` blocks, so the feedback stays readable and editable."""


def represent_feedback_string(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


FeedbackYamlDumper.add_representer(str, represent_feedback_string)


def clean_yaml_multiline_strings(value):
    if isinstance(value, str) and "\n" in value:
        return "\n".join(line.rstrip() for line in value.splitlines())
    if isinstance(value, list):
        return [clean_yaml_multiline_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: clean_yaml_multiline_strings(item) for key, item in value.items()}
    return value


def write_feedback_yaml(path, data):
    data = clean_yaml_multiline_strings(data)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, Dumper=FeedbackYamlDumper, allow_unicode=True, sort_keys=False, width=1000)


def _find_session_file(session_folder, name, fallback_glob):
    """``<session>/<name>``, else the first file matching ``fallback_glob`` (None if neither)."""
    path = os.path.join(session_folder, name)
    if os.path.exists(path):
        return path
    candidates = glob.glob(os.path.join(session_folder, fallback_glob))
    return candidates[0] if candidates else None


def _load_rubric(session_folder, name):
    path = _find_session_file(session_folder, name, '[Rr]ubri*.*')
    if path != os.path.join(session_folder, name):
        print(f"Error: Rubric file not found at {os.path.join(session_folder, name)}")
        if path is None:
            return None, None
        print(f"Found alternative rubric file: {path}")
    print(f"Using rubric: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        return path, f.read()


def _load_example(session_folder, name):
    path = _find_session_file(session_folder, name, '[Ee]xample*.*')
    if path != os.path.join(session_folder, name):
        print(f"Warning: Example feedback file not found at {os.path.join(session_folder, name)}")
        if path is not None:
            print(f"Found alternative example file: {path}")
    if path is None:
        print("No example feedback will be included in the prompt.")
        return None, "[No example feedback provided]"
    print(f"Using example review: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        return path, f.read()


def _read_markdown(path, assets_dir, prompts_dir, args, markdown_config):
    """A submission or reference file as Markdown (+ images when --include-images)."""
    if args.include_images:
        clean_asset_dir(assets_dir)
    return utils.read_file_markdown(
        path,
        cleanup_html=not args.no_cleanup_html,
        image_output_dir=assets_dir if args.include_images else None,
        image_reference_dir=prompts_dir if args.include_images else None,
        markdown_config=markdown_config,
        dedupe=not args.no_dedupe_images,
    )


def _load_references(session_folder, students_dir, prompts_dir, args, markdown_config):
    """(content, images, warnings) of the reference solution(s), or None if one is missing."""
    if args.no_reference or not args.reference or args.reference.lower() in ("none", "null", "no"):
        print("No reference file will be included in the prompt.")
        return NO_REFERENCE, [], []
    content, images, warnings = "", [], []
    for i, ref_path in enumerate(args.reference.split(';')):
        resolved_path = resolve_reference_file(session_folder, students_dir, ref_path)
        if not resolved_path:
            print(f"Error: Reference file '{ref_path}' not found.")
            return None
        print(f"Using reference file {i+1}: {resolved_path}")
        extraction = _read_markdown(resolved_path, os.path.join(prompts_dir, f"reference_{i + 1}_images"),
                                    prompts_dir, args, markdown_config)
        content += f"\n\n--- Reference File {i+1} ({os.path.basename(resolved_path)}) ---\n{extraction.markdown}\n"
        images.extend(extraction.images)
        warnings.extend(extraction.warnings)
        if args.include_images:
            print(f"Extracted {len(extraction.images)} image(s) from reference file {i+1}.")
    return content, images, warnings


def _images_for_model(args, reference_images, student_images, warnings):
    """The images attached to the request (deduplicated and limited); notes go to ``warnings``."""
    if not args.include_images:
        return []
    images = reference_images + student_images
    if not args.no_dedupe_images:
        images, duplicate_count = utils.dedupe_images(images)
        if duplicate_count:
            warnings.append(f"Removed {duplicate_count} duplicate image(s) across reference and student files.")
    images, omitted_count = _limit_images(images, args.max_images)
    if omitted_count:
        warnings.append(f"Omitted {omitted_count} image(s) because --max-images is {args.max_images}.")
    return images


def _feedback_record(response_text, meta, student_files, rubric):
    """The YAML stored for a graded submission, with the grader's provenance."""
    student_file_path = student_files[0]
    structured_feedback = extract_structured_feedback(response_text)
    structured_feedback["submission_file"] = student_file_path
    if len(student_files) > 1:
        structured_feedback["submission_files"] = list(student_files)
    structured_feedback["source_id"] = get_submission_source_id(student_file_path)
    structured_feedback["grader"] = {
        "provider": meta["provider"],
        "model": meta["model_served"],
        "effort": meta["effort"],
        "fallback_used": meta["fallback_used"],
        "request_id": meta["request_id"],
        "graded_at_utc": meta["timestamp_utc"],
        "tool_version": meta["tool_version"],
        "rubric_sha256": hashlib.sha256(rubric.encode("utf-8")).hexdigest(),
        "prompt_sha256": meta["prompt_sha256"],
        # The model's own mark and feedback; teacher edits change only the top-level fields.
        "mark": structured_feedback.get("mark"),
        "feedback": structured_feedback.get("feedback"),
    }
    return structured_feedback


def _grade_one(student_files, ctx, args, client):
    """Build the prompt for one submission (one file, or all the files of a submission with
    --whole-submission), save it if asked and, unless --no-evaluate, grade it."""
    student_file_path = student_files[0]
    student_name = get_student_name_from_path(student_file_path)
    prompt_slug = get_submission_output_slug(student_name, student_file_path)
    prompts_dir = ctx["prompts_dir"]
    print(f"Grading submission for {student_name} ({'; '.join(os.path.basename(p) for p in student_files)})...")

    parts, student_images, image_warnings = [], [], list(ctx["reference_warnings"])
    for i, path in enumerate(student_files):
        suffix = f"_{i + 1}" if len(student_files) > 1 else ""
        extraction = _read_markdown(path, os.path.join(prompts_dir, f"prompt_{prompt_slug}_images{suffix}"),
                                    prompts_dir, args, ctx["markdown_config"])
        markdown, images = extraction.markdown, extraction.images
        if getattr(args, "pdf_pages_as_images", False) and path.lower().endswith(".pdf"):
            images = render_pdf_pages(path)
            markdown = (f"[Each of the {len(images)} pages of this PDF is attached as an image, in order: "
                        f"use them for the figures, diagrams and tables.]\n\n{markdown}")
        # The file name too: groups often name their members only there.
        parts.append(f"--- File {i + 1} of {len(student_files)}: {os.path.basename(path)} ---\n{markdown}")
        student_images.extend(images)
        image_warnings.extend(extraction.warnings)
    if args.include_images:
        print(f"Extracted {len(student_images)} image(s) from student submission.")

    prompt = build_grading_prompt(student_name, "\n\n".join(parts), ctx["rubric"], ctx["example_review"],
                                  ctx["reference_content"])
    images_for_model = _images_for_model(args, ctx["reference_images"], student_images, image_warnings)
    if args.include_images and not images_for_model and (student_images or ctx["reference_images"]):
        prompt += "\nImage extraction was requested, but no supported images were attached after filtering.\n"

    estimated_tokens, token_method = estimate_prompt_tokens(prompt)
    print(
        f"Prompt size for {student_name}: {len(prompt):,} chars, "
        f"~{estimated_tokens:,} tokens ({token_method})."
    )
    if args.include_images:
        print(f"Sending {len(images_for_model)} image(s) to the LLM for {student_name}.")
        for warning in image_warnings:
            print(f"Image warning: {warning}")
    if args.keep_prompt:
        prompt_file = os.path.join(prompts_dir, f"prompt_{prompt_slug}.md")
        save_prompt_markdown(prompt_file, prompt)
        print(f"Prompt for {student_name} saved to {prompt_file}")

    if args.no_evaluate:
        print(f"Skipping LLM evaluation for {student_name} because --no-evaluate was set.")
        return

    try:
        response_text, meta = client.complete(
            prompt,
            images=[(image.data, image.mime_type) for image in images_for_model],
            system=GRADING_SYSTEM,
            purpose="grade_submission",
            context={"submission": "; ".join(os.path.basename(p) for p in student_files)},
        )
        structured_feedback = _feedback_record(response_text, meta, student_files, ctx["rubric"])
        feedback_slug = get_submission_output_slug(student_name, student_file_path, structured_feedback)
        feedback_dir = os.path.join(ctx["session_folder"], 'feedback')
        os.makedirs(feedback_dir, exist_ok=True)
        feedback_file = os.path.join(feedback_dir, f"feedback_{feedback_slug}.yaml")
        write_feedback_yaml(feedback_file, structured_feedback)
        print(f"Feedback for {student_name} saved to {feedback_file}")
    except Exception as e:
        print(f"An error occurred while grading {student_name}: {e}")


def grade_submissions(session_folder, students_dir, args):
    """Grades all student submissions using an LLM."""
    if args.no_evaluate:
        print("Preparing grading prompts without calling the LLM...")
    else:
        print("Starting LLM-based grading...")
    load_project_dotenv()
    client = None
    if not args.no_evaluate:
        from .llm import LLMClient

        try:
            client = LLMClient(
                args.model, effort=getattr(args, "effort", None) or None, api_key_env=getattr(args, "api_key_env", None),
                log_path=os.path.join(session_folder, "feedback", "llm_calls.jsonl"), tool="pevaluate",
            )
        except RuntimeError as e:
            print(f"Error: {e}")
            return

    rubric_path, rubric = _load_rubric(session_folder, args.rubric)
    if rubric_path is None:
        return
    example_path, example_review = _load_example(session_folder, args.example)

    markdown_config = parse_markdown_config(getattr(args, "markdown_config", None))
    prompts_dir = os.path.join(session_folder, 'prompts')
    if client is not None:
        from .llm import write_run_manifest
        write_run_manifest(os.path.join(session_folder, "feedback"), "pevaluate grade", client,
                           inputs=[rubric_path, example_path or ""],
                           extra={"session_folder": os.path.abspath(session_folder), "markdown_config": markdown_config})

    references = _load_references(session_folder, students_dir, prompts_dir, args, markdown_config)
    if references is None:
        return
    reference_content, reference_images, reference_warnings = references

    single_file = getattr(args, "single_file", None)
    if single_file:
        student_files = [single_file]
        print(f"Using single submission file: {single_file}")
    else:
        student_files = find_student_files(students_dir, args.files_regex, args.prefer_extensions)
    if args.student:
        student_files = filter_by_student(student_files, args.student)
    print(f"Found {len(student_files)} files to grade matching regex and filter.")

    ctx = {
        "session_folder": session_folder, "prompts_dir": prompts_dir, "markdown_config": markdown_config,
        "rubric": rubric, "example_review": example_review, "reference_content": reference_content,
        "reference_images": reference_images, "reference_warnings": reference_warnings,
    }
    if getattr(args, "whole_submission", False):
        submissions = {}
        for path in student_files:
            submissions.setdefault(get_submission_group_key(path, students_dir), []).append(path)
        print(f"Grading {len(submissions)} submission(s), all their files in one prompt.")
        groups = list(submissions.values())
    else:
        groups = [[path] for path in student_files]
    for files in groups:
        _grade_one(files, ctx, args, client)


DESCRIPTION = "Automate the correction pipeline for assignment submissions."


def build_parser(parser: Optional[argparse.ArgumentParser] = None) -> argparse.ArgumentParser:
    parser = parser or argparse.ArgumentParser(prog="pevaluate", description=DESCRIPTION)
    parser.add_argument("session_folder", help="The path to the assignment/session folder, or a single submission file.")
    parser.add_argument("--no-unzip", action="store_true", help="Skip the unzipping step.")
    parser.add_argument("--no-convert", action="store_true", help="Skip the batch notebook to markdown conversion step.")
    parser.add_argument("--no-grade", action="store_true", help="Skip the LLM-based grading step entirely, including prompt preparation.")
    parser.add_argument("--no-evaluate", action="store_true", help="Prepare inputs, print token estimates, and save prompts when requested, but do not call the LLM.")
    parser.add_argument("--model", default="claude-opus-5-5", help="Grading model. Bare 'claude-...' ids use the Anthropic API; others (e.g. google/gemini-3.1-pro-preview) use OpenRouter.")
    parser.add_argument("--effort", default="medium", help="Reasoning effort (low/medium/high); empty for the provider default.")
    parser.add_argument("--api-key-env", default=None, help="Environment variable holding the API key (default: ANTHROPIC_API_KEY or OPENROUTER_API_KEY).")
    parser.add_argument("--student", help="Filter to grade only a specific student's submission (part of the filename). Can be a semicolon-separated list.")
    parser.add_argument("--rubric", default="rubric.txt", help="Name of the rubric file in the session folder.")
    parser.add_argument("--example", default="example.txt", help="Name of the example feedback file in the session folder.")
    parser.add_argument("--reference", default="", help="Name or path of the reference solution file(s). Multiple files can be separated by semicolon (;). Empty by default.")
    parser.add_argument("--no-reference", action="store_true", help="Do not include any reference solution in the grading prompt.")
    parser.add_argument("--files-regex", default=r".*\.ipynb$", help="Regex to match student files to grade.")
    parser.add_argument("--prefer-extensions", default=".ipynb;.html", help="Semicolon-separated extension priority for duplicate submissions in the same folder. Use an empty string to disable.")
    parser.add_argument("--remove-files-regex", help="Regex to remove specific files from the students directory after unzipping.")
    parser.add_argument("--keep-prompt", "--keep-prompts", dest="keep_prompt", action="store_true", help="Save the grading prompt to a file for debugging.")
    parser.add_argument("--no-cleanup-html", dest="no_cleanup_html", action="store_true", help="Disable removal of HTML style/script/image artifacts from notebooks, markdown, and HTML files.")
    parser.add_argument("--include-images", action="store_true", help="Extract images from supported files and attach them to the LLM request.")
    parser.add_argument("--no-dedupe-images", action="store_true", help="Do not remove duplicate extracted images before sending them to the LLM.")
    parser.add_argument("--max-images", type=int, default=20, help="Maximum extracted images to attach per LLM request. Use 0 for no limit.")
    parser.add_argument("--markdown-config", help="JSON object or path to a JSON file with document-to-Markdown converter options. For PDFs these are passed to pymupdf4llm.to_markdown.")
    parser.add_argument("--students-dir", help="Directory containing already unpacked student submissions. Defaults to <session_folder>/students.")
    parser.add_argument("--pdf-pages-as-images", action="store_true", help="Attach every page of a submitted PDF as an image (with --include-images) instead of the images embedded in it: diagrams drawn as vector graphics are lost otherwise.")
    parser.add_argument("--whole-submission", action="store_true", help="Grade all the matching files of a submission (e.g. a report PDF and its SQL script) in one prompt, instead of one prompt per file.")
    parser.add_argument("--extract-nested-zips", action="store_true", help="Extract zip files found inside the students directory before conversion/grading.")
    parser.add_argument("--output-dir", help="Output/session folder for single-file inputs. Defaults to the input file's parent folder.")
    add_hidden_alias(parser, "--not-cleanup-html", "no_cleanup_html", action="store_true")
    return parser


def run(args: argparse.Namespace):
    """The lab pipeline: unzip, clean, convert and grade (each step can be skipped)."""
    input_path = os.path.abspath(args.session_folder)
    if os.path.isfile(input_path):
        args.single_file = input_path
        if not args.students_dir:
            args.students_dir = os.path.dirname(input_path)
        session_folder = args.output_dir if args.output_dir else os.path.dirname(input_path)
        os.makedirs(session_folder, exist_ok=True)
        args.no_unzip = True
        args.no_convert = True
        print(f"Single-file input detected: {input_path}")
        print(f"Using output/session folder: {session_folder}")
    else:
        if args.output_dir:
            print("Warning: --output-dir is currently only used for single-file inputs; ignoring it for folder input.")
        args.single_file = None
        session_folder = args.session_folder
    students_dir = args.students_dir if args.students_dir else os.path.join(session_folder, 'students')

    if not args.no_unzip:
        unzip_submissions(session_folder, students_dir)
    if args.remove_files_regex:
        remove_matching_files(students_dir, args.remove_files_regex)
    if args.extract_nested_zips:
        extract_nested_zips(students_dir)
    if not args.no_convert:
        # Batch conversion of .ipynb files, useful for manual inspection.
        convert_notebooks_batch(students_dir)
    if not args.no_grade:
        grade_submissions(session_folder, students_dir, args)
    print("Pipeline finished.")


def main(argv: Optional[list[str]] = None):
    run(build_parser().parse_args(argv))
