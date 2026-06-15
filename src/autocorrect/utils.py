import os
import re
import base64
import hashlib
import mimetypes
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET
try:
    import nbformat
    from nbconvert import MarkdownExporter
except ImportError:
    nbformat = None
    MarkdownExporter = None


@dataclass
class ExtractedImage:
    source: str
    mime_type: str
    data: bytes
    sha256: str

    @property
    def data_url(self):
        encoded = base64.b64encode(self.data).decode("ascii")
        return f"data:{self.mime_type};base64,{encoded}"


@dataclass
class MarkdownExtraction:
    markdown: str
    images: list
    warnings: list
    image_paths: list = field(default_factory=list)

def read_file_content(file_path, cleanup_html=True):
    """
    Reads the content of a file based on its extension.
    Supports: .ipynb, .docx, .pdf, and text files (.txt, .md, .py, .sql, etc.)
    """
    ext = os.path.splitext(file_path)[1].lower()

    try:
        if ext == '.ipynb':
            return normalize_extracted_text(_read_ipynb(file_path, cleanup_html=cleanup_html))
        elif ext in ('.html', '.htm'):
            return normalize_extracted_text(_read_html(file_path, cleanup_html=cleanup_html))
        elif ext == '.docx':
            return normalize_extracted_text(_read_docx(file_path))
        elif ext == '.pdf':
            return normalize_extracted_text(_read_pdf(file_path))
        else:
            # Assume text file
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            return normalize_extracted_text(sanitize_html_artifacts(content, strip_tags=False) if cleanup_html else content)
    except Exception as e:
        return f"Error reading file {file_path}: {str(e)}"


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
            result = MarkdownExtraction(_read_ipynb(file_path, cleanup_html=cleanup_html), [], [])
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


def dedupe_images(images):
    seen = set()
    unique = []
    duplicates = 0
    for image in images:
        if image.sha256 in seen:
            duplicates += 1
            continue
        seen.add(image.sha256)
        unique.append(image)
    return unique, duplicates


def _guess_mime(path_or_name, data=None):
    mime, _encoding = mimetypes.guess_type(path_or_name)
    if mime:
        return mime
    if data:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
            return "image/gif"
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return "image/webp"
    return "application/octet-stream"


def _image_from_bytes(source, data, mime_type=None):
    mime_type = mime_type or _guess_mime(source, data)
    return ExtractedImage(
        source=str(source),
        mime_type=mime_type,
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _image_extension(mime_type):
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
    }.get(mime_type, ".img")


def _relative_asset_path(path, image_reference_dir):
    if image_reference_dir:
        return os.path.relpath(path, image_reference_dir).replace("\\", "/")
    return str(path).replace("\\", "/")


def _write_image_asset(image, image_output_dir, image_reference_dir):
    if not image_output_dir:
        return image.source
    extension = _image_extension(image.mime_type)
    asset_path = Path(image_output_dir) / f"image_{image.sha256[:12]}{extension}"
    if not asset_path.exists():
        asset_path.write_bytes(image.data)
    return _relative_asset_path(asset_path, image_reference_dir)


def _normalize_markdown_image_paths(markdown, image_output_dir, image_reference_dir):
    if not image_output_dir:
        return markdown
    image_output_dir = Path(image_output_dir)

    def replace_link(match):
        alt = match.group(1)
        src = match.group(2).strip()
        clean_src = src.strip("<>")
        candidates = [
            Path(clean_src),
            image_output_dir / Path(clean_src).name,
        ]
        if not Path(clean_src).is_absolute():
            candidates.append(image_output_dir / clean_src)
        for candidate in candidates:
            if candidate.exists():
                return f"![{alt}]({_relative_asset_path(candidate, image_reference_dir)})"
        return match.group(0)

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_link, markdown)


def _collect_asset_images(image_output_dir):
    if not image_output_dir:
        return []
    images = []
    for path in sorted(Path(image_output_dir).glob("*")):
        if not path.is_file():
            continue
        mime_type = _guess_mime(str(path), path.read_bytes())
        if mime_type.startswith("image/"):
            images.append(_image_from_bytes(str(path), path.read_bytes(), mime_type=mime_type))
    return images


