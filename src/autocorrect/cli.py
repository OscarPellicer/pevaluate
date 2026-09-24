'''
This script automates the correction pipeline for JupyterLab sessions.
Usage:
    1) Install the dependencies: openai, dotenv, tenacity, python-docx, pypdf
    2) Set the OPENROUTER_API_KEY in the .env file.
    3) Make sure the session folder contains the required files (rubric, example, reference).
    4) Run the script: autocorrect <session_folder>
'''

import argparse
import csv
import html
import json
import os
import glob
import shutil
import re
import sys
import zipfile
import hashlib
import unicodedata
from . import flatunzip
from . import utils
try:
    from . import jupyter2md
except ImportError:
    jupyter2md = None
try:
    import openai
except ImportError:
    openai = None
import yaml
from pathlib import Path
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception

MOODLE_COLUMN_ALIASES = {
    "name": [
        "Nom complet", "Nombre completo", "Full name", "Name", "Cognoms i nom",
        "Apellidos y nombre", "Cognoms", "Nombre",
    ],
    "grade": [
        "Qualificació", "Qualificació.", "Calificación", "Calificación.",
        "Grade", "Nota", "Puntuación", "QualificaciÃ³",
    ],
    "feedback": [
        "Comentaris de retroacció.", "Comentaris de retroacció",
        "Comentarios de retroacción.", "Comentarios de retroacción",
        "Comentarios de retroalimentación.", "Comentarios de retroalimentación",
        "Feedback comments", "Feedback", "Comentaris de retroacciÃ³.",
    ],
    "submission_modified": [
        "Darrera modificació (tramesa)", "Última modificación (entrega)",
        "Last modified (submission)", "Darrera modificaciÃ³ (tramesa)",
    ],
    "grade_modified": [
        "Darrera modificació (qualificació)", "Última modificación (calificación)",
        "Last modified (grade)", "Darrera modificaciÃ³ (qualificaciÃ³)",
    ],
}


