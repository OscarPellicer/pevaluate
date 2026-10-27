"""Markdown and HTML files (image links resolved to assets), and the cleanup of HTML artifacts
(scripts, styles, SVG, embedded base64 images) before the text goes to an LLM."""
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from .images import (
    MarkdownExtraction,
    _collect_markdown_asset_images,
    _guess_mime,
    _image_from_bytes,
    _image_from_data_uri,
    _write_image_asset,
)


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


def sanitize_html_artifacts(text, strip_tags=False):
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