def _collect_markdown_asset_images(markdown, image_output_dir, image_reference_dir):
    if not image_output_dir:
        return [], []

    image_output_dir = Path(image_output_dir)
    image_reference_dir = Path(image_reference_dir) if image_reference_dir else None
    images = []
    image_paths = []
    seen_paths = set()

    for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", markdown or ""):
        src = match.group(1).strip().strip("<>")
        parsed = urlparse(src)
        if parsed.scheme and parsed.scheme not in {"file"}:
            continue

        if parsed.scheme == "file":
            candidates = [Path(unquote(parsed.path))]
        else:
            raw_path = Path(unquote(src))
            candidates = [raw_path]
            if image_reference_dir and not raw_path.is_absolute():
                candidates.append(image_reference_dir / raw_path)
            if not raw_path.is_absolute():
                candidates.append(image_output_dir / raw_path.name)

        for candidate in candidates:
            if not candidate.exists() or not candidate.is_file():
                continue
            try:
                resolved = candidate.resolve()
            except OSError:
                resolved = candidate.absolute()
            if resolved in seen_paths:
                break
            data = candidate.read_bytes()
            mime_type = _guess_mime(str(candidate), data)
            if not mime_type.startswith("image/"):
                break
            seen_paths.add(resolved)
            images.append(_image_from_bytes(str(candidate), data, mime_type=mime_type))
            image_paths.append(str(candidate))
            break

    return images, image_paths


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


def _paragraph_to_markdown(para, image_output_dir, image_reference_dir):
    parts = []
    for run in para.runs:
        parts.append(run.text)
        blips = run.element.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip")
        for blip in blips:
            rel_id = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
            if not rel_id:
                continue
            part = para.part.related_parts.get(rel_id)
            if not part:
                continue
            image = _image_from_bytes(str(part.partname), part.blob, mime_type=getattr(part, "content_type", None))
            if image_output_dir:
                parts.append(f"\n\n![{Path(str(part.partname)).name}]({_write_image_asset(image, image_output_dir, image_reference_dir)})\n\n")
            else:
                parts.append("\n\n[image omitted]\n\n")
    text = "".join(parts).strip()
    style_name = getattr(getattr(para, "style", None), "name", "") or ""
    match = re.match(r"Heading\s+([1-6])", style_name, flags=re.I)
    if match and text:
        return f"{'#' * int(match.group(1))} {text}"
    return text


def _docx_iter_blocks(doc):
    try:
        from docx.document import Document as DocumentClass
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError:
        return []
    parent_elm = doc.element.body
    for child in parent_elm.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, doc)
        elif child.tag.endswith("}tbl"):
            yield Table(child, doc)


