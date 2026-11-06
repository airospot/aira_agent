# Doğrulama

| Kontrol | Sonuç | Gözlem |
| --- | --- | --- |
| `python app.py` | | `127.0.0.1:5000` (veya `AIRA_DEV_PORT`), `GET /health` 200 |
| Statik | | `css/app.css`, `js/assistant.js` |
| UI | | `GET /agent/` ve `/assistant` |
| Tool kaydı | | `file_name_search`, `file_search`, `file_read`, `show_image` |
| Tool smoke | | Corpus `README.md` / sentetik dosya okuma + arama |
| Bellek | | PostgreSQL `DATABASE_URL` |
| Submission migration | | `python migrations/create_agent_submissions_table.py` (iki kez güvenli) |
| Auth/secret | | `SECRET_KEY` placeholder değil; auth açıkken `LOGIN_UI_URL` dolu |
| Idempotency | | Aynı `submission_id` çift POST → tek agent; farklı içerik → 400 |
| A00 pytest | | `pip install -r requirements-dev.txt && pytest -q` |
| A00 gerçek PG | | `A00_TEST_DATABASE_URL` veya `…/NATIVE_FLOW_A00_TEST` üzerinde migration + race |

## A00 UAT (manuel, tarayıcı)

1. İzole test DB’sinde migration’ları çalıştır (`conversation_memory`, embedding, `agent_submissions`, structured_memory).
2. `AUTH_DISABLED=1` ile uygulamayı başlat; `/agent/assistant` aç.
3. Yeni konuşma → sentetik `uat-guide.md` yükle → içerik sor → sayfayı yenile → geçmişten yeniden aç.
4. Aynı gönderimi çift tıkla / yeniden gönder; tek cevap, tek agent çalışması.
5. Normal F5 yenilemesi POST tekrarlamaz (GET); bu, çift submit’ten farklıdır.
6. Mevcut konuşmada da aynı idempotency davranışını dene.
