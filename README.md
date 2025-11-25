# Autocorrect

This tool automates the correction pipeline for JupyterLab sessions. It unzips student submissions, converts notebooks to Markdown, and uses an LLM (via OpenRouter) to grade them based on a provided rubric.

## Installation

It is recommended to use the `autotestia2` conda environment for this project.

```bash
conda activate autotestia2
```

To install the library:

```bash
pip install .
```

## Setup

1.  Create a `.env` file in the directory where you run the script (or ensure it's loaded) with your OpenRouter API key:

    ```env
    OPENROUTER_API_KEY=your_api_key_here
    ```

2.  Prepare your session folder structure:

    ```
    <session_folder>/
    ├── grupo_l1.zip          # Student submissions zip (downloaded with "Include subfolders")
    ├── grupo_l2.zip          # More student submissions...
    ├── notebook.ipynb        # The reference notebook (name must NOT contain "student")
    ├── example.txt           # Example feedback (must be exactly "example.txt")
    └── Rubrica.txt           # Grading rubric (must be exactly "Rubrica.txt")
    ```

## Usage

Run the correction pipeline:

```bash
autocorrect <session_folder>
```

### Options

-   **Grade specific student(s):**
    ```bash
    autocorrect <session_folder> --student "Student Name"
    ```
    Multiple students can be separated by semicolons.

-   **Skip steps:**
    ```bash
    autocorrect <session_folder> --no-unzip
    autocorrect <session_folder> --no-convert
    autocorrect <session_folder> --no-grade
    ```

-   **Select LLM model:**
    ```bash
    autocorrect <session_folder> --model "google/gemini-pro"
    ```
    Default model is `google/gemini-3-pro-preview`.

## Components

-   `src/autocorrect/cli.py`: Main script that orchestrates the pipeline.
-   `src/autocorrect/flatunzip.py`: Unzips submissions and flattens directory structures.
-   `src/autocorrect/jupyter2md.py`: Converts Jupyter notebooks to Markdown.

