"""Jupyter notebooks to Markdown (nbconvert), compacted so they are cheaper to send to an LLM."""
from .markup import sanitize_html_artifacts

try:
    import nbformat
    from nbconvert import MarkdownExporter
except ImportError:
    nbformat = None
    MarkdownExporter = None


def _shorten(text, max_chars):
    """Collapse runs of repeated lines and keep the head and tail of very long text."""
    lines, out, previous, repeats = text.split("\n"), [], None, 0
    for line in lines + [None]:
        if line == previous:
            repeats += 1
            continue
        if repeats:
            out.append(f"[... previous line repeated {repeats} more times]")
        if line is not None:
            out.append(line)
        previous, repeats = line, 0
    text = "\n".join(out)
    if max_chars and len(text) > max_chars:
        half = max_chars // 2
        text = f"{text[:half]}\n[... {len(text) - max_chars:,} characters omitted ...]\n{text[-half:]}"
    return text


def _resolve_carriage_returns(text):
    """Keep what a terminal shows: a line rewritten with \\r (progress bars) keeps its last
    non-empty version."""
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if "\r" in line:
            parts = [part for part in line.split("\r") if part.strip()]
            line = parts[-1] if parts else ""
        lines.append(line)
    return "\n".join(lines)


def _merge_streams(outputs):
    """Join consecutive stream outputs of the same stream (stdout/stderr) into one. Progress
    bars (tqdm, PyTorch Lightning) can save thousands of tiny outputs in one cell, which the
    per-output truncation would not catch."""
    merged = []
    for output in outputs:
        if (output.get("output_type") == "stream" and merged
                and merged[-1].get("output_type") == "stream"
                and merged[-1].get("name") == output.get("name")):
            previous = merged[-1]["text"] if isinstance(merged[-1]["text"], str) else "".join(merged[-1]["text"])
            current = output.get("text", "")
            merged[-1]["text"] = previous + (current if isinstance(current, str) else "".join(current))
        else:
            if output.get("output_type") == "stream" and not isinstance(output.get("text", ""), str):
                output["text"] = "".join(output["text"])
            merged.append(output)
    return merged


def compact_notebook(nb, max_output_chars=3000):
    """Make a notebook cheaper to send to an LLM without losing what a grader needs:
    plain text instead of HTML when an output has both (pandas tables), consecutive stream
    outputs merged, progress-bar redraws (\\r) reduced to their final state, repeated lines
    collapsed and very long outputs (e.g. thousands of warnings) truncated."""
    for cell in nb.cells:
        if cell.get("cell_type") != "code":
            continue
        cell["outputs"] = _merge_streams(cell.get("outputs", []))
        for output in cell.get("outputs", []):
            if output.get("output_type") == "stream":
                output["text"] = _resolve_carriage_returns(output.get("text", ""))
            kind = output.get("output_type")
            if kind == "stream":
                output["text"] = _shorten(output.get("text", ""), max_output_chars)
            elif kind in ("display_data", "execute_result"):
                data = output.get("data", {})
                if "text/plain" in data and "text/html" in data:
                    del data["text/html"]
                for key in ("text/plain", "text/html", "text/markdown"):
                    if key in data:
                        value = data[key] if isinstance(data[key], str) else "".join(data[key])
                        data[key] = _shorten(value, max_output_chars)
            elif kind == "error":
                tb = output.get("traceback", [])
                if len(tb) > 6:
                    output["traceback"] = tb[:2] + ["[... traceback frames omitted ...]"] + tb[-2:]
    return nb


def _read_ipynb(file_path, cleanup_html=True, max_output_chars=3000):
    if nbformat is None or MarkdownExporter is None:
        return "Error: nbformat/nbconvert not installed. Cannot read .ipynb files."
    with open(file_path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    if max_output_chars is not None:
        nb = compact_notebook(nb, max_output_chars)
    md_exporter = MarkdownExporter()
    body, _ = md_exporter.from_notebook_node(nb)
    return sanitize_html_artifacts(body, strip_tags=False) if cleanup_html else body
