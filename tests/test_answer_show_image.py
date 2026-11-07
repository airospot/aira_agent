"""Regression: enrich ANSWER with verified show_image display_url."""

from __future__ import annotations

from app.domain.agents.flow.execution.answer_show_image import (
    enrich_answer_with_show_images,
)
from app.interfaces.web.safe_markdown import render_safe_markdown

_URL = "/agent/corpus/images/figure-1.png"


def test_plain_url_becomes_markdown_image():
    answer = f"İşte şekil: {_URL}"
    obs = [{"status": "ok", "path": "images/figure-1.png", "display_url": _URL}]
    out = enrich_answer_with_show_images(answer, obs)
    assert f"![görsel]({_URL})" in out
    assert out.count(_URL) == 1
    html = render_safe_markdown(out)
    assert 'class="agent-inline-image"' in html
    assert f'src="{_URL}"' in html


def test_existing_markdown_image_not_duplicated():
    answer = f"Şekil:\n\n![kapak]({_URL})\n"
    obs = [{"status": "ok", "path": "images/figure-1.png", "display_url": _URL}]
    out = enrich_answer_with_show_images(answer, obs)
    assert out.count(_URL) == 1
    assert out.count("![") == 1
    assert "![kapak]" in out


def test_failed_show_image_does_not_inject():
    answer = "Görsel bulunamadı."
    obs = [
        {
            "status": "not_found",
            "path": "images/missing.png",
            "display_url": None,
            "error": "file_not_found",
        }
    ]
    out = enrich_answer_with_show_images(answer, obs)
    assert out == answer
    assert "![" not in out
    assert "/agent/corpus/" not in out


def test_ignores_bare_path_without_successful_observation():
    answer = "Dosya: images/secret.png"
    out = enrich_answer_with_show_images(answer, [])
    assert out == answer
    assert "![" not in out


def test_appends_when_url_absent_from_answer():
    answer = "Tablo aşağıda."
    obs = [{"status": "ok", "path": "images/figure-1.png", "display_url": _URL}]
    out = enrich_answer_with_show_images(answer, obs)
    assert answer in out
    assert f"![görsel]({_URL})" in out