def normalize_column_name(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def resolve_moodle_column(fieldnames, requested, role, required=True):
    if requested == "":
        return None
    if requested and requested in fieldnames:
        return requested

    lookup = {normalize_column_name(name): name for name in fieldnames}
    candidates = []
    if requested:
        candidates.append(requested)
    candidates.extend(MOODLE_COLUMN_ALIASES.get(role, []))

    for candidate in candidates:
        resolved = lookup.get(normalize_column_name(candidate))
        if resolved:
            if requested and requested != resolved:
                print(f"Resolved Moodle column '{requested}' to '{resolved}'.")
            return resolved

    if required:
        print(f"CSV column not found for {role}: {requested}. Available columns: {fieldnames}")
    return None


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

def unzip_submissions(session_folder, students_dir):
    """Unzips all student submissions."""
    print("Unzipping student submissions...")
    zip_files = glob.glob(os.path.join(session_folder, '*.zip'))
    if not zip_files:
        print("No zip files found in the session folder.")
        return

    # Clean up existing students directory to avoid duplicates from previous runs
    if os.path.exists(students_dir):
        print(f"Cleaning up existing students directory: {students_dir}")
        # On Windows, sometimes rmtree fails if a file is open or locked.
        # We'll try to handle it gracefully or just remove content.
        try:
            shutil.rmtree(students_dir)
        except PermissionError:
            print(f"Warning: Could not fully remove {students_dir}. Trying to empty it instead.")
            for root, dirs, files in os.walk(students_dir):
                for f in files:
                    try:
                        os.unlink(os.path.join(root, f))
                    except Exception as e:
                        print(f"Failed to delete {f}: {e}")
                for d in dirs:
                    try:
                        shutil.rmtree(os.path.join(root, d))
                    except Exception as e:
                        print(f"Failed to delete directory {d}: {e}")
        except Exception as e:
             print(f"Error cleaning students dir: {e}")

    os.makedirs(students_dir, exist_ok=True)
    for zip_file in zip_files:
        print(f"Unzipping {zip_file}...")
        flatunzip.unpack_and_flatten(zip_file, students_dir)
    print("Unzipping completed.")

def convert_notebooks_batch(students_dir):
    """Converts notebooks to markdown (batch processing)."""
    print("Converting notebooks to markdown (batch)...")
    if jupyter2md is None:
        print("Notebook conversion requires nbconvert. Install pevaluate notebook dependencies or use --no-convert.")
        return
    if not os.path.exists(students_dir):
        print(f"Students directory '{students_dir}' not found. Skipping conversion.")
        return
    
    # Clean up existing .md files to avoid duplicates from previous runs with different naming
    for md_file in glob.glob(os.path.join(students_dir, '**', '*.md'), recursive=True):
        try:
            os.remove(md_file)
        except OSError:
            pass

    jupyter2md.convert_notebooks(Path(students_dir))
    print("Conversion to markdown completed.")

def extract_nested_zips(students_dir):
    """Extracts zip files already present inside the students directory."""
    print("Extracting nested zip files from students directory...")
    if not os.path.exists(students_dir):
        print(f"Students directory '{students_dir}' not found. Skipping nested zip extraction.")
        return

    zip_files = []
    for root, _, files in os.walk(students_dir):
        if any(part == ".autocorrect_unzipped" or part.endswith("_unzipped") for part in Path(root).parts):
            continue
        for file in files:
            if file.lower().endswith(".zip"):
                zip_files.append(os.path.join(root, file))

    extracted = 0
    extracted_root = os.path.join(students_dir, ".autocorrect_unzipped")
    os.makedirs(extracted_root, exist_ok=True)

    for zip_file in zip_files:
        zip_hash = hashlib.md5(zip_file.encode("utf-8")).hexdigest()[:8]
        output_dir = os.path.join(extracted_root, f"{Path(zip_file).stem[:24]}_{zip_hash}")
        os.makedirs(output_dir, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_file) as zf:
                count = 0
                for member in zf.infolist():
                    if member.is_dir() or "__MACOSX" in member.filename or ".DS_Store" in member.filename:
                        continue
                    member_hash = hashlib.md5(member.filename.encode("utf-8")).hexdigest()[:8]
                    basename = os.path.basename(member.filename.replace("\\", "/"))
                    safe_basename = basename.encode("ascii", "ignore").decode() or "file"
                    safe_basename = re.sub(r"[^A-Za-z0-9_.-]+", "_", safe_basename)
                    stem, ext = os.path.splitext(safe_basename)
                    output_name = f"{stem[:35]}_{member_hash}{ext}"
                    with open(os.path.join(output_dir, output_name), "wb") as f:
                        f.write(zf.read(member))
                    count += 1
                if count == 0:
                    print(f"Warning: nested zip had no extractable files: {zip_file}")
            extracted += 1
        except zipfile.BadZipFile:
            print(f"Warning: nested zip is not valid: {zip_file}")
        except Exception as e:
            print(f"Warning: could not extract nested zip {zip_file}: {e}")

    print(f"Extracted {extracted} nested zip files.")

def get_student_name_from_path(path):
    """Extracts student name from file path."""
    filename = os.path.basename(path)
    parts = filename.split('_')
    
    # Heuristic: Look for a part containing a comma
    for part in parts:
        if ',' in part:
            return part
            
    # Fallback: Assuming name is between the first and second underscore (Old Logic)
    # But with new flatunzip format: Zip_Hash_Suffix
    # If Suffix is Student_File, then parts[2] is Student.
    if len(parts) > 2:
        # If we are using the new format with hash at parts[1]
        # parts[0] = Zip, parts[1] = Hash.
        # So parts[2] might be the name if not comma found (e.g. if flatunzip fell back)
        # But wait, flatunzip now uses underscores to join parts, so the student name might be split across parts if it contained underscores (unlikely for names but possible)
        # However, comma is the strong signal.
        if len(parts) > 2:
            return parts[2]
            
    # Fallback to filename without extension
    return os.path.splitext(filename)[0]

def slugify_filename(text, fallback="submission", max_length=60):
    text = str(text or "").strip()
    text = "".join(
        char for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    if not text:
        text = fallback
    return text[:max_length].strip("_") or fallback

def get_submission_source_id(path):
    return hashlib.md5(os.path.abspath(path).encode("utf-8")).hexdigest()[:8]

def get_submission_output_slug(student_name, student_file_path, structured_feedback=None):
    base_name = student_name
    if structured_feedback:
        students = structured_feedback.get("students") or []
        first_student = students[0] if students else None
        if isinstance(first_student, dict):
            base_name = first_student.get("full_name") or first_student.get("name") or base_name
        elif first_student:
            base_name = str(first_student)

    return f"{slugify_filename(base_name)}_{get_submission_source_id(student_file_path)}"


def openrouter_extra_body(model_name):
    """Gemini Flash models on OpenRouter reason by default and cannot disable it; the
    minimal effort avoids paying for (and waiting on) reasoning tokens."""
    return {"reasoning": {"effort": "minimal"}} if "flash" in str(model_name).lower() else {}

def is_retryable_api_error(e):
    if isinstance(e, (openai.APIConnectionError, openai.RateLimitError)):
        return True
    if isinstance(e, openai.APIStatusError):
        return e.status_code != 400
    return False

@retry(stop=stop_after_attempt(5), wait=wait_fixed(2), retry=retry_if_exception(is_retryable_api_error), reraise=True)
def get_llm_response(client, model, messages):
    return client.chat.completions.create(
        model=model,
        messages=messages,
        extra_body=openrouter_extra_body(model),
    )

def _limit_images(images, max_images):
    if max_images is None or max_images <= 0:
        return images, 0
    return images[:max_images], max(0, len(images) - max_images)

def _image_extension(mime_type):
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
    }.get(mime_type, ".img")

def build_multimodal_user_content(prompt, images):
    if not images:
        return prompt
    content = [{"type": "text", "text": prompt}]
    for image in images:
        content.append({
            "type": "image_url",
            "image_url": {"url": image.data_url},
        })
    return content

def save_prompt_markdown(prompt_path, prompt, images=None):
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

def resolve_reference_file(session_folder, students_dir, ref_name):
    """
    Attempts to resolve the reference file path using several strategies:
    1. Exact path (relative or absolute).
    2. Converted markdown file in students directory (e.g. solutions_0.md).
    3. Heuristic auto-discovery in session folder if default name is used.
    """
    ref_name = ref_name.strip()
    if not ref_name:
        return None

    # 1. Exact match (or absolute path)
    if os.path.isabs(ref_name):
        if os.path.exists(ref_name):
            return ref_name
    else:
        path = os.path.join(session_folder, ref_name)
        if os.path.exists(path):
            return path

    # 2. Look for converted markdown in students_dir
    # jupyter2md truncates stem to 30 chars and adds _{i}.md
    base = os.path.splitext(os.path.basename(ref_name))[0]
    stem = base[:30]
    # Pattern: stem + underscore + digits + .md
    # We use a glob to find it
    md_pattern = os.path.join(students_dir, f"{stem}_*.md")
    matches = glob.glob(md_pattern)
    
    # Filter matches to ensure they follow the pattern (to avoid matching unrelated files that start similarly)
    # e.g. solutions_consultas vs solutions_0
    # The pattern from jupyter2md is strictly stem[:30] + "_" + digit + ".md"
    valid_matches = []
    for m in matches:
        filename = os.path.basename(m)
        # Regex to check format: stem_digits.md
        if re.match(re.escape(stem) + r"_\d+\.md$", filename):
            valid_matches.append(m)
    
    if valid_matches:
        print(f"Found converted reference file in students dir: {valid_matches[0]}")
        return valid_matches[0]

    # 3. Auto-discovery in session folder (heuristic) if ref_name is default
    if ref_name == "solutions.ipynb":
         notebooks = glob.glob(os.path.join(session_folder, '*.ipynb'))
         # Exclude files with 'student' in the name
         candidates = [nb for nb in notebooks if 'student' not in os.path.basename(nb).lower()]
         if candidates:
             # Pick the shortest one as a heuristic
             best = min(candidates, key=len)
             print(f"Auto-discovered reference notebook: {best}")
             return best
             
    return None

def estimate_prompt_tokens(text):
    try:
        import tiktoken
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text)), "tiktoken:cl100k_base"
    except Exception:
        return max(1, round(len(text) / 4)), "chars/4 estimate"

