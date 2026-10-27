"""``.env`` loading. The document-to-Markdown parser lives in :mod:`autocorrect.parsing`; its names
are re-exported here because ptestgen and older code import them from ``autocorrect.utils``."""
from pathlib import Path

from dotenv import load_dotenv

from autocorrect.parsing import (
    ExtractedImage,
    MarkdownExtraction,
    compact_notebook,
    dedupe_images,
    normalize_extracted_text,
    read_file_images,
    read_file_markdown,
    sanitize_html_artifacts,
)
# Internal helpers, importable from here as before the split (tests use some of them).
from autocorrect.parsing.images import (
    _collect_markdown_asset_images,
    _guess_mime,
    _image_extension,
    _image_from_bytes,
    _image_from_data_uri,
    _normalize_markdown_image_paths,
    _relative_asset_path,
    _write_image_asset,
)
from autocorrect.parsing.markup import _read_markup_images, _read_markup_markdown
from autocorrect.parsing.notebook import MarkdownExporter, _read_ipynb, _shorten, nbformat
from autocorrect.parsing.office import (
    _docx_iter_blocks,
    _docx_table_to_markdown,
    _paragraph_to_markdown,
    _pptx_shape_text,
    _read_docx_markdown,
    _read_pptx_markdown,
    _read_zip_media_images,
)
from autocorrect.parsing.pdf import _read_pdf_images, _read_pdf_markdown


def load_project_dotenv():
    """Load .env files from the current workspace and package parents."""
    seen = set()
    for start in (Path.cwd(), Path(__file__).resolve()):
        folder = start if start.is_dir() else start.parent
        for candidate in (folder, *folder.parents):
            if candidate in seen:
                continue
            seen.add(candidate)
            load_dotenv(candidate / ".env")


__all__ = [
    "load_project_dotenv",
    # autocorrect.parsing
    "ExtractedImage", "MarkdownExtraction", "compact_notebook", "dedupe_images", "normalize_extracted_text",
    "read_file_images", "read_file_markdown", "sanitize_html_artifacts",
    "MarkdownExporter", "nbformat", "_collect_markdown_asset_images", "_docx_iter_blocks", "_docx_table_to_markdown",
    "_guess_mime", "_image_extension", "_image_from_bytes", "_image_from_data_uri", "_normalize_markdown_image_paths",
    "_paragraph_to_markdown", "_pptx_shape_text", "_read_docx_markdown", "_read_ipynb", "_read_markup_images",
    "_read_markup_markdown", "_read_pdf_images", "_read_pdf_markdown", "_read_pptx_markdown", "_read_zip_media_images",
    "_relative_asset_path", "_shorten", "_write_image_asset",
]
