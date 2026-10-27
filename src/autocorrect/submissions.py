"""Student submissions of a lab session: unzip the Moodle downloads, find each submission's files,
the student who submitted them and the reference solution."""
import glob
import hashlib
import os
import re
import shutil
import unicodedata
import zipfile
from pathlib import Path

from . import flatunzip

try:
    from . import jupyter2md
except ImportError:
    jupyter2md = None


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
        # On Windows, rmtree fails if a file is open or locked: then empty it file by file.
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


def remove_matching_files(students_dir, pattern):
    """Delete the files under ``students_dir`` whose name matches the regex ``pattern``."""
    print(f"Removing files matching regex: {pattern}")
    remove_regex = re.compile(pattern)
    count_removed = 0
    for root, _, files in os.walk(students_dir):
        for file in files:
            if remove_regex.match(file):
                try:
                    os.remove(os.path.join(root, file))
                    count_removed += 1
                except OSError as e:
                    print(f"Error removing {file}: {e}")
    print(f"Removed {count_removed} files.")


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


def _index_entry(path):
    return flatunzip.load_submissions_index(os.path.dirname(os.path.abspath(path))).get(os.path.basename(path), {})


def get_student_name_from_path(path):
    """Student name of a submission file: from the unzip index when available, else guessed from
    the file name (the part with a comma, as in Moodle's "Surname, Name", or the third
    ``_``-separated part of flatunzip's ``Zip_Hash_Student_File`` names)."""
    entry = _index_entry(path)
    if entry.get("student"):
        return entry["student"]
    filename = os.path.basename(path)
    parts = filename.split('_')
    for part in parts:
        if ',' in part:
            return part
    if len(parts) > 2:
        return parts[2]
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
    """``<name>_<hash of the path>``, with the first student listed by the grader if any."""
    base_name = student_name
    if structured_feedback:
        students = structured_feedback.get("students") or []
        first_student = students[0] if students else None
        if isinstance(first_student, dict):
            base_name = first_student.get("full_name") or first_student.get("name") or base_name
        elif first_student:
            base_name = str(first_student)

    return f"{slugify_filename(base_name)}_{get_submission_source_id(student_file_path)}"


def get_file_priority(path, preferred_extensions):
    ext = os.path.splitext(path)[1].lower()
    try:
        return preferred_extensions.index(ext)
    except ValueError:
        return len(preferred_extensions)


def get_submission_group_key(path, students_dir):
    entry = _index_entry(path)
    if entry.get("submission"):
        return entry["submission"]
    parent = os.path.dirname(path)
    if os.path.abspath(parent) != os.path.abspath(students_dir):
        return parent
    return get_student_name_from_path(path)


def select_preferred_student_files(student_files, students_dir, preferred_extensions):
    """Within each submission, keep only the files with the most preferred extension."""
    if not preferred_extensions:
        return student_files

    grouped = {}
    for path in student_files:
        grouped.setdefault(get_submission_group_key(path, students_dir), []).append(path)

    selected = []
    skipped = []
    for paths in grouped.values():
        best_priority = min(get_file_priority(path, preferred_extensions) for path in paths)
        for path in paths:
            (selected if get_file_priority(path, preferred_extensions) == best_priority else skipped).append(path)

    if skipped:
        print(f"Preferred-file selection skipped {len(skipped)} lower-priority file(s).")
        for path in skipped:
            kept = [p for p in selected if get_submission_group_key(p, students_dir) == get_submission_group_key(path, students_dir)]
            kept_names = "; ".join(os.path.basename(p) for p in kept)
            print(f"  Skipped {path} because preferred file(s) exist: {kept_names}")

    return sorted(selected)


def parse_extensions(value):
    """``".ipynb;html"`` -> ``[".ipynb", ".html"]``."""
    return [
        ext.strip().lower() if ext.strip().startswith(".") else f".{ext.strip().lower()}"
        for ext in value.split(";")
        if ext.strip()
    ]


def find_student_files(students_dir, files_regex, prefer_extensions):
    """Files under ``students_dir`` whose name matches ``files_regex``, one format per submission
    (see :func:`select_preferred_student_files`)."""
    regex = re.compile(files_regex)
    student_files = []
    for root, _, files in os.walk(students_dir):
        for file in files:
            if regex.match(file):
                student_files.append(os.path.join(root, file))
    return select_preferred_student_files(student_files, students_dir, parse_extensions(prefer_extensions))


def filter_by_student(student_files, student_filter):
    """Files whose name contains one of the ``;``-separated (case-insensitive) filters."""
    student_filters = [s.strip() for s in student_filter.split(';')]
    filtered_files = []
    matched_filters = set()
    for p in student_files:
        for s in student_filters:
            if s.lower() in os.path.basename(p).lower():
                filtered_files.append(p)
                matched_filters.add(s)
                break
    for s in student_filters:
        if s not in matched_filters:
            print(f"Warning: No file found matching filter '{s}'")
    return filtered_files


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

    # 2. Converted markdown in students_dir: jupyter2md writes <stem[:30]>_<i>.md
    stem = os.path.splitext(os.path.basename(ref_name))[0][:30]
    valid_matches = [
        m for m in glob.glob(os.path.join(students_dir, f"{stem}_*.md"))
        if re.match(re.escape(stem) + r"_\d+\.md$", os.path.basename(m))
    ]
    if valid_matches:
        print(f"Found converted reference file in students dir: {valid_matches[0]}")
        return valid_matches[0]

    # 3. Auto-discovery in session folder (heuristic) if ref_name is default
    if ref_name == "solutions.ipynb":
        notebooks = glob.glob(os.path.join(session_folder, '*.ipynb'))
        candidates = [nb for nb in notebooks if 'student' not in os.path.basename(nb).lower()]
        if candidates:
            best = min(candidates, key=len)  # the shortest name, as a heuristic
            print(f"Auto-discovered reference notebook: {best}")
            return best

    return None