def get_file_priority(path, preferred_extensions):
    ext = os.path.splitext(path)[1].lower()
    try:
        return preferred_extensions.index(ext)
    except ValueError:
        return len(preferred_extensions)

def get_submission_group_key(path, students_dir):
    parent = os.path.dirname(path)
    if os.path.abspath(parent) != os.path.abspath(students_dir):
        return parent
    return get_student_name_from_path(path)

def select_preferred_student_files(student_files, students_dir, preferred_extensions):
    if not preferred_extensions:
        return student_files

    grouped = {}
    for path in student_files:
        grouped.setdefault(get_submission_group_key(path, students_dir), []).append(path)

    selected = []
    skipped = []
    for _, paths in grouped.items():
        best_priority = min(get_file_priority(path, preferred_extensions) for path in paths)
        current_selected = [path for path in paths if get_file_priority(path, preferred_extensions) == best_priority]
        current_skipped = [path for path in paths if get_file_priority(path, preferred_extensions) != best_priority]
        selected.extend(current_selected)
        skipped.extend(current_skipped)

    if skipped:
        print(f"Preferred-file selection skipped {len(skipped)} lower-priority file(s).")
        for path in skipped:
            kept = [p for p in selected if get_submission_group_key(p, students_dir) == get_submission_group_key(path, students_dir)]
            kept_names = "; ".join(os.path.basename(p) for p in kept)
            print(f"  Skipped {path} because preferred file(s) exist: {kept_names}")

    return sorted(selected)

