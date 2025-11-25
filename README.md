# Autocorrect

This tool automates the correction pipeline for grading student submissions. It supports unzipping submissions, converting/reading various file formats (Jupyter Notebooks, PDF, Word, Text, Code), and using an LLM (via OpenRouter) to grade them based on a provided rubric.

## Installation

It is recommended to use the `autotestia2` conda environment for this project.

```bash
conda activate autotestia2
```

To install the library in editable mode (recommended for development):

```bash
pip install -e .
```

## Setup

1.  Create a `.env` file with your OpenRouter API key:

    ```env
    OPENROUTER_API_KEY=your_api_key_here
    ```

2.  Prepare your session folder structure.

## Usage

Run the correction pipeline:

```bash
autocorrect <session_folder>
```

### Arguments & Options

| Argument | Description | Default |
| :--- | :--- | :--- |
| `session_folder` | Path to the lab session folder. | **Required** |
| `--model` | The LLM model to use via OpenRouter. | `google/gemini-3-pro-preview` |
| `--rubric` | Name of the rubric file in the session folder. | `rubric.txt` |
| `--example` | Name of the example feedback file in the session folder. | `example.txt` |
| `--reference` | Name or path of reference solution file(s). Multiple files separated by `;`. | `solutions.ipynb` |
| `--files-regex` | Regex to select which student files to grade. | `.*\.ipynb$` |
| `--remove-files-regex`| Regex to delete files immediately after unzipping (e.g., cleanup). | `None` |
| `--student` | Filter to grade only specific student(s) (semicolon-separated). | `None` (all) |
| `--keep-prompt` | Save the generated LLM prompt to `prompts/` for debugging. | `False` |
| `--no-unzip` | Skip the unzipping step. | `False` |
| `--no-convert` | Skip the batch `.ipynb` to `.md` conversion step. | `False` |
| `--no-grade` | Skip the LLM grading step. | `False` |

## Examples

### Subject 1: Analítica de Datos en Salud (ADS)
**Scenario:** Student submissions are Jupyter Notebooks.

*   **Structure:**
    *   `P1 - SADC/`
        *   `submissions.zip` (Standard Moodle export)
        *   `P1_ADS.ipynb` (Reference solution)
        *   `rubric.txt`
        *   `example.txt`
*   **Command:**
    ```bash
    autocorrect "P1 - SADC" \
      --reference "P1_ADS.ipynb" \
      --files-regex ".*\.ipynb$" \
      --model "google/gemini-3-pro-preview"
    ```

### Subject 2: Sistemas Informáticos (MIB) - BD Practica
**Scenario:** Student submissions are mixed text, SQL, Word, and PDF files. We need to remove Moodle's `timestamp.txt` files and use multiple reference files.

*   **Structure:**
    *   `bd_practica/`
        *   `Practica de bases de datos.zip`
        *   `enunciado.md`
        *   `soluciones_definicion.md`
        *   `soluciones_consultas.md`
        *   `rubric.txt`
        *   `example.txt`
*   **Command:**
    ```bash
    autocorrect "path/to/bd_practica" \
      --files-regex ".*\.(txt|sql|docx|pdf)$" \
      --remove-files-regex ".*timestamp\.txt$" \
      --reference "enunciado.md;soluciones_definicion.md;soluciones_consultas.md" \
      --keep-prompt \
      --model "google/gemini-3-pro-preview"
    ```

## Components

-   `src/autocorrect/cli.py`: Main entry point. Handles arguments, unzipping cleanup, and orchestration.
-   `src/autocorrect/flatunzip.py`: Unzips submissions. **Features:**
    *   Sanitizes filenames to ASCII.
    *   Hashes path components to ensure unique, short filenames (Windows-friendly).
    *   Preserves student names via heuristic (looking for commas in path).
    *   Aggressively truncates filenames to avoid `MAX_PATH` issues.
-   `src/autocorrect/utils.py`: Reads content from `.ipynb`, `.docx`, `.pdf`, and text files.
-   `src/autocorrect/jupyter2md.py`: Batch converter for notebooks (uses `nbconvert`).
