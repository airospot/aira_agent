"""Safe markdown pipe-table + existing image/link safety."""

from __future__ import annotations

from app.interfaces.web.assistant_markdown import render_assistant_markdown


def test_pipe_table_renders_table_scroll_not_paragraphs():
    md = (
        "| Ekip | Sorumlu |\n"
        "| --- | --- |\n"
        "| Saha | Mert |\n"
        "| Ag | Lina |\n"
    )
    html = render_assistant_markdown(md)
    assert '<div class="table-scroll"><table>' in html
    assert "<thead>" in html and "<th>" in html
    assert "<td>Mert</td>" in html
    assert html.count("<p>") == 0


def test_table_cell_escapes_raw_html_and_keeps_safe_link():
    md = (
        "| Col | Val |\n"
        "| --- | --- |\n"
        "| x | <script>alert(1)</script> [ok](/agent/corpus/a.png) |\n"
    )
    html = render_assistant_markdown(md)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert 'href="/agent/corpus/a.png"' in html


def test_code_fence_pipes_are_not_tables():
    md = "```\n| a | b |\n| --- | --- |\n| 1 | 2 |\n```\n"
    html = render_assistant_markdown(md)
    assert "<table>" not in html
    assert "<pre><code>" in html
    assert "| a | b |" in html


def test_invalid_separator_stays_paragraphs():
    md = "| a | b |\n| not-a-sep |\n| 1 | 2 |\n"
    html = render_assistant_markdown(md)
    assert "<table>" not in html
    assert "<p>" in html


def test_show_image_markdown_still_renders_img():
    md = "Gorsel:\n\n![cap](/agent/corpus/extracted_data/x/images/img_001.png)\n"
    html = render_assistant_markdown(md)
    assert 'src="/agent/corpus/extracted_data/x/images/img_001.png"' in html
    assert 'class="agent-inline-image"' in html
