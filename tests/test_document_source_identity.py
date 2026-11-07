"""Original upload name identity: tools, search, meta/manifest, sandbox."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.domain.agents.flow.tooling import ToolExecutor, build_native_tool_registry
from app.domain.agents.flow.tooling.native_bootstrap import NATIVE_TOOL_NAMES
from app.domain.services.document_parsers.base import ParseResult
from app.shared.document_source_identity import resolve_document_source
from app.shared.tenant_storage import resolve_tenant_storage
from tests.conftest import load_app_py


@pytest.fixture
def tenant_app(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://native:native@127.0.0.1:5432/NATIVE_FLOW_A00_TEST",
    )
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.setenv("SECRET_KEY", "source-identity-test-secret")
    monkeypatch.setenv("TENANT_DATA_ROOT", str(tmp_path / "tenants"))
    monkeypatch.setenv("AUTH_BYPASS_CUSTOMER_ID", "101")
    monkeypatch.setenv("AUTH_BYPASS_USER_ID", "201")
    mod = load_app_py()
    application = mod.create_app()
    application.config["TESTING"] = True
    application.config["AUTH_DISABLED"] = "1"
    application.config["TENANT_DATA_ROOT"] = str(tmp_path / "tenants")
    application.config["AUTH_BYPASS_CUSTOMER_ID"] = 101
    application.config["AUTH_BYPASS_USER_ID"] = 201
    return application, tmp_path / "tenants"



_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n"
    + b"\x00\x00\x00\rIHDR"
    + b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    + b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _executor() -> ToolExecutor:
    return ToolExecutor(build_native_tool_registry(), permitted_names=NATIVE_TOOL_NAMES)


def _write_extracted(
    corpus: Path,
    *,
    stem: str,
    source_filename: str,
    body: str = "hello body",
    source_sha256: str = "abc",
    with_image: bool = False,
) -> str:
    doc = corpus / "extracted_data" / stem
    doc.mkdir(parents=True)
    (doc / "content.md").write_text(body + "\n", encoding="utf-8")
    images: list[dict] = []
    if with_image:
        img_dir = doc / "images"
        img_dir.mkdir()
        (img_dir / "img_001.png").write_bytes(_MINI_PNG)
        images = [{"file": "images/img_001.png", "index": 1}]
    meta = {
        "source_filename": source_filename,
        "source_type": "docx",
        "source_sha256": source_sha256,
        "image_count": len(images),
        "images": images,
    }
    (doc / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return f"extracted_data/{stem}/content.md"


def _write_manifest(
    uploads: Path,
    *,
    upload_id: str,
    source_filename: str,
    corpus_relative_path: str,
) -> None:
    d = uploads / upload_id
    d.mkdir(parents=True)
    manifest = {
        "upload_id": upload_id,
        "customer_id": 1,
        "source_filename": source_filename,
        "stored_filename": "unused.docx",
        "original_sha256": "deadbeef",
        "status": "ready",
        "corpus_relative_path": corpus_relative_path,
        "cached": False,
    }
    (d / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_resolve_from_meta_turkish_spaced_name(tmp_path: Path) -> None:
    tenants = tmp_path / "tenants"
    st = resolve_tenant_storage(1, {"TENANT_DATA_ROOT": str(tenants)})
    original = "Saha İnceleme Formu.docx"
    rel = _write_extracted(st.corpus_root, stem="Saha_nceleme_Formu", source_filename=original)
    identity = resolve_document_source(st.corpus_root, rel)
    assert identity.source_known is True
    assert identity.source_filename == original
    assert identity.display_name == original


def test_file_name_search_matches_original_not_only_sanitized(tmp_path: Path) -> None:
    tenants = tmp_path / "tenants"
    st = resolve_tenant_storage(1, {"TENANT_DATA_ROOT": str(tenants)})
    original = "Saha İnceleme Formu.docx"
    rel = _write_extracted(st.corpus_root, stem="Saha_nceleme_Formu", source_filename=original)
    _write_manifest(
        st.uploads_root,
        upload_id="u1",
        source_filename=original,
        corpus_relative_path=rel,
    )
    cfg = {"AGENT_CORPUS_DIR": str(st.corpus_root)}
    ex = _executor()

    named = ex.execute(
        "file_name_search",
        {"query": "Saha İnceleme Formu.docx", "limit": 10},
        config=cfg,
    )
    assert named["status"] == "ok"
    assert named["matched_total"] >= 1
    hit = next(c for c in named["candidates"] if c["path"] == rel)
    assert hit["source_filename"] == original
    assert hit["display_name"] == original
    assert hit["source_known"] is True

    read = ex.execute("file_read", {"path": rel}, config=cfg)
    assert read["status"] == "ok"
    assert read["source_filename"] == original
    assert read["display_name"] == original
    assert read["path"] == rel


def test_show_image_carries_source_filename(tmp_path: Path) -> None:
    tenants = tmp_path / "tenants"
    st = resolve_tenant_storage(1, {"TENANT_DATA_ROOT": str(tenants)})
    original = "Saha İnceleme Formu.docx"
    _write_extracted(
        st.corpus_root,
        stem="Saha_nceleme_Formu",
        source_filename=original,
        with_image=True,
    )
    img_rel = "extracted_data/Saha_nceleme_Formu/images/img_001.png"
    shown = _executor().execute(
        "show_image",
        {"path": img_rel},
        config={"AGENT_CORPUS_DIR": str(st.corpus_root)},
    )
    assert shown["status"] == "ok"
    assert shown["source_filename"] == original
    assert shown["display_name"] == original
    assert shown["path"] == img_rel


def test_legacy_fixture_does_not_invent_docx_name(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "old_note.md").write_text("legacy", encoding="utf-8")
    identity = resolve_document_source(corpus, "old_note.md")
    assert identity.source_known is False
    assert identity.source_filename is None
    assert "bilinmiyor" in identity.display_name

    read = _executor().execute(
        "file_read",
        {"path": "old_note.md"},
        config={"AGENT_CORPUS_DIR": str(corpus)},
    )
    assert read["status"] == "ok"
    assert read["source_known"] is False
    assert read["source_filename"] is None


def test_broken_meta_and_outside_symlink_ignored(tmp_path: Path) -> None:
    tenants = tmp_path / "tenants"
    st = resolve_tenant_storage(1, {"TENANT_DATA_ROOT": str(tenants)})
    doc = st.corpus_root / "extracted_data" / "broken"
    doc.mkdir(parents=True)
    (doc / "content.md").write_text("x\n", encoding="utf-8")
    (doc / "meta.json").write_text("{not-json", encoding="utf-8")
    identity = resolve_document_source(st.corpus_root, "extracted_data/broken/content.md")
    assert identity.source_known is False

    outside = tmp_path / "evil_meta.json"
    outside.write_text(
        json.dumps({"source_filename": "Evil.docx"}), encoding="utf-8"
    )
    doc2 = st.corpus_root / "extracted_data" / "linked"
    doc2.mkdir(parents=True)
    (doc2 / "content.md").write_text("y\n", encoding="utf-8")
    (doc2 / "meta.json").symlink_to(outside)
    identity2 = resolve_document_source(st.corpus_root, "extracted_data/linked/content.md")
    assert identity2.source_known is False
    assert identity2.source_filename is None


def test_cache_reuse_keeps_distinct_original_names(tmp_path: Path) -> None:
    tenants = tmp_path / "tenants"
    st = resolve_tenant_storage(1, {"TENANT_DATA_ROOT": str(tenants)})
    rel = _write_extracted(
        st.corpus_root,
        stem="shared",
        source_filename="First.docx",
        source_sha256="samehash",
    )
    _write_manifest(
        st.uploads_root,
        upload_id="u_first",
        source_filename="First.docx",
        corpus_relative_path=rel,
    )
    _write_manifest(
        st.uploads_root,
        upload_id="u_second",
        source_filename="Second Name.docx",
        corpus_relative_path=rel,
    )
    identity = resolve_document_source(st.corpus_root, rel)
    assert identity.source_ambiguous is True
    assert identity.source_known is False
    assert set(identity.alternate_source_filenames) == {"First.docx", "Second Name.docx"}

    cfg = {"AGENT_CORPUS_DIR": str(st.corpus_root)}
    ex = _executor()
    for name in ("First.docx", "Second Name.docx"):
        named = ex.execute("file_name_search", {"query": name, "limit": 10}, config=cfg)
        assert named["status"] == "ok"
        assert any(
            c.get("path") == rel and c.get("source_filename") == name
            for c in named["candidates"]
        )


def test_same_original_name_different_paths_are_distinct(tmp_path: Path) -> None:
    tenants = tmp_path / "tenants"
    st = resolve_tenant_storage(1, {"TENANT_DATA_ROOT": str(tenants)})
    name = "Rapor.docx"
    rel_a = _write_extracted(st.corpus_root, stem="Rapor", source_filename=name, body="A")
    rel_b = _write_extracted(st.corpus_root, stem="Rapor_2", source_filename=name, body="B")
    _write_manifest(
        st.uploads_root, upload_id="ua", source_filename=name, corpus_relative_path=rel_a
    )
    _write_manifest(
        st.uploads_root, upload_id="ub", source_filename=name, corpus_relative_path=rel_b
    )
    named = _executor().execute(
        "file_name_search",
        {"query": "Rapor.docx", "limit": 10},
        config={"AGENT_CORPUS_DIR": str(st.corpus_root)},
    )
    paths = {c["path"] for c in named["candidates"] if c.get("source_filename") == name}
    assert rel_a in paths
    assert rel_b in paths


def test_txt_upload_preserves_original_name_in_response_and_tools(tenant_app) -> None:
    app, root = tenant_app
    client = app.test_client()
    app.config["AUTH_BYPASS_CUSTOMER_ID"] = 101
    app.config["AUTH_BYPASS_USER_ID"] = 201

    original = "Saha Notları.txt"
    resp = client.post(
        "/agent/documents/upload",
        data={"file": (io.BytesIO(b"saha icerik"), original)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["source_filename"] == original
    assert body["display_name"] == original
    assert body["suggest_prompt"] == f"{original} dosyasını oku ve özetle"
    assert "extracted_data" not in body["message"]
    assert body["path"] not in body["message"] or body["path"] == original

    corpus = root / "101" / "corpus"
    cfg = {"AGENT_CORPUS_DIR": str(corpus)}
    named = _executor().execute(
        "file_name_search", {"query": "Saha Notları.txt", "limit": 10}, config=cfg
    )
    assert named["matched_total"] >= 1
    hit = named["candidates"][0]
    assert hit["source_filename"] == original
    read = _executor().execute("file_read", {"path": hit["path"]}, config=cfg)
    assert read["source_filename"] == original


def test_office_cache_reuse_response_keeps_new_original_name(tenant_app) -> None:
    app, _root = tenant_app
    client = app.test_client()
    app.config["AUTH_BYPASS_CUSTOMER_ID"] = 101
    app.config["AUTH_BYPASS_USER_ID"] = 201

    class Stub:
        def parse(self, data, filename=None):
            return ParseResult(
                text="parsed text",
                source_type="docx",
                images=(),
                meta={},
            )

    payload = b"PK\x03\x04same-bytes-content"
    with patch(
        "app.interfaces.web.agent_routes.document_upload.get_parser",
        return_value=Stub(),
    ), patch(
        "app.interfaces.web.agent_routes.document_upload.fill_image_placeholders",
        side_effect=lambda text, images, config=None: text,
    ):
        first = client.post(
            "/agent/documents/upload",
            data={"file": (io.BytesIO(payload), "Alpha Rapor.docx")},
            content_type="multipart/form-data",
        )
        assert first.status_code == 200
        j1 = first.get_json()
        assert j1["cached"] is False
        assert j1["source_filename"] == "Alpha Rapor.docx"
        assert "extracted_data" not in j1["message"]

        second = client.post(
            "/agent/documents/upload",
            data={"file": (io.BytesIO(payload), "Beta Kopya.docx")},
            content_type="multipart/form-data",
        )
    assert second.status_code == 200
    j2 = second.get_json()
    assert j2["cached"] is True
    assert j2["source_filename"] == "Beta Kopya.docx"
    assert j2["suggest_prompt"] == "Beta Kopya.docx dosyasını oku ve özetle"
    assert j2["path"] == j1["path"]
    assert "extracted_data" not in j2["message"]
