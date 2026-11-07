"""Tenant document storage: isolation, originals, download, migration."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import importlib.util

from app.domain.agents.flow.tooling import ToolExecutor, build_native_tool_registry
from app.domain.agents.flow.tooling.native_bootstrap import NATIVE_TOOL_NAMES
from app.domain.services.document_parsers.base import ParseResult
from app.shared.tenant_storage import TenantStorageError, resolve_tenant_storage
from tests.conftest import REPO_ROOT, load_app_py


def _load_migrate():
    import sys

    path = REPO_ROOT / "scripts" / "migrate_shared_corpus_to_tenant.py"
    name = "migrate_shared_corpus_to_tenant"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod.migrate


migrate = _load_migrate()


@pytest.fixture
def tenant_app(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://native:native@127.0.0.1:5432/NATIVE_FLOW_A00_TEST",
    )
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.setenv("SECRET_KEY", "tenant-storage-test-secret")
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


def _set_tenant(app, customer_id: int, user_id: int = 1) -> None:
    app.config["AUTH_BYPASS_CUSTOMER_ID"] = customer_id
    app.config["AUTH_BYPASS_USER_ID"] = user_id


def test_resolver_fail_closed_and_under_data_root(tmp_path):
    cfg = {"TENANT_DATA_ROOT": str(tmp_path / "tenants")}
    with pytest.raises(TenantStorageError):
        resolve_tenant_storage(None, cfg)
    with pytest.raises(TenantStorageError):
        resolve_tenant_storage(0, cfg)
    with pytest.raises(TenantStorageError):
        resolve_tenant_storage(True, cfg)  # type: ignore[arg-type]
    st = resolve_tenant_storage(7, cfg)
    assert st.corpus_root.is_dir()
    assert st.uploads_root.is_dir()
    assert st.data_root in st.corpus_root.parents or st.corpus_root == st.data_root / "7" / "corpus"
    assert str(st.customer_id) == "7"
    assert "7" in str(st.tenant_root)


def test_tenant_root_symlink_to_other_tenant_rejected(tmp_path):
    root = tmp_path / "tenants"
    cfg = {"TENANT_DATA_ROOT": str(root)}
    resolve_tenant_storage(2, cfg)  # victim tenant materializes
    # Attacker tenant id path is a symlink into tenant 2.
    (root / "1").symlink_to(root / "2")
    with pytest.raises(TenantStorageError, match="symlink"):
        resolve_tenant_storage(1, cfg)
    # Victim tree must not gain attacker-side writes via the link.
    assert not (root / "2" / "uploads" / "from-1").exists()


def test_uploads_root_symlink_to_other_tenant_rejected(tmp_path):
    root = tmp_path / "tenants"
    cfg = {"TENANT_DATA_ROOT": str(root)}
    st2 = resolve_tenant_storage(2, cfg)
    st1 = resolve_tenant_storage(1, cfg)
    # Replace tenant 1 uploads with symlink to tenant 2 uploads.
    import shutil

    shutil.rmtree(st1.uploads_root)
    (root / "1" / "uploads").symlink_to(st2.uploads_root)
    with pytest.raises(TenantStorageError, match="symlink"):
        resolve_tenant_storage(1, cfg)


def test_corpus_root_symlink_to_other_tenant_rejected(tmp_path):
    root = tmp_path / "tenants"
    cfg = {"TENANT_DATA_ROOT": str(root)}
    st2 = resolve_tenant_storage(2, cfg)
    st1 = resolve_tenant_storage(1, cfg)
    import shutil

    shutil.rmtree(st1.corpus_root)
    (root / "1" / "corpus").symlink_to(st2.corpus_root)
    with pytest.raises(TenantStorageError, match="symlink"):
        resolve_tenant_storage(1, cfg)


def test_two_tenants_same_name_physically_isolated(tenant_app):
    app, root = tenant_app
    client = app.test_client()

    _set_tenant(app, 101)
    r1 = client.post(
        "/agent/documents/upload",
        data={"file": (io.BytesIO(b"alpha-tenant-a"), "note.txt")},
        content_type="multipart/form-data",
    )
    assert r1.status_code == 200
    j1 = r1.get_json()
    assert j1["ok"] is True
    assert j1["path"] == "note.txt"
    sha_a = j1["original_sha256"]

    _set_tenant(app, 202)
    r2 = client.post(
        "/agent/documents/upload",
        data={"file": (io.BytesIO(b"beta-tenant-b"), "note.txt")},
        content_type="multipart/form-data",
    )
    assert r2.status_code == 200
    j2 = r2.get_json()
    assert j2["ok"] is True
    assert j2["original_sha256"] != sha_a

    a_file = root / "101" / "corpus" / "note.txt"
    b_file = root / "202" / "corpus" / "note.txt"
    assert a_file.read_bytes() == b"alpha-tenant-a"
    assert b_file.read_bytes() == b"beta-tenant-b"
    assert (root / "101" / "uploads" / j1["upload_id"]).is_dir()
    assert (root / "202" / "uploads" / j2["upload_id"]).is_dir()


def test_cross_tenant_download_and_image_denied(tenant_app):
    app, root = tenant_app
    client = app.test_client()

    _set_tenant(app, 101)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        + b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    img_dir = root / "101" / "corpus" / "images"
    img_dir.mkdir(parents=True)
    (img_dir / "secret.png").write_bytes(png)

    up = client.post(
        "/agent/documents/upload",
        data={"file": (io.BytesIO(b"owned-by-a"), "owned.txt")},
        content_type="multipart/form-data",
    )
    upload_id = up.get_json()["upload_id"]
    dl_a = client.get(f"/agent/documents/{upload_id}/original")
    assert dl_a.status_code == 200
    assert dl_a.data == b"owned-by-a"
    assert "no-store" in (dl_a.headers.get("Cache-Control") or "")
    assert dl_a.headers.get("X-Content-Type-Options") == "nosniff"
    assert "attachment" in (dl_a.headers.get("Content-Disposition") or "").lower()

    img_a = client.get("/agent/corpus/images/secret.png")
    assert img_a.status_code == 200
    assert img_a.data == png

    _set_tenant(app, 202)
    assert client.get(f"/agent/documents/{upload_id}/original").status_code == 404
    assert client.get("/agent/corpus/images/secret.png").status_code == 404


def test_parse_failure_keeps_original(tenant_app):
    app, root = tenant_app
    client = app.test_client()
    _set_tenant(app, 101)

    class Boom:
        def parse(self, data, filename=None):
            raise RuntimeError("explode")

    with patch(
        "app.interfaces.web.agent_routes.document_upload.get_parser",
        return_value=Boom(),
    ):
        resp = client.post(
            "/agent/documents/upload",
            data={"file": (io.BytesIO(b"PK\x03\x04fake"), "broken.docx")},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error"] == "parse_failed"
    assert body["original_preserved"] is True
    assert body["status"] == "failed"
    upload_id = body["upload_id"]
    original = root / "101" / "uploads" / upload_id / "broken.docx"
    assert original.is_file()
    assert hashlib.sha256(original.read_bytes()).hexdigest() == body["original_sha256"]
    manifest = json.loads(
        (root / "101" / "uploads" / upload_id / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "failed"
    # No partial publish into corpus
    extracted = root / "101" / "corpus" / "extracted_data"
    assert not extracted.exists() or list(extracted.glob("broken*")) == []


def test_tenant_hash_cache_still_stores_original(tenant_app):
    app, root = tenant_app
    client = app.test_client()
    _set_tenant(app, 101)
    payload = b"PK\x03\x04same-bytes"

    class OkParser:
        def parse(self, data, filename=None):
            return ParseResult(
                text="hello from doc",
                source_type="docx",
                images=(),
                meta={},
            )

    with patch(
        "app.interfaces.web.agent_routes.document_upload.get_parser",
        return_value=OkParser(),
    ), patch(
        "app.interfaces.web.agent_routes.document_upload.fill_image_placeholders",
        side_effect=lambda text, images, config=None: text,
    ):
        first = client.post(
            "/agent/documents/upload",
            data={"file": (io.BytesIO(payload), "dup.docx")},
            content_type="multipart/form-data",
        )
        assert first.status_code == 200
        j1 = first.get_json()
        assert j1["cached"] is False
        second = client.post(
            "/agent/documents/upload",
            data={"file": (io.BytesIO(payload), "dup.docx")},
            content_type="multipart/form-data",
        )
    assert second.status_code == 200
    j2 = second.get_json()
    assert j2["cached"] is True
    assert j2["upload_id"] != j1["upload_id"]
    assert (root / "101" / "uploads" / j2["upload_id"] / "dup.docx").is_file()
    assert j2["original_sha256"] == j1["original_sha256"]
    assert j2["path"] == j1["path"]


def test_concurrent_same_names_do_not_clobber(tenant_app):
    app, root = tenant_app
    client = app.test_client()
    _set_tenant(app, 101)
    r1 = client.post(
        "/agent/documents/upload",
        data={"file": (io.BytesIO(b"one"), "same.txt")},
        content_type="multipart/form-data",
    )
    r2 = client.post(
        "/agent/documents/upload",
        data={"file": (io.BytesIO(b"two"), "same.txt")},
        content_type="multipart/form-data",
    )
    j1, j2 = r1.get_json(), r2.get_json()
    assert j1["upload_id"] != j2["upload_id"]
    assert j1["path"] != j2["path"]
    assert (root / "101" / "corpus" / Path(j1["path"])).read_bytes() == b"one"
    assert (root / "101" / "corpus" / Path(j2["path"])).read_bytes() == b"two"


def test_tools_and_symlink_cross_tenant_rejected(tenant_app):
    app, root = tenant_app
    a_corpus = root / "101" / "corpus"
    b_corpus = root / "202" / "corpus"
    a_corpus.mkdir(parents=True)
    b_corpus.mkdir(parents=True)
    secret = b_corpus / "secret.txt"
    secret.write_text("leak-b", encoding="utf-8")
    (a_corpus / "escape.txt").symlink_to(secret)
    (a_corpus / "ok.txt").write_text("only-a", encoding="utf-8")

    ex = ToolExecutor(build_native_tool_registry(), permitted_names=NATIVE_TOOL_NAMES)
    cfg_a = {"AGENT_CORPUS_DIR": str(a_corpus)}
    named = ex.execute(
        "file_name_search", {"query": "escape", "limit": 10}, config=cfg_a
    )
    assert named["matched_total"] == 0
    read = ex.execute("file_read", {"path": "escape.txt"}, config=cfg_a)
    assert read["status"] in {"invalid_path", "not_found"}
    ok = ex.execute("file_read", {"path": "ok.txt"}, config=cfg_a)
    assert ok["status"] == "ok"
    assert "only-a" in (ok.get("content") or "")


def test_form_spoof_customer_cannot_switch_tenant(tenant_app):
    app, root = tenant_app
    client = app.test_client()
    _set_tenant(app, 101)
    resp = client.post(
        "/agent/documents/upload",
        data={
            "file": (io.BytesIO(b"bound-to-101"), "spoof.txt"),
            "customer_id": "202",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert (root / "101" / "corpus" / "spoof.txt").is_file()
    assert not (root / "202" / "corpus" / "spoof.txt").exists()


def test_path_traversal_upload_id_download(tenant_app):
    app, _root = tenant_app
    client = app.test_client()
    _set_tenant(app, 101)
    assert client.get("/agent/documents/../101/original").status_code in {404, 405}
    assert client.get("/agent/documents/..%2F202/original").status_code == 404


def test_execution_context_uses_tenant_corpus(tmp_path):
    from app.domain.agents.run.factory import build_execution_context

    cfg = {"TENANT_DATA_ROOT": str(tmp_path / "tenants"), "AGENT_CORPUS_DIR": "/shared/liar"}
    ctx = build_execution_context(customer_id=5, user_id=9, config=cfg)
    assert str(tmp_path / "tenants" / "5" / "corpus") == ctx.corpus_root
    assert ctx.runner_config["AGENT_CORPUS_DIR"] == ctx.corpus_root
    assert "/shared/liar" not in ctx.corpus_root


def test_migration_dry_run_and_idempotent_apply(tmp_path):
    source = tmp_path / "shared"
    (source / "extracted_data" / "doc1").mkdir(parents=True)
    (source / "notes.txt").write_text("hello", encoding="utf-8")
    (source / "extracted_data" / "doc1" / "content.md").write_text("# x\n", encoding="utf-8")
    (source / "extracted_data" / "doc1" / "meta.json").write_text(
        json.dumps({"source_filename": "doc1.docx"}),
        encoding="utf-8",
    )
    dest_root = tmp_path / "tenants"

    dry = migrate(source=source, tenant_id=9, tenant_data_root=dest_root, apply=False)
    assert dry.copied
    assert any("original_unavailable" in x for x in dry.original_unavailable)
    assert not (dest_root / "9" / "corpus" / "notes.txt").exists()

    first = migrate(source=source, tenant_id=9, tenant_data_root=dest_root, apply=True)
    assert (dest_root / "9" / "corpus" / "notes.txt").read_text(encoding="utf-8") == "hello"
    assert "notes.txt" in first.copied

    second = migrate(source=source, tenant_id=9, tenant_data_root=dest_root, apply=True)
    assert "notes.txt" in second.skipped_exists
    assert not second.errors
    assert (dest_root / "9" / "corpus" / "notes.txt").read_text(encoding="utf-8") == "hello"
