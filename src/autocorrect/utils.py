import os
import nbformat
from nbconvert import MarkdownExporter

def read_file_content(file_path):
    """
    Reads the content of a file based on its extension.
    Supports: .ipynb, .docx, .pdf, and text files (.txt, .md, .py, .sql, etc.)
    """
    ext = os.path.splitext(file_path)[1].lower()

    try:
        if ext == '.ipynb':
            return _read_ipynb(file_path)
        elif ext == '.docx':
            return _read_docx(file_path)
        elif ext == '.pdf':
            return _read_pdf(file_path)
        else:
            # Assume text file
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
    except Exception as e:
        return f"Error reading file {file_path}: {str(e)}"

def _read_ipynb(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    md_exporter = MarkdownExporter()
    (body, resources) = md_exporter.from_notebook_node(nb)
    return body

def _read_docx(file_path):
    try:
        import docx
    except ImportError:
        return "Error: python-docx not installed. Cannot read .docx files."
    
    doc = docx.Document(file_path)
    full_text = []
    for para in doc.paragraphs:
        full_text.append(para.text)
    return '\n'.join(full_text)

def _read_pdf(file_path):
    try:
        from pypdf import PdfReader
    except ImportError:
        return "Error: pypdf not installed. Cannot read .pdf files."

    reader = PdfReader(file_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text

