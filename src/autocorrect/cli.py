'''
This script automates the correction pipeline for JupyterLab sessions.
Usage:
    1) Install the dependencies: openai, dotenv, tenacity, python-docx, pypdf
    2) Set the OPENROUTER_API_KEY in the .env file.
    3) Make sure the session folder contains the required files (rubric, example, reference).
    4) Run the script: autocorrect <session_folder>
'''

import argparse
import os
import glob
import shutil
import re
from . import flatunzip
from . import jupyter2md
from . import utils
import openai
from pathlib import Path
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception

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
    if not os.path.exists(students_dir):
        print(f"Students directory '{students_dir}' not found. Skipping conversion.")
        return
    
    # Clean up existing .md files to avoid duplicates from previous runs with different naming
    for md_file in glob.glob(os.path.join(students_dir, '*.md')):
        try:
            os.remove(md_file)
        except OSError:
            pass

    jupyter2md.convert_notebooks(Path(students_dir))
    print("Conversion to markdown completed.")

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
    )

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

def grade_submissions(session_folder, students_dir, args):
    """Grades all student submissions using an LLM."""
    print("Starting LLM-based grading...")
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("Error: OPENROUTER_API_KEY not found in .env file.")
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
        rubrics = glob.glob(os.path.join(session_folder, '[Rr]ubri*.txt'))
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
    if not os.path.exists(example_path):
        print(f"Error: Example feedback file not found at {example_path}")
        # If not found, try to look for a file starting with "example" in the session folder
        examples = glob.glob(os.path.join(session_folder, '[Ee]xample*.txt'))
        if examples:
             example_path = examples[0]
             print(f"Found alternative example file: {example_path}")
        else:
             return
    print(f"Using example review: {example_path}")
    with open(example_path, 'r', encoding='utf-8') as f:
        example_review = f.read()

    # Load Reference(s)
    # Check if absolute path or relative to session folder
    ref_paths = args.reference.split(';')
    reference_content = ""
    
    for i, ref_path in enumerate(ref_paths):
        resolved_path = resolve_reference_file(session_folder, students_dir, ref_path)
        
        if not resolved_path:
            print(f"Error: Reference file '{ref_path}' not found.")
            # We continue to allow other references or fail?
            # Given that we might need all references, failing is safer if one is missing.
            # But let's print all missing ones first? 
            # For now, let's return to avoid grading with missing context.
            return
        
        print(f"Using reference file {i+1}: {resolved_path}")
        content = utils.read_file_content(resolved_path)
        reference_content += f"\n\n--- Reference File {i+1} ({os.path.basename(resolved_path)}) ---\n{content}\n"

    # Find Student Files
    student_files = []
    regex = re.compile(args.files_regex)
    
    for root, dirs, files in os.walk(students_dir):
        for file in files:
            if regex.match(file):
                student_files.append(os.path.join(root, file))

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
        # Skip if it's the reference file (unlikely if in students dir, but good safety)
        if os.path.abspath(student_file_path) == os.path.abspath(ref_path):
            continue

        student_name = get_student_name_from_path(student_file_path)
        print(f"Grading submission for {student_name} ({os.path.basename(student_file_path)})...")
        
        student_content = utils.read_file_content(student_file_path)
        
        prompt = \
f"""You are a helpful assistant that grades the exercises of the students of the course "Analítica de Datos en Salud" of the University of Valencia. You are given a rubric, a reference solution and a student submission to grade. The rubric includes not only the points for each question, but also some examples of specific reviews that should be given to the students for specific response. You need to grade the submission according to the rubric. Report the marks for each question and the total mark scaled to 10 points. The final feedback should be extremely brief, just the marks for each exercise and any maximum a setence for every exercise where points were deducted. Provide the feedback in the same language as the ones the students used to answer the questions.

Here is the rubric:

{rubric}
--------------------------------

Here is the reference solution:

{reference_content}
--------------------------------

Here is the student's submission to grade:

{student_content}
--------------------------------

Here is an example of review (note that the exercises might be completely different, this is just an example of the expected format):

{example_review}
--------------------------------

Please provide the feedback now.
"""
        if args.keep_prompt:
            prompts_dir = os.path.join(session_folder, 'prompts')
            os.makedirs(prompts_dir, exist_ok=True)
            prompt_file = os.path.join(prompts_dir, f"prompt_{student_name}.txt")
            with open(prompt_file, 'w', encoding='utf-8') as f:
                f.write(prompt)
            print(f"Prompt for {student_name} saved to {prompt_file}")

        try:
            response = get_llm_response(
                client,
                args.model,
                [
                    {"role": "system", "content": "You are a teaching assistant for a data science course."},
                    {"role": "user", "content": prompt},
                ]
            )
            feedback = response.choices[0].message.content

            feedback_dir = os.path.join(session_folder, 'feedback')
            os.makedirs(feedback_dir, exist_ok=True)
            feedback_file = os.path.join(feedback_dir, f"feedback_{student_name}.md")
            with open(feedback_file, 'w', encoding='utf-8') as f:
                f.write(feedback)
            print(f"Feedback for {student_name} saved to {feedback_file}")

        except Exception as e:
            print(f"An error occurred while grading {student_name}: {e}")
            continue

def main():
    parser = argparse.ArgumentParser(description="Automate the correction pipeline for lab sessions.")
    parser.add_argument("session_folder", help="The path to the lab session folder (e.g., 'P1 - SADC').")
    parser.add_argument("--no-unzip", action="store_true", help="Skip the unzipping step.")
    parser.add_argument("--no-convert", action="store_true", help="Skip the batch notebook to markdown conversion step.")
    parser.add_argument("--no-grade", action="store_true", help="Skip the LLM-based grading step.")
    parser.add_argument("--model", default="google/gemini-3-pro-preview", help="The model to use for grading on OpenRouter.")
    parser.add_argument("--student", help="Filter to grade only a specific student's submission (part of the filename). Can be a semicolon-separated list.")
    
    # New arguments for generalization
    parser.add_argument("--rubric", default="rubric.txt", help="Name of the rubric file in the session folder.")
    parser.add_argument("--example", default="example.txt", help="Name of the example feedback file in the session folder.")
    parser.add_argument("--reference", default="solutions.ipynb", help="Name or path of the reference solution file(s). Multiple files can be separated by semicolon (;).")
    parser.add_argument("--files-regex", default=r".*\.ipynb$", help="Regex to match student files to grade.")
    parser.add_argument("--remove-files-regex", help="Regex to remove specific files from the students directory after unzipping.")
    parser.add_argument("--keep-prompt", action="store_true", help="Save the grading prompt to a file for debugging.")

    args = parser.parse_args()

    session_folder = args.session_folder
    students_dir = os.path.join(session_folder, 'students')
    
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

    if not args.no_convert:
        # We still support batch conversion for .ipynb files as it's useful for manual inspection
        convert_notebooks_batch(students_dir)
    
    if not args.no_grade:
        grade_submissions(session_folder, students_dir, args)

    print("Pipeline finished.")

if __name__ == "__main__":
    main()
