import base64
import sys
import types
import zipfile
import argparse
from pathlib import Path

from autocorrect import utils
from autocorrect.cli import _limit_images, build_multimodal_user_content, grade_submissions, main


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAAC0lEQVR4nGNg+A8AAwMBAY+ip1sAAAAASUVORK5CYII="
)
SECOND_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def _write_zip(path, members):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def test_docx_and_pptx_image_extraction_deduplicates_repeated_media(tmp_path):
    docx_path = tmp_path / "answer.docx"
    pptx_path = tmp_path / "slides.pptx"
    _write_zip(docx_path, {
        "word/media/image1.png": PNG_BYTES,
        "word/media/logo-copy.png": PNG_BYTES,
        "docProps/core.xml": b"<xml />",
    })
    _write_zip(pptx_path, {
        "ppt/media/image1.png": PNG_BYTES,
        "ppt/media/image2.png": SECOND_PNG_BYTES,
        "ppt/media/logo-copy.png": PNG_BYTES,
    })

    docx_images, docx_warnings = utils.read_file_images(str(docx_path))
    pptx_images, pptx_warnings = utils.read_file_images(str(pptx_path))

    assert len(docx_images) == 1
    assert docx_images[0].mime_type == "image/png"
    assert "Removed 1 duplicate image" in docx_warnings[0]
    assert len(pptx_images) == 2
    assert "Removed 1 duplicate image" in pptx_warnings[0]


def test_markdown_extracts_local_and_embedded_images_and_deduplicates(tmp_path):
    image_path = tmp_path / "figure.png"
    image_path.write_bytes(PNG_BYTES)
    embedded = base64.b64encode(SECOND_PNG_BYTES).decode("ascii")
    md_path = tmp_path / "answer.md"
    md_path.write_text(
        f"![local](figure.png)\n\n<img src=\"figure.png\">\n\n![embedded](data:image/png;base64,{embedded})",
        encoding="utf-8",
    )

    images, warnings = utils.read_file_images(str(md_path))

    assert len(images) == 2
    assert {image.sha256 for image in images} == {
        utils._image_from_bytes("a", PNG_BYTES).sha256,
        utils._image_from_bytes("b", SECOND_PNG_BYTES).sha256,
    }
    assert "Removed 1 duplicate image" in warnings[0]


def test_read_file_markdown_rewrites_images_to_relative_assets(tmp_path):
    image_path = tmp_path / "figure.png"
    image_path.write_bytes(PNG_BYTES)
    md_path = tmp_path / "answer.md"
    md_path.write_text("Before.\n\n![diagram](figure.png)\n\nAfter.", encoding="utf-8")
    prompts_dir = tmp_path / "prompts"
    assets_dir = prompts_dir / "answer_images"

    extraction = utils.read_file_markdown(
        str(md_path),
        image_output_dir=assets_dir,
        image_reference_dir=prompts_dir,
    )

    assert "Before." in extraction.markdown
    assert "![diagram](answer_images/image_" in extraction.markdown
    assert "After." in extraction.markdown
    assert len(extraction.images) == 1
    assert len(list(assets_dir.glob("*.png"))) == 1


def test_pdf_markdown_uses_pymupdf4llm_defaults_and_relative_images(monkeypatch, tmp_path):
    def fake_to_markdown(doc, **kwargs):
        assert kwargs["header"] is False
        assert kwargs["footer"] is False
        assert kwargs["use_ocr"] is False
        assert kwargs["force_text"] is True
        assert kwargs["write_images"] is True
        image_path = Path(kwargs["image_path"])
        image_path.mkdir(parents=True, exist_ok=True)
        (image_path / "page-1.png").write_bytes(PNG_BYTES)
        return f"PDF text.\n\n![page image]({image_path / 'page-1.png'})"

    monkeypatch.setitem(sys.modules, "pymupdf4llm", types.SimpleNamespace(to_markdown=fake_to_markdown))
    pdf_path = tmp_path / "answer.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    prompts_dir = tmp_path / "prompts"

    extraction = utils.read_file_markdown(
        str(pdf_path),
        image_output_dir=prompts_dir / "pdf_images",
        image_reference_dir=prompts_dir,
    )

    assert "PDF text." in extraction.markdown
    assert "![page image](pdf_images/page-1.png)" in extraction.markdown
    assert len(extraction.images) == 1