def _docx_table_to_markdown(table):
    rows = [[cell.text.strip().replace("\n", "<br>") for cell in row.cells] for row in table.rows]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    header = rows[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _read_docx_markdown(file_path, image_output_dir, image_reference_dir):
    try:
        import docx
    except ImportError:
        return MarkdownExtraction("Error: python-docx not installed. Cannot read .docx files.", [], [])

    doc = docx.Document(file_path)
    blocks = []
    for block in _docx_iter_blocks(doc):
        if hasattr(block, "runs"):
            text = _paragraph_to_markdown(block, image_output_dir, image_reference_dir)
        else:
            text = _docx_table_to_markdown(block)
        if text:
            blocks.append(text)
    markdown = "\n\n".join(blocks)
    images, image_paths = _collect_markdown_asset_images(markdown, image_output_dir, image_reference_dir)
    return MarkdownExtraction(markdown, images, [], image_paths)


def _pptx_shape_text(shape):
    text_parts = []
    if hasattr(shape, "text"):
        shape_text = str(shape.text or "").strip()
        if shape_text:
            text_parts.append(shape_text)
    if getattr(shape, "has_table", False):
        rows = []
        for row in shape.table.rows:
            rows.append([cell.text_frame.text.strip().replace("\n", "<br>") for cell in row.cells])
        if rows:
            width = max(len(row) for row in rows)
            rows = [row + [""] * (width - len(row)) for row in rows]
            lines = [
                "| " + " | ".join(rows[0]) + " |",
                "| " + " | ".join("---" for _ in rows[0]) + " |",
            ]
            for row in rows[1:]:
                lines.append("| " + " | ".join(row) + " |")
            text_parts.append("\n".join(lines))
    return "\n\n".join(part for part in text_parts if part)


def _read_pptx_markdown(file_path, image_output_dir, image_reference_dir):
    try:
        from pptx import Presentation
    except ImportError:
        Presentation = None

    if Presentation is not None:
        try:
            prs = Presentation(file_path)
            slides = []
            for slide_no, slide in enumerate(prs.slides, start=1):
                parts = [f"## Slide {slide_no}"]
                for shape in slide.shapes:
                    text = _pptx_shape_text(shape)
                    if text:
                        parts.append(text)
                    if getattr(shape, "shape_type", None) is not None and hasattr(shape, "image"):
                        try:
                            image_blob = shape.image.blob
                            mime_type = shape.image.content_type
                            image = _image_from_bytes(
                                f"{file_path}:slide-{slide_no}:{getattr(shape, 'name', 'image')}",
                                image_blob,
                                mime_type=mime_type,
                            )
                            if image_output_dir:
                                parts.append(f"![{getattr(shape, 'name', 'image')}]({_write_image_asset(image, image_output_dir, image_reference_dir)})")
                            else:
                                parts.append("[image omitted]")
                        except Exception:
                            pass
                slides.append("\n\n".join(part for part in parts if part))
            markdown = "\n\n".join(slides)
            images, image_paths = _collect_markdown_asset_images(markdown, image_output_dir, image_reference_dir)
            return MarkdownExtraction(markdown, images, [], image_paths)
        except Exception:
            pass

    ns = {
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    slides = []
    images = []
    with zipfile.ZipFile(file_path) as zf:
        slide_names = sorted(
            (name for name in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name)),
            key=lambda name: int(re.search(r"slide(\d+)\.xml$", name).group(1)),
        )
        for slide_no, slide_name in enumerate(slide_names, start=1):
            rels_name = f"ppt/slides/_rels/{Path(slide_name).name}.rels"
            rel_targets = {}
            if rels_name in zf.namelist():
                rel_root = ET.fromstring(zf.read(rels_name))
                for rel in rel_root:
                    rel_id = rel.attrib.get("Id")
                    target = rel.attrib.get("Target", "")
                    rel_targets[rel_id] = target

            root = ET.fromstring(zf.read(slide_name))
            parts = [f"## Slide {slide_no}"]
            sp_tree = root.find(".//p:cSld/p:spTree", ns)
            for element in list(sp_tree) if sp_tree is not None else []:
                texts = [node.text for node in element.findall(".//a:t", ns) if node.text]
                if texts:
                    parts.append("\n".join(texts))
                for blip in element.findall(".//a:blip", ns):
                    rel_id = blip.attrib.get(f"{{{ns['r']}}}embed")
                    target = rel_targets.get(rel_id)
                    if not target:
                        continue
                    if target.startswith("../"):
                        media_name = "ppt/" + target[3:]
                    else:
                        media_name = "ppt/slides/" + target
                    if not media_name.startswith("ppt/"):
                        media_name = "ppt/" + target.lstrip("../")
                    if media_name not in zf.namelist():
                        media_name = "ppt/media/" + Path(target).name
                    if media_name not in zf.namelist():
                        continue
                    data = zf.read(media_name)
                    image = _image_from_bytes(f"{file_path}:{media_name}", data, mime_type=_guess_mime(media_name, data))
                    images.append(image)
                    if image_output_dir:
                        parts.append(f"![{Path(media_name).name}]({_write_image_asset(image, image_output_dir, image_reference_dir)})")
                    else:
                        parts.append("[image omitted]")
            slides.append("\n\n".join(part for part in parts if part))
    markdown = "\n\n".join(slides)
    image_paths = []
    if image_output_dir:
        images, image_paths = _collect_markdown_asset_images(markdown, image_output_dir, image_reference_dir)
    return MarkdownExtraction(markdown, images, [], image_paths)


def _read_markup_markdown(file_path, image_output_dir, image_reference_dir, cleanup_html=True):
    path = Path(file_path)
    markdown = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in {".html", ".htm"} and cleanup_html and not image_output_dir:
        markdown = sanitize_html_artifacts(markdown, strip_tags=False)

    images = []

    def replace_src(raw_src, alt="image"):
        src = raw_src.split(None, 1)[0].strip("<>'\"")
        if not src:
            return raw_src, None
        if src.startswith("data:image/"):
            image = _image_from_data_uri(src, f"{file_path}:embedded-image-{len(images) + 1}")
        else:
            parsed = urlparse(src)
            if parsed.scheme and parsed.scheme not in {"file"}:
                return src, None
            local_path = Path(unquote(parsed.path)) if parsed.scheme == "file" else path.parent / unquote(src)
            if not local_path.exists() or not local_path.is_file():
                return src, None
            data = local_path.read_bytes()
            mime_type = _guess_mime(str(local_path), data)
            if not mime_type.startswith("image/"):
                return src, None
            image = _image_from_bytes(str(local_path), data, mime_type=mime_type)
        if not image:
            return src, None
        images.append(image)
        if not image_output_dir:
            return src, image
        return _write_image_asset(image, image_output_dir, image_reference_dir), image

    def replace_md(match):
        new_src, _image = replace_src(match.group(2), alt=match.group(1))
        return f"![{match.group(1)}]({new_src})"

    def replace_html(match):
        before = match.group(1)
        src = match.group(2)
        after = match.group(3)
        new_src, _image = replace_src(src)
        return f'<img{before}src="{new_src}"{after}>'

    markdown = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_md, markdown)
    markdown = re.sub(r'(?is)<img\b([^>]*?\bsrc=["\'])([^"\']+)(["\'][^>]*)>', replace_html, markdown)
    image_paths = []
    if image_output_dir:
        images, image_paths = _collect_markdown_asset_images(markdown, image_output_dir, image_reference_dir)
    return MarkdownExtraction(markdown, images, [], image_paths)


