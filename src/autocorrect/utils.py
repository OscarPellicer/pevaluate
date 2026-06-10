import os
import re
try:
    import nbformat
    from nbconvert import MarkdownExporter
except ImportError:
    nbformat = None
    MarkdownExporter = None

def read_file_content(file_path, cleanup_html=True):
    """
    Reads the content of a file based on its extension.
    Supports: .ipynb, .docx, .pdf, and text files (.txt, .md, .py, .sql, etc.)
    """
    ext = os.path.splitext(file_path)[1].lower()

    try:
        if ext == '.ipynb':
            return _read_ipynb(file_path, cleanup_html=cleanup_html)
        elif ext in ('.html', '.htm'):
            return _read_html(file_path, cleanup_html=cleanup_html)
        elif ext == '.docx':
            return _read_docx(file_path)
        elif ext == '.pdf':
            return _read_pdf(file_path)
        else:
            # Assume text file
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            return sanitize_html_artifacts(content, strip_tags=False) if cleanup_html else content
    except Exception as e:
        return f"Error reading file {file_path}: {str(e)}"

def _read_ipynb(file_path, cleanup_html=True):
    if nbformat is None or MarkdownExporter is None:
        return "Error: nbformat/nbconvert not installed. Cannot read .ipynb files."
    with open(file_path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    md_exporter = MarkdownExporter()
    (body, resources) = md_exporter.from_notebook_node(nb)
    return sanitize_html_artifacts(body, strip_tags=False) if cleanup_html else body

def _read_html(file_path, cleanup_html=True):
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        html = f.read()

    if not cleanup_html:
        return html

    original_len = len(html)
    text = sanitize_html_artifacts(html, strip_tags=True)
    return f"[HTML sanitizado: {original_len} caracteres originales, {len(text)} caracteres tras limpieza]\n\n{text}"

def sanitize_html_artifacts(text, strip_tags=False):
    original = text
    text = re.sub(r'(?is)<script\b[^>]*>.*?</script>', '\n', text)
    text = re.sub(r'(?is)<style\b[^>]*>.*?</style>', '\n', text)
    text = re.sub(r'(?is)<svg\b[^>]*>.*?</svg>', '\n', text)
    text = re.sub(r'(?is)<img\b[^>]*>', '\n[imagen omitida]\n', text)
    text = re.sub(r'(?is)url\(\s*[\'"]?data:image/[^)]*\)', 'url([imagen embebida omitida])', text)
    text = re.sub(r'(?is)data:image/[a-zA-Z0-9.+-]+;base64,[a-zA-Z0-9+/=\s]+', '[imagen embebida omitida]', text)
    text = re.sub(r'(?is)<!--.*?-->', '\n', text)
    if strip_tags:
        text = re.sub(r'(?s)<br\s*/?>', '\n', text)
        text = re.sub(r'(?s)</(p|div|h[1-6]|li|tr|pre|code|blockquote|table|thead|tbody)>', '\n', text)
        text = re.sub(r'(?s)</tr>', '\n', text)
        text = re.sub(r'(?s)</(td|th)>', ' | ', text)
        text = re.sub(r'(?s)<[^>]+>', ' ', text)

    try:
        import html as html_lib
        text = html_lib.unescape(text)
    except Exception:
        pass

    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
    return text.strip()

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

