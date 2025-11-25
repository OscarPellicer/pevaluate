'''
This script automates the correction pipeline for JupyterLab sessions.
Usage:
    1) Install the dependencies: openai, dotenv, tenacity
    2) Set the OPENROUTER_API_KEY in the .env file.
    3) Make sure the session folder contains the following files:
        <session_folder>/grupo_l1.zip : as downloaded from Moodle, with option "Download all files" > "Include subfolders". All zips will be flatunzipped.
        <session_folder>/grupo_l2.zip
        ...
        <session_folder>/notebook.ipynb : the reference notebook: the name must not contain "student"
        <session_folder>/example.txt : an example of feedback, name must be exactly "example.txt".
        <session_folder>/Rubrica.txt : the rubric for the session, containing the points for each question. Name must be exactly "Rubrica.txt".
    4) Run the script:
        python autocorrect.py <session_folder>
    5) Run the script for some specific students:
        python autocorrect.py <session_folder> --student <student_name>
    6) Run the script wihtout unzipping, converting or grading (which would do nothing):
        python autocorrect.py <session_folder> --no-unzip --no-convert --no-grade
'''

import argparse
import os
import glob
import shutil
from . import flatunzip
from . import jupyter2md
import openai
from pathlib import Path
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception

def find_reference_notebook(session_folder):
    """Finds the reference notebook in the session folder."""
    notebooks = glob.glob(os.path.join(session_folder, '*.ipynb'))
    # Simple heuristic: the one with the shortest name, not containing "student"
    # and not inside the students folder.
    notebooks = [nb for nb in notebooks if 'student' not in nb.lower()]
    if not notebooks:
        return None
    ref_notebook = min(notebooks, key=len)
    print(f"Found reference notebook: {ref_notebook}")
    return ref_notebook

def unzip_submissions(session_folder, students_dir):
    """Unzips all student submissions."""
    print("Unzipping student submissions...")
    zip_files = glob.glob(os.path.join(session_folder, '*.zip'))
    if not zip_files:
        print("No zip files found in the session folder.")
        return

    os.makedirs(students_dir, exist_ok=True)
    for zip_file in zip_files:
        print(f"Unzipping {zip_file}...")
        flatunzip.unpack_and_flatten(zip_file, students_dir)
    print("Unzipping completed.")

def copy_reference_notebook(session_folder, students_dir):
    """Copies the reference notebook to the students' directory."""
    print("Copying reference notebook...")
    reference_notebook = find_reference_notebook(session_folder)
    if reference_notebook:
        print(f"Found reference notebook: {reference_notebook}")
        shutil.copy(reference_notebook, students_dir)
        print("Reference notebook copied.")
    else:
        print("Warning: Reference notebook not found.")

def convert_notebooks(students_dir):
    """Converts notebooks to markdown."""
    print("Converting notebooks to markdown...")
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
    # Assuming name is between the first and second underscore, a bit fragile.
    parts = filename.split('_')
    if len(parts) > 2:
        return parts[1]
    return "unknown_student"


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

