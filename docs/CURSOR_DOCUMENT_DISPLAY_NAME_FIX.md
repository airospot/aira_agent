# PR #4 — Kullanıcıya orijinal belge adı

Durum: implementasyon branch’te; **merge/A03 yok**. Gerçek model/browser UAT ayrı.

## Yapılan

- `app/shared/document_source_identity.py`: meta.json + upload manifest’ten sandboxed `source_filename` / `display_name`
- Tools: `file_read`, `file_search`, `file_name_search`, `show_image` sonuç şemaları + identity alanları
- `file_name_search` orijinal adı da eşler; teknik corpus path döner
- Cache reuse farklı orijinal adları sessizce tek ada düşürmez (ambiguous / alternate)
- Prompt: kullanıcı başlığında gerçek ad; `content.md` başlık olmasın
- Upload JSON: `suggest_prompt` + kullanıcı mesajı gerçek adla; `assistant.js` textarea artık teknik path yazmıyor
- Trace/history özetleri identity alanlarını taşıyor
- Testler: `tests/test_document_source_identity.py` (+ suite 114)

Önceki kapsam (escaped-pipe, tenant-root symlink) aynı branch’te kalır.