def _read_zip_media_images(file_path, media_prefixes):
    images = []
    with zipfile.ZipFile(file_path) as zf:
        for member in zf.infolist():
            member_name = member.filename.replace("\\", "/")
            if member.is_dir() or not member_name.lower().startswith(media_prefixes):
                continue
            mime_type = _guess_mime(member_name)
            if not mime_type.startswith("image/"):
                continue
            data = zf.read(member)
            images.append(_image_from_bytes(f"{file_path}:{member_name}", data, mime_type=mime_type))
    return images


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


def _read_markup_images(file_path):
    path = Path(file_path)
    text = path.read_text(encoding="utf-8", errors="replace")
    candidates = []
    candidates.extend(match.group(1).strip() for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", text))
    candidates.extend(match.group(1).strip() for match in re.finditer(r'(?is)<img\b[^>]*\bsrc=["\']([^"\']+)["\']', text))

    images = []
    for raw_src in candidates:
        src = raw_src.split(None, 1)[0].strip("<>'\"")
        if not src:
            continue
        if src.startswith("data:image/"):
            image = _image_from_data_uri(src, f"{file_path}:embedded-image-{len(images) + 1}")
            if image:
                images.append(image)
            continue
        parsed = urlparse(src)
        if parsed.scheme and parsed.scheme not in {"file"}:
            continue
        local_path = Path(unquote(parsed.path)) if parsed.scheme == "file" else path.parent / unquote(src)
        if local_path.exists() and local_path.is_file():
            data = local_path.read_bytes()
            mime_type = _guess_mime(str(local_path), data)
            if mime_type.startswith("image/"):
                images.append(_image_from_bytes(str(local_path), data, mime_type=mime_type))
    return images


def _image_from_data_uri(uri, source):
    match = re.match(r"data:(image/[a-zA-Z0-9.+-]+);base64,(.*)", uri, flags=re.S)
    if not match:
        return None
    data = base64.b64decode(re.sub(r"\s+", "", match.group(2)))
    return _image_from_bytes(source, data, mime_type=match.group(1))

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