def grade_submissions(session_folder, students_dir, model, student_filter=None):
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

    rubric_file = glob.glob(os.path.join(session_folder, 'Rúbrica*.txt'))
    if not rubric_file:
        print("Error: Rubric file not found.")
        return
    rubric_file = rubric_file[0]
    print(f"Using rubric: {rubric_file}")

    with open(rubric_file, 'r', encoding='utf-8') as f:
        rubric = f.read()

    reference_notebook_path = find_reference_notebook(session_folder)
    if not reference_notebook_path:
        print("Error: Reference notebook not found for grading.")
        return
    
    # Find the converted reference notebook, allowing for suffixes added by jupyter2md.py
    ref_notebook_name = os.path.basename(reference_notebook_path).replace('.ipynb', '')
    
    # Search for the markdown file that starts with the reference notebook name
    ref_notebook_md_paths = glob.glob(os.path.join(students_dir, f'{ref_notebook_name}*.md'))

    if not ref_notebook_md_paths:
        print(f"Error: Converted reference notebook starting with '{ref_notebook_name}' not found in '{students_dir}'")
        return
    
    ref_notebook_md_path = ref_notebook_md_paths[0] # Take the first match
    print(f"Found converted reference notebook: {ref_notebook_md_path}")
        
    with open(ref_notebook_md_path, 'r', encoding='utf-8') as f:
        reference_notebook_md = f.read()

    # Read the example review
    with open(os.path.join(session_folder, 'example.txt'), 'r', encoding='utf-8') as f:
        example_review = f.read()
    print(f"Using example review:\n{example_review}")

    student_notebooks_md = glob.glob(os.path.join(students_dir, '*.md'))
    # Exclude the reference notebook from the list of student notebooks
    student_notebooks_md = [p for p in student_notebooks_md if os.path.basename(p) != os.path.basename(ref_notebook_md_path)]

    if student_filter:
        if isinstance(student_filter, str):
            student_filter = [student_filter]
        
        matched_filters = set()
        filtered_notebooks = []
        for p in student_notebooks_md:
            for s in student_filter:
                if s.lower() in os.path.basename(p).lower():
                    filtered_notebooks.append(p)
                    matched_filters.add(s)
                    break 
        
        student_notebooks_md = filtered_notebooks

        for s in student_filter:
            if s not in matched_filters:
                print(f"Warning: No notebook found matching filter '{s}'")
    
    print(f"Found {len(student_notebooks_md)} notebooks to grade matching filter.")

    for student_md_path in student_notebooks_md:
        student_name = get_student_name_from_path(student_md_path)
        print(f"Grading submission for {student_name}...")
        
        with open(student_md_path, 'r', encoding='utf-8') as f:
            student_notebook_md = f.read()
        
        prompt = f"""You are a helpful assistant that grades the notebooks of the students of the course "Analítica de Datos en Salud" of the University of Valencia. You are given a rubric, a reference notebook and a notebook to grade. The rubric includes not only the points for each question, but also some examples of specific reviews that should be given to the students for specific response. You need to grade the notebook according to the rubric and review the exercises from the students. Report the marks for each question and the total mark for the notebook scaled to 10 points. The final feedback should be extremely brief, just the marks for each exercise and any maximum a setence for every exercise where points were deducted. Provide the feedback in the same language as the ones the students used to answer the questions.

Here is the rubric:
---
{rubric}
---

Here is the reference notebook:
---
{reference_notebook_md}
---

Here is the student's notebook to grade:
---
{student_notebook_md}
---

Here is an example of review (note that the exercises might be completely different, this is just an example of the expected format):
---
{example_review}
---

Please provide the feedback now.
"""

        try:
            response = get_llm_response(
                client,
                model,
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

        except openai.APIConnectionError as e:
            print(f"Connection error for {student_name}: Could not connect to OpenRouter. Please check your network connection.")
            print(f"Underlying error: {e.__cause__}")
            continue
        except openai.RateLimitError as e:
            print(f"Rate limit exceeded for {student_name}. Please check your OpenRouter plan and usage limits.")
            continue
        except openai.AuthenticationError as e:
            print(f"Authentication error for {student_name}. Please check your OPENROUTER_API_KEY in the .env file.")
            continue
        except openai.APIStatusError as e:
            print(f"OpenRouter API error for {student_name} (Status code: {e.status_code}):")
            try:
                # Try to print the JSON response for better readability
                print(e.response.json())
            except:
                # Fallback to raw text if it's not JSON
                print(e.response.text)
            continue
        except Exception as e:
            print(f"An unexpected error occurred while grading {student_name}: {e}")
            continue

def main():
    parser = argparse.ArgumentParser(description="Automate the correction pipeline for lab sessions.")
    parser.add_argument("session_folder", help="The path to the lab session folder (e.g., 'P1 - SADC').")
    parser.add_argument("--no-unzip", action="store_true", help="Skip the unzipping step.")
    parser.add_argument("--no-convert", action="store_true", help="Skip the notebook to markdown conversion step.")
    parser.add_argument("--no-grade", action="store_true", help="Skip the LLM-based grading step.")
    parser.add_argument("--model", default="google/gemini-3-pro-preview", help="The model to use for grading on OpenRouter.")
    parser.add_argument("--student", help="Filter to grade only a specific student's notebook (a part of the filename). Can be a semicolon-separated list.")

    args = parser.parse_args()

    session_folder = args.session_folder
    students_dir = os.path.join(session_folder, 'students')
    
    student_filter = args.student
    if student_filter:
        student_filter = [s.strip() for s in student_filter.split(';')]

    if not args.no_unzip:
        unzip_submissions(session_folder, students_dir)
        copy_reference_notebook(session_folder, students_dir)

    if not args.no_convert:
        convert_notebooks(students_dir)
    
    if not args.no_grade:
        grade_submissions(session_folder, students_dir, args.model, student_filter)

    print("Pipeline finished.")

if __name__ == "__main__":
    main()