def normalize_person_name(text):
    text = str(text or "").strip().lower()
    if "," in text:
        parts = [part.strip() for part in text.split(",", 1)]
        text = f"{parts[1]} {parts[0]}"
    text = "".join(
        char for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())

def name_order_variants(text):
    normalized = normalize_person_name(text)
    tokens = normalized.split()
    variants = [normalized]

    if len(tokens) >= 2:
        for split in range(1, len(tokens)):
            variants.append(" ".join(tokens[split:] + tokens[:split]))

    seen = set()
    unique_variants = []
    for variant in variants:
        if variant and variant not in seen:
            seen.add(variant)
            unique_variants.append(variant)
    return unique_variants

def levenshtein_distance(a, b):
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            insertion = current[j - 1] + 1
            deletion = previous[j] + 1
            substitution = previous[j - 1] + (char_a != char_b)
            current.append(min(insertion, deletion, substitution))
        previous = current
    return previous[-1]

def levenshtein_ratio(a, b):
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 100.0
    return 100.0 * (1.0 - levenshtein_distance(a, b) / max_len)

def common_prefix_len(a, b):
    count = 0
    for char_a, char_b in zip(a, b):
        if char_a != char_b:
            break
        count += 1
    return count

def token_name_similarity(query_key, candidate_key):
    query_tokens = query_key.split()
    candidate_tokens = candidate_key.split()
    if not query_tokens or not candidate_tokens:
        return 0.0

    token_scores = []
    exact_matches = 0
    for query_token in query_tokens:
        best_token_score = 0.0
        for candidate_token in candidate_tokens:
            if query_token == candidate_token:
                best_token_score = 1.0
                exact_matches += 1
                break

            prefix_len = common_prefix_len(query_token, candidate_token)
            min_len = min(len(query_token), len(candidate_token))
            if min_len >= 5 and prefix_len >= 4:
                best_token_score = max(best_token_score, 0.85)
            elif min_len >= 4 and prefix_len >= 3:
                best_token_score = max(best_token_score, 0.75)

        token_scores.append(best_token_score)

    if exact_matches == 0:
        return 0.0
    return 100.0 * sum(token_scores) / len(token_scores)

def find_moodle_row(student_name, row_by_name, fuzzy_threshold):
    keys = name_order_variants(student_name)
    for key in keys:
        if key in row_by_name:
            return row_by_name[key], "exact", 100.0

    if fuzzy_threshold is None or fuzzy_threshold <= 0:
        return None, None, 0.0

    best_key = None
    best_score = 0.0
    best_match_type = "fuzzy"
    for candidate_key in row_by_name:
        for key in keys:
            score = levenshtein_ratio(key, candidate_key)
            if score > best_score:
                best_key = candidate_key
                best_score = score
                best_match_type = "fuzzy"

            token_score = token_name_similarity(key, candidate_key)
            if token_score > best_score:
                best_key = candidate_key
                best_score = token_score
                best_match_type = "token-fuzzy"

    if best_key is not None and best_score >= fuzzy_threshold:
        return row_by_name[best_key], best_match_type, best_score
    return None, None, best_score

def extract_structured_feedback(response_text):
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
    pass

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

def format_moodle_mark(mark):
    if mark is None:
        return ""
    return f"{float(mark):.2f}".replace(".", ",")

def format_moodle_feedback(feedback, feedback_format):
    feedback = str(feedback or "").strip()
    if feedback_format == "plain":
        return feedback
    if feedback_format == "html":
        escaped = html.escape(feedback)
        return escaped.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    if feedback_format == "escaped-newlines":
        return feedback.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
    return feedback

def collect_feedback_yaml(feedback_dir):
    feedback_items = []
    for path in sorted(Path(feedback_dir).glob("*.y*ml")):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            print(f"Warning: ignoring non-dict feedback YAML: {path}")
            continue
        data["_path"] = str(path)
        feedback_items.append(data)
    return feedback_items

