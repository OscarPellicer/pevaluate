"""Images found in documents: the extraction types, MIME sniffing, and the image assets written
next to the Markdown (``image_<sha>.<ext>``) with their relative links."""
import base64
import hashlib
import mimetypes
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse


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


def _image_from_data_uri(uri, source):
    match = re.match(r"data:(image/[a-zA-Z0-9.+-]+);base64,(.*)", uri, flags=re.S)
    if not match:
        return None
    data = base64.b64decode(re.sub(r"\s+", "", match.group(2)))
    return _image_from_bytes(source, data, mime_type=match.group(1))


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
