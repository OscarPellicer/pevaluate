"""Document-to-Markdown parser shared with ptestgen (``ptestgen generate``); also importable as
:mod:`autocorrect.utils`.

:func:`read_file_markdown` turns PDF, DOCX, PPTX, notebooks, HTML, Markdown, images and text
files into Markdown (with image assets); :func:`read_file_images` extracts their raster images.
"""
import os
import re
from pathlib import Path

from .images import ExtractedImage, MarkdownExtraction, _image_from_bytes, _write_image_asset, dedupe_images
from .markup import _read_markup_images, _read_markup_markdown, sanitize_html_artifacts
from .notebook import _read_ipynb, compact_notebook
from .office import _read_docx_markdown, _read_pptx_markdown, _read_zip_media_images
from .pdf import _read_pdf_images, _read_pdf_markdown

__all__ = [
    "ExtractedImage", "MarkdownExtraction", "compact_notebook", "dedupe_images", "normalize_extracted_text",
    "read_file_images", "read_file_markdown", "sanitize_html_artifacts",
]


def read_file_markdown(
    file_path,
    cleanup_html=True,
    image_output_dir=None,
    image_reference_dir=None,
    markdown_config=None,
    dedupe=True,
):
    """
    Reads a file as Markdown, preserving image references where the source format allows it.
    """
    ext = os.path.splitext(file_path)[1].lower()
    markdown_config = markdown_config or {}
    image_output_dir = Path(image_output_dir) if image_output_dir else None
    image_reference_dir = Path(image_reference_dir) if image_reference_dir else None
    if image_output_dir:
        image_output_dir.mkdir(parents=True, exist_ok=True)

    try:
        if ext == ".pdf":
            result = _read_pdf_markdown(file_path, image_output_dir, image_reference_dir, markdown_config)
        elif ext == ".docx":
            result = _read_docx_markdown(file_path, image_output_dir, image_reference_dir)
        elif ext == ".pptx":
            result = _read_pptx_markdown(file_path, image_output_dir, image_reference_dir)
        elif ext == ".ipynb":
            result = MarkdownExtraction(_read_ipynb(file_path, cleanup_html=cleanup_html,
                                                    max_output_chars=markdown_config.get("max_output_chars", 3000)), [], [])
        elif ext in (".html", ".htm"):
            result = _read_markup_markdown(file_path, image_output_dir, image_reference_dir, cleanup_html=cleanup_html)
        elif ext in {".md", ".markdown"}:
            result = _read_markup_markdown(file_path, image_output_dir, image_reference_dir, cleanup_html=False)
        elif ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
            image = _image_from_bytes(file_path, Path(file_path).read_bytes())
            ref = _write_image_asset(image, image_output_dir, image_reference_dir) if image_output_dir else file_path
            image_path = str(Path(image_output_dir) / Path(ref).name) if image_output_dir else file_path
            result = MarkdownExtraction(f"![{Path(file_path).name}]({ref})", [image], [], [image_path])
        else:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            markdown = sanitize_html_artifacts(content, strip_tags=False) if cleanup_html else content
            result = MarkdownExtraction(markdown, [], [])
    except Exception as e:
        return MarkdownExtraction(f"Error reading file {file_path}: {str(e)}", [], [str(e)])

    result.markdown = normalize_extracted_text(result.markdown)
    if dedupe:
        original_images = list(result.images)
        original_paths = list(result.image_paths)
        result.images, duplicate_count = dedupe_images(result.images)
        if original_paths:
            unique_paths = []
            seen = set()
            for image, path in zip(original_images, original_paths):
                if image.sha256 in seen:
                    continue
                seen.add(image.sha256)
                unique_paths.append(path)
            result.image_paths = unique_paths
        if duplicate_count:
            result.warnings.append(f"Removed {duplicate_count} duplicate image attachment(s) from {file_path}.")
    return result


def normalize_extracted_text(text):
    replacements = {
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\ufb05": "st",
        "\ufb06": "st",
        "\x1c": "fi",
        "\x1d": "fl",
        "\x1e": "ffi",
        "\x1f": "ffl",
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1b\x7f]", "", text)
    return text


def read_file_images(file_path, dedupe=True):
    """
    Extract raster images from supported submission/reference files.
    Supports: .docx, .pptx, .pdf, .md/.markdown, .html/.htm, and direct image files.
    """
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
            images = [_image_from_bytes(file_path, Path(file_path).read_bytes())]
        elif ext == ".docx":
            images = _read_zip_media_images(file_path, ("word/media/",))
        elif ext == ".pptx":
            images = _read_zip_media_images(file_path, ("ppt/media/",))
        elif ext == ".pdf":
            images = _read_pdf_images(file_path)
        elif ext in {".md", ".markdown", ".html", ".htm"}:
            images = _read_markup_images(file_path)
        else:
            images = []
    except Exception as e:
        return [], [f"Error extracting images from {file_path}: {str(e)}"]

    warnings = []
    if dedupe:
        images, duplicate_count = dedupe_images(images)
        if duplicate_count:
            warnings.append(f"Removed {duplicate_count} duplicate image(s) from {file_path}.")
    return images, warnings