def test_pdf_markdown_ignores_stale_unreferenced_asset_images(monkeypatch, tmp_path):
    def fake_to_markdown(doc, **kwargs):
        image_path = Path(kwargs["image_path"])
        image_path.mkdir(parents=True, exist_ok=True)
        (image_path / "current.png").write_bytes(PNG_BYTES)
        return f"PDF text.\n\n![current]({image_path / 'current.png'})"

    monkeypatch.setitem(sys.modules, "pymupdf4llm", types.SimpleNamespace(to_markdown=fake_to_markdown))
    pdf_path = tmp_path / "answer.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    prompts_dir = tmp_path / "prompts"
    assets_dir = prompts_dir / "pdf_images"
    assets_dir.mkdir(parents=True)
    (assets_dir / "stale.png").write_bytes(SECOND_PNG_BYTES)

    extraction = utils.read_file_markdown(
        str(pdf_path),
        image_output_dir=assets_dir,
        image_reference_dir=prompts_dir,
    )

    assert "![current](pdf_images/current.png)" in extraction.markdown
    assert len(extraction.images) == 1
    assert extraction.images[0].source.endswith("current.png")


def test_normalize_extracted_text_replaces_ligature_controls():
    assert utils.normalize_extracted_text("co\x1cn and a\x1doat \ufb01 \ufb02") == "cofin and afloat fi fl"


def test_pdf_image_extraction_uses_pypdf_page_images(monkeypatch, tmp_path):
    class FakePdfImage:
        name = "diagram.png"
        data = PNG_BYTES

    class FakePage:
        images = [FakePdfImage(), FakePdfImage()]

    class FakePdfReader:
        def __init__(self, _path):
            self.pages = [FakePage()]

    fake_pypdf = types.SimpleNamespace(PdfReader=FakePdfReader)
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)

    pdf_path = tmp_path / "answer.pdf"
    pdf_path.write_bytes(b"%PDF fake")

    images, warnings = utils.read_file_images(str(pdf_path))

    assert len(images) == 1
    assert images[0].source.endswith("page-1:diagram.png")
    assert "Removed 1 duplicate image" in warnings[0]


def test_multimodal_message_content_and_image_limit():
    images = [
        utils._image_from_bytes("one.png", PNG_BYTES),
        utils._image_from_bytes("two.png", SECOND_PNG_BYTES),
    ]

    limited, omitted = _limit_images(images, 1)
    content = build_multimodal_user_content("Grade this.", limited)

    assert omitted == 1
    assert content[0] == {"type": "text", "text": "Grade this."}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert build_multimodal_user_content("Text only.", []) == "Text only."


def test_no_evaluate_saves_markdown_prompt_and_image_assets(tmp_path, capsys):
    session_dir = tmp_path / "session"
    students_dir = session_dir / "students"
    session_dir.mkdir()
    students_dir.mkdir()

    (session_dir / "rubric.txt").write_text("Grade this TFG from 0 to 10.", encoding="utf-8")
    (session_dir / "example.txt").write_text("Short, constructive feedback.", encoding="utf-8")
    (students_dir / "Marta_TFG.md").write_text(
        "Final project text.\n\n![figure](figure.png)",
        encoding="utf-8",
    )
    (students_dir / "figure.png").write_bytes(PNG_BYTES)

    args = argparse.Namespace(
        no_evaluate=True,
        rubric="rubric.txt",
        example="example.txt",
        reference="",
        no_reference=True,
        no_cleanup_html=False,
        include_images=True,
        no_dedupe_images=False,
        max_images=20,
        files_regex=r".*\.md$",
        prefer_extensions="",
        student=None,
        keep_prompt=True,
        model="fake/model",
    )

    grade_submissions(str(session_dir), str(students_dir), args)

    output = capsys.readouterr().out
    assert "Prompt size for Marta" in output
    assert "Skipping LLM evaluation" in output
    prompt_files = list((session_dir / "prompts").glob("prompt_*.md"))
    assert len(prompt_files) == 1
    prompt_text = prompt_files[0].read_text(encoding="utf-8")
    assert "# pevaluate LLM Prompt" in prompt_text
    assert "## Attached Images" not in prompt_text
    assert "The following extracted image" not in prompt_text
    assert "![figure](prompt_*_images/" not in prompt_text
    assert "![figure](prompt_" in prompt_text
    assert len(list((session_dir / "prompts").glob("prompt_*_images/*.png"))) == 1
    assert not (session_dir / "feedback").exists()


def test_cli_accepts_single_file_input_with_output_dir(tmp_path, monkeypatch, capsys):
    output_dir = tmp_path / "eval"
    output_dir.mkdir()
    submission = tmp_path / "single_submission.md"
    submission.write_text("A single TFG submission.", encoding="utf-8")
    (output_dir / "rubric.txt").write_text("Grade from 0 to 10.", encoding="utf-8")
    (output_dir / "example.txt").write_text("Brief feedback.", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", [
        "pevaluate",
        str(submission),
        "--output-dir", str(output_dir),
        "--rubric", "rubric.txt",
        "--example", "example.txt",
        "--no-reference",
        "--keep-prompt",
        "--no-evaluate",
    ])

    main()

    output = capsys.readouterr().out
    assert "Single-file input detected" in output
    assert "Using single submission file" in output
    assert "Prompt size for single" in output
    assert len(list((output_dir / "prompts").glob("prompt_*.md"))) == 1
    assert not (output_dir / "students").exists()
