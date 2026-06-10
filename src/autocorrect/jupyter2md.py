from pathlib import Path
import argparse
import nbformat
from nbconvert import MarkdownExporter
from .utils import sanitize_html_artifacts


def convert_notebooks(input_path: Path):
    """
    Converts all .ipynb files in a given directory to .md files using jupyter nbconvert.
    """
    if not input_path.is_dir():
        print(f"Error: The provided path '{input_path}' is not a directory.")
        return
        
    notebooks = list(input_path.rglob('*.ipynb'))

    if not notebooks:
        print(f"No Jupyter notebooks found in '{input_path}'.")
        return

    print(f"Found {len(notebooks)} notebooks in '{input_path}'. Starting conversion...")

    for i, notebook in enumerate(notebooks):
        print(f"Converting {notebook.name}...")
        
        # Create a shorter name for output files to avoid path length issues on Windows
        # Using 30 chars to ensure total path length stays well below 260 chars
        output_stem = f"{notebook.stem[:30]}_{i}"

        try:
            with open(notebook, "r", encoding="utf-8") as f:
                nb = nbformat.read(f, as_version=4)
            body, _ = MarkdownExporter().from_notebook_node(nb)
            body = sanitize_html_artifacts(body, strip_tags=False)
            output_path = notebook.parent / f"{output_stem}.md"
            output_path.write_text(body, encoding="utf-8")
            print(f"Successfully converted {notebook.name} to {output_path.name}")
        except Exception as e:
            print(f"Error converting {notebook.name}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Converts all .ipynb files in a directory to .md files."
    )
    parser.add_argument(
        "input_path",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Path to the directory containing .ipynb files. Defaults to the current directory.",
    )
    args = parser.parse_args()
    convert_notebooks(args.input_path)
