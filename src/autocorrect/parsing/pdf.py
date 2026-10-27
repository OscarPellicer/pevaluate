"""PDF to Markdown (pymupdf4llm) and the raster images embedded in a PDF (pypdf)."""
from .images import (
    MarkdownExtraction,
    _collect_markdown_asset_images,
    _image_from_bytes,
    _normalize_markdown_image_paths,
)


def _read_pdf_markdown(file_path, image_output_dir, image_reference_dir, markdown_config):
    try:
        import pymupdf4llm
    except ImportError:
        raise RuntimeError(
            "pymupdf4llm is required by pevaluate for PDF Markdown extraction. Reinstall pevaluate so its declared dependencies are installed."
        )

    markdown_config = dict(markdown_config or {})
    pdf_backend = str(markdown_config.pop("pdf_backend", markdown_config.pop("backend", "layout"))).lower()

    config = {
        "header": False,
        "footer": False,
        "use_ocr": False,
        "force_text": True,
    }
    if image_output_dir:
        config.update({
            "write_images": True,
            "image_path": str(image_output_dir),
        })
    config.update(markdown_config)
    if pdf_backend == "legacy":
        import pymupdf4llm.helpers.pymupdf_rag as pymupdf_rag
        legacy_config = dict(config)
        for ignored_key in ("header", "footer", "use_ocr", "force_ocr", "ocr_dpi", "ocr_language"):
            legacy_config.pop(ignored_key, None)
        markdown = pymupdf_rag.to_markdown(file_path, **legacy_config)
    else:
        markdown = pymupdf4llm.to_markdown(file_path, **config)
    if isinstance(markdown, list):
        markdown = "\n\n".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in markdown)
    markdown = _normalize_markdown_image_paths(str(markdown), image_output_dir, image_reference_dir)
    images, image_paths = _collect_markdown_asset_images(markdown, image_output_dir, image_reference_dir)
    return MarkdownExtraction(markdown, images, [], image_paths)


def _read_pdf_images(file_path):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("pypdf not installed. Cannot extract images from .pdf files.")

    images = []
    reader = PdfReader(file_path)
    for page_index, page in enumerate(reader.pages, start=1):
        for image_index, pdf_image in enumerate(getattr(page, "images", []) or [], start=1):
            name = getattr(pdf_image, "name", f"image_{image_index}")
            data = getattr(pdf_image, "data", None)
            if data is None:
                continue
            images.append(_image_from_bytes(f"{file_path}:page-{page_index}:{name}", data))
    return images