def feedback_to_moodle_csv(args):
    feedback_items = collect_feedback_yaml(args.feedback_dir)
    if not feedback_items:
        print(f"No YAML feedback files found in {args.feedback_dir}")
        return

    with open(args.marks_csv, "r", encoding=args.encoding, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    if not fieldnames:
        print(f"Could not read CSV header from {args.marks_csv}")
        return

    grade_col = resolve_moodle_column(fieldnames, args.grade_column, "grade")
    feedback_col = resolve_moodle_column(fieldnames, args.feedback_column, "feedback")
    name_col = resolve_moodle_column(fieldnames, args.name_column, "name")
    if not grade_col or not feedback_col or not name_col:
        return

    row_by_name = {normalize_person_name(row.get(name_col, "")): row for row in rows}
    matched = 0
    unmatched = []
    updated_row_ids = set()

    for item in feedback_items:
        mark = item.get("mark")
        feedback = format_moodle_feedback(item.get("feedback", ""), args.feedback_format)
        students = item.get("students", [])
        if isinstance(students, str):
            students = [{"full_name": students}]

        for student in students:
            if isinstance(student, dict):
                student_name = student.get("full_name") or student.get("name") or ""
            else:
                student_name = str(student)
            row, match_type, match_score = find_moodle_row(student_name, row_by_name, args.fuzzy_threshold)
            if row is None:
                unmatched.append((student_name, item.get("_path"), match_score))
                continue
            if args.skip_filled and (
                str(row.get(grade_col, "")).strip() or str(row.get(feedback_col, "")).strip()
            ):
                continue
            if match_type != "exact":
                print(
                    f"{match_type.capitalize()} matched '{student_name}' -> '{row.get(name_col, '')}' "
                    f"({match_score:.1f}/100)"
                )
            row[grade_col] = format_moodle_mark(mark)
            row[feedback_col] = feedback
            updated_row_ids.add(id(row))
            matched += 1

    if args.clear_timestamps:
        timestamp_cols = [
            resolve_moodle_column(fieldnames, args.submission_modified_column, "submission_modified", required=False),
            resolve_moodle_column(fieldnames, args.grade_modified_column, "grade_modified", required=False),
        ]
        for timestamp_col in timestamp_cols:
            if not timestamp_col:
                continue
            if timestamp_col not in fieldnames:
                print(f"Warning: timestamp column not found, cannot clear it: {timestamp_col}")
                continue
            for row in rows:
                if id(row) in updated_row_ids:
                    row[timestamp_col] = "-"

    output_rows = [row for row in rows if id(row) in updated_row_ids] if args.partial else rows

    with open(args.output, "w", encoding=args.encoding, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Wrote Moodle CSV: {args.output}")
    print(f"Updated {matched} student row(s) from {len(feedback_items)} feedback YAML file(s).")
    if args.partial:
        print(f"Partial CSV contains {len(output_rows)} row(s).")
    if unmatched:
        print(f"Unmatched students ({len(unmatched)}):")
        for name, path, score in unmatched:
            print(f"  {name} from {path} (best fuzzy score {score:.1f}/100)")

def moodle_csv_main(argv):
    parser = argparse.ArgumentParser(description="Compile structured YAML feedback into a Moodle marks CSV.")
    parser.add_argument("marks_csv", help="Moodle marks CSV to fill.")
    parser.add_argument("--feedback-dir", default="feedback", help="Directory containing feedback YAML files.")
    parser.add_argument("--output", default="marks_filled.csv", help="Output CSV path for Moodle upload.")
    parser.add_argument("--encoding", default="utf-8-sig", help="CSV encoding.")
    parser.add_argument("--name-column", default="Nom complet", help="Moodle CSV full-name column.")
    parser.add_argument("--grade-column", default="Qualificació", help="Moodle CSV grade column.")
    parser.add_argument("--feedback-column", default="Comentaris de retroacció.", help="Moodle CSV feedback comments column.")
    parser.add_argument("--submission-modified-column", default="Darrera modificació (tramesa)", help="Moodle CSV last-submission-modified column.")
    parser.add_argument("--grade-modified-column", default="Darrera modificació (qualificació)", help="Moodle CSV last-grade-modified column.")
    parser.add_argument("--feedback-format", choices=["plain", "html", "escaped-newlines"], default="plain", help="How to write multiline feedback comments in the CSV. Use 'html' if Moodle flattens raw newlines.")
    parser.add_argument("--partial", action="store_true", help="Write only rows that were updated from feedback YAML. Safer for repeated Moodle imports.")
    parser.add_argument("--skip-filled", action="store_true", help="Do not overwrite rows that already have a grade or feedback in the input Moodle CSV.")
    parser.add_argument("--clear-timestamps", action="store_true", help="Set Moodle last-modified timestamp columns to '-' for updated rows.")
    parser.add_argument("--fuzzy-threshold", type=float, default=70.0, help="Minimum normalized Levenshtein score (0-100) for fuzzy name matching. Use 0 to disable.")
    args = parser.parse_args(argv)
    feedback_to_moodle_csv(args)

def grade_submissions(session_folder, students_dir, args):
    """Grades all student submissions using an LLM."""
    if args.no_evaluate:
        print("Preparing grading prompts without calling the LLM...")
    else:
        print("Starting LLM-based grading...")
    load_project_dotenv()
    client = None
    if not args.no_evaluate:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            print("Error: OPENROUTER_API_KEY not found in .env file.")
            return
        if openai is None:
            print("Error: openai package not installed. Install it to grade submissions with an LLM.")
            return

        client = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )

    # Load Rubric
    rubric_path = os.path.join(session_folder, args.rubric)
    if not os.path.exists(rubric_path):
        print(f"Error: Rubric file not found at {rubric_path}")
        # If not found, try to look for a file starting with "Rubri" or "rubri" in the session folder
        rubrics = glob.glob(os.path.join(session_folder, '[Rr]ubri*.*'))
        if rubrics:
             rubric_path = rubrics[0]
             print(f"Found alternative rubric file: {rubric_path}")
        else:
             return
    print(f"Using rubric: {rubric_path}")
    with open(rubric_path, 'r', encoding='utf-8') as f:
        rubric = f.read()

    # Load Example
    example_path = os.path.join(session_folder, args.example)
    found_example= True
    if not os.path.exists(example_path):
        print(f"Warning: Example feedback file not found at {example_path}")
        # If not found, try to look for a file starting with "example" in the session folder
        examples = glob.glob(os.path.join(session_folder, '[Ee]xample*.*'))
        if examples:
             example_path = examples[0]
             print(f"Found alternative example file: {example_path}")
        else:
             found_example = False

    if found_example:
        print(f"Using example review: {example_path}")
        with open(example_path, 'r', encoding='utf-8') as f:
            example_review = f.read()
    else:
        print("No example feedback will be included in the prompt.")
        example_review = "[No example feedback provided]"

    markdown_config = parse_markdown_config(getattr(args, "markdown_config", None))
    prompts_dir = os.path.join(session_folder, 'prompts')

    reference_content = ""
    reference_images = []
    image_warnings = []
    if args.no_reference or not args.reference or args.reference.lower() in ("none", "null", "no"):
        print("No reference file will be included in the prompt.")
        reference_content = "[No reference content provided]"
    else:
        ref_paths = args.reference.split(';')
        for i, ref_path in enumerate(ref_paths):
            resolved_path = resolve_reference_file(session_folder, students_dir, ref_path)

            if not resolved_path:
                print(f"Error: Reference file '{ref_path}' not found.")
                reference_content = "[No reference content provided]"
                return

            print(f"Using reference file {i+1}: {resolved_path}")
            reference_assets_dir = os.path.join(prompts_dir, f"reference_{i + 1}_images")
            if args.include_images:
                clean_asset_dir(reference_assets_dir)
            extraction = utils.read_file_markdown(
                resolved_path,
                cleanup_html=not args.no_cleanup_html,
                image_output_dir=reference_assets_dir if args.include_images else None,
                image_reference_dir=prompts_dir if args.include_images else None,
                markdown_config=markdown_config,
                dedupe=not args.no_dedupe_images,
            )
            reference_content += f"\n\n--- Reference File {i+1} ({os.path.basename(resolved_path)}) ---\n{extraction.markdown}\n"
            reference_images.extend(extraction.images)
            image_warnings.extend(extraction.warnings)
            if args.include_images:
                print(f"Extracted {len(extraction.images)} image(s) from reference file {i+1}.")

    # Find Student Files
    single_file = getattr(args, "single_file", None)
    if single_file:
        student_files = [single_file]
        print(f"Using single submission file: {single_file}")
    else:
        student_files = []
        regex = re.compile(args.files_regex)

        for root, dirs, files in os.walk(students_dir):
            for file in files:
                if regex.match(file):
                    student_files.append(os.path.join(root, file))

        preferred_extensions = [
            ext.strip().lower() if ext.strip().startswith(".") else f".{ext.strip().lower()}"
            for ext in args.prefer_extensions.split(";")
            if ext.strip()
        ]
        student_files = select_preferred_student_files(student_files, students_dir, preferred_extensions)

    # Filter by student name if provided
    if args.student:
        student_filters = [s.strip() for s in args.student.split(';')]
        filtered_files = []
        matched_filters = set()
        for p in student_files:
            for s in student_filters:
                if s.lower() in os.path.basename(p).lower():
                    filtered_files.append(p)
                    matched_filters.add(s)
                    break
        student_files = filtered_files
        
        for s in student_filters:
            if s not in matched_filters:
                print(f"Warning: No file found matching filter '{s}'")

    print(f"Found {len(student_files)} files to grade matching regex and filter.")

    for student_file_path in student_files:
        student_name = get_student_name_from_path(student_file_path)
        prompt_slug = get_submission_output_slug(student_name, student_file_path)
        print(f"Grading submission for {student_name} ({os.path.basename(student_file_path)})...")

        prompt_assets_dir = os.path.join(prompts_dir, f"prompt_{prompt_slug}_images")
        if args.include_images:
            clean_asset_dir(prompt_assets_dir)
        extraction = utils.read_file_markdown(
            student_file_path,
            cleanup_html=not args.no_cleanup_html,
            image_output_dir=prompt_assets_dir if args.include_images else None,
            image_reference_dir=prompts_dir if args.include_images else None,
            markdown_config=markdown_config,
            dedupe=not args.no_dedupe_images,
        )
        # You need to grade the submission according to the rubric. Report the marks for each question and the total mark. The final feedback should be brief, just the marks for each exercise and any maximum a sentence for every exercise where points were deducted. The rubric may include not only the points for each question, but also some examples of specific reviews that should be given to the students for specific response.
        student_content = extraction.markdown
        student_images = extraction.images
        current_image_warnings = list(image_warnings)
        current_image_warnings.extend(extraction.warnings)
        if args.include_images:
            print(f"Extracted {len(student_images)} image(s) from student submission.")
        
        reference_section = ""
        if reference_content:
            reference_section = f"""
Here is the reference solution:

{reference_content}
--------------------------------
"""

        prompt = \
f"""You are a helpful assistant that grades University assignments. You are given the student submission (mandatory), a rubric (mandatory), an example feedback (optional), a reference solution (optional), and the images extracted from the submission (optional). You need to grade the submission according to the rubric. Provide the feedback in the same language as the ones the student(s) used to answer the questions.

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
        images_for_model = []
        if args.include_images:
            images_for_model = reference_images + student_images
            if not args.no_dedupe_images:
                images_for_model, duplicate_count = utils.dedupe_images(images_for_model)
                if duplicate_count:
                    current_image_warnings.append(f"Removed {duplicate_count} duplicate image(s) across reference and student files.")
            images_for_model, omitted_count = _limit_images(images_for_model, args.max_images)
            if omitted_count:
                current_image_warnings.append(f"Omitted {omitted_count} image(s) because --max-images is {args.max_images}.")
            if not images_for_model and (student_images or reference_images):
                prompt += "\nImage extraction was requested, but no supported images were attached after filtering.\n"

        estimated_tokens, token_method = estimate_prompt_tokens(prompt)
        print(
            f"Prompt size for {student_name}: {len(prompt):,} chars, "
            f"~{estimated_tokens:,} tokens ({token_method})."
        )
        if args.include_images:
            print(f"Sending {len(images_for_model)} image(s) to the LLM for {student_name}.")
            for warning in current_image_warnings:
                print(f"Image warning: {warning}")
        if args.keep_prompt:
            os.makedirs(prompts_dir, exist_ok=True)
            prompt_file = os.path.join(prompts_dir, f"prompt_{prompt_slug}.md")
            save_prompt_markdown(prompt_file, prompt, images_for_model if args.include_images else [])
            print(f"Prompt for {student_name} saved to {prompt_file}")

        if args.no_evaluate:
            print(f"Skipping LLM evaluation for {student_name} because --no-evaluate was set.")
            continue

        try:
            response = get_llm_response(
                client,
                args.model,
                [
                    {"role": "system", "content": "You are a teaching assistant for a data science course."},
                    {"role": "user", "content": build_multimodal_user_content(prompt, images_for_model)},
                ]
            )
            feedback = response.choices[0].message.content
            structured_feedback = extract_structured_feedback(feedback)
            structured_feedback["submission_file"] = student_file_path
            structured_feedback["source_id"] = get_submission_source_id(student_file_path)
            feedback_slug = get_submission_output_slug(student_name, student_file_path, structured_feedback)

            feedback_dir = os.path.join(session_folder, 'feedback')
            os.makedirs(feedback_dir, exist_ok=True)
            feedback_file = os.path.join(feedback_dir, f"feedback_{feedback_slug}.yaml")
            write_feedback_yaml(feedback_file, structured_feedback)
            print(f"Feedback for {student_name} saved to {feedback_file}")

        except Exception as e:
            print(f"An error occurred while grading {student_name}: {e}")
            continue

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "exam-open":
        from .exam_open import main as exam_open_main
        exam_open_main(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] in ("exam-open-test", "test-open"):
        from .exam_open import smoke_main
        smoke_main(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] in ("moodle-csv", "feedback-csv"):
        moodle_csv_main(sys.argv[2:])
        return

    parser = argparse.ArgumentParser(description="Automate the correction pipeline for assignment submissions.")
    parser.add_argument("session_folder", help="The path to the assignment/session folder, or a single submission file.")
    parser.add_argument("--no-unzip", action="store_true", help="Skip the unzipping step.")
    parser.add_argument("--no-convert", action="store_true", help="Skip the batch notebook to markdown conversion step.")
    parser.add_argument("--no-grade", action="store_true", help="Skip the LLM-based grading step entirely, including prompt preparation.")
    parser.add_argument("--no-evaluate", action="store_true", help="Prepare inputs, print token estimates, and save prompts when requested, but do not call the LLM.")
    parser.add_argument("--model", default="google/gemini-3.1-pro-preview", help="The model to use for grading on OpenRouter.")
    parser.add_argument("--student", help="Filter to grade only a specific student's submission (part of the filename). Can be a semicolon-separated list.")
    
    # New arguments for generalization
    parser.add_argument("--rubric", default="rubric.txt", help="Name of the rubric file in the session folder.")
    parser.add_argument("--example", default="example.txt", help="Name of the example feedback file in the session folder.")
    parser.add_argument("--reference", default="", help="Name or path of the reference solution file(s). Multiple files can be separated by semicolon (;). Empty by default.")
    parser.add_argument("--no-reference", action="store_true", help="Do not include any reference solution in the grading prompt.")
    parser.add_argument("--files-regex", default=r".*\.ipynb$", help="Regex to match student files to grade.")
    parser.add_argument("--prefer-extensions", default=".ipynb;.html", help="Semicolon-separated extension priority for duplicate submissions in the same folder. Use an empty string to disable.")
    parser.add_argument("--remove-files-regex", help="Regex to remove specific files from the students directory after unzipping.")
    parser.add_argument("--keep-prompt", action="store_true", help="Save the grading prompt to a file for debugging.")
    parser.add_argument("--no-cleanup-html", "--not-cleanup-html", dest="no_cleanup_html", action="store_true", help="Disable removal of HTML style/script/image artifacts from notebooks, markdown, and HTML files.")
    parser.add_argument("--include-images", action="store_true", help="Extract images from supported files and attach them to the LLM request.")
    parser.add_argument("--no-dedupe-images", action="store_true", help="Do not remove duplicate extracted images before sending them to the LLM.")
    parser.add_argument("--max-images", type=int, default=20, help="Maximum extracted images to attach per LLM request. Use 0 for no limit.")
    parser.add_argument("--markdown-config", help="JSON object or path to a JSON file with document-to-Markdown converter options. For PDFs these are passed to pymupdf4llm.to_markdown.")
    parser.add_argument("--students-dir", help="Directory containing already unpacked student submissions. Defaults to <session_folder>/students.")
    parser.add_argument("--extract-nested-zips", action="store_true", help="Extract zip files found inside the students directory before conversion/grading.")
    parser.add_argument("--output-dir", help="Output/session folder for single-file inputs. Defaults to the input file's parent folder.")

    args = parser.parse_args()

    input_path = os.path.abspath(args.session_folder)
    single_file = os.path.isfile(input_path)
    if single_file:
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
        print(f"Removing files matching regex: {args.remove_files_regex}")
        remove_regex = re.compile(args.remove_files_regex)
        count_removed = 0
        for root, dirs, files in os.walk(students_dir):
            for file in files:
                if remove_regex.match(file):
                    try:
                        os.remove(os.path.join(root, file))
                        count_removed += 1
                    except OSError as e:
                        print(f"Error removing {file}: {e}")
        print(f"Removed {count_removed} files.")

    if args.extract_nested_zips:
        extract_nested_zips(students_dir)

    if not args.no_convert:
        # We still support batch conversion for .ipynb files as it's useful for manual inspection
        convert_notebooks_batch(students_dir)
    
    if not args.no_grade:
        grade_submissions(session_folder, students_dir, args)

    print("Pipeline finished.")

if __name__ == "__main__":
    main()
