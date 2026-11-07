# Agent geliştirme UAT kayıtları

Cursor teknik kanıtı yazar; manuel UAT ve inceleme sonuçlarını yalnız ilgili kişinin açık bildiriminden sonra kaydeder. Henüz test edilmemiş durumlar PASS değildir. Her aşama için aşağıdaki şablon kopyalanır. Gerçek secret, JWT, müşteri belgesi ve DB connection string eklenmez.

## Aşama kayıt şablonu

- Aşama:
- Başlangıç commit:
- Teslim commit SHA:
- GitHub dalı ve PR:
- Çalıştırma tarihi ve test profili:
- Otomatik test komutları ve sonuçları:
- Gerçek PostgreSQL testi: beklemede / geçti / başarısız
- Gerçek MCP entegrasyon testi: uygulanmaz / beklemede / geçti / başarısız
- Gerçek model testi: beklemede / geçti / başarısız
- İnceleme: beklemede / değişiklik gerekli / kabul
- Manuel UAT sahibi: proje sahibi
- Manuel UAT: beklemede / geçti / başarısız
- Beklenen davranış ve gözlenen davranış:
- İlgili run/submission kimlikleri ve güvenli kanıt:
- Bilinen sınırlar ve açık kusurlar:
- Geri alma: önceki kabul edilmiş commit; schema değişikliği varsa veri kaybetmeyen dönüş adımları
- Sonraki aşamaya geçiş talimatı: beklemede

İnceleme/UAT sonrası kod değişirse yeni SHA ayrı kaydedilir ve etkilenen testler tekrarlanır. Önceki sonuçlar silinmez. Test komutu çalışmadıysa nedeni yazılır; test varlığı veya mock sonucu gerçek entegrasyonun yerine geçmez.

## Manuel test fixture’ları

`uat-guide.md` içeriği:

```text
# UAT rapor kuralları
Rapor dili Türkçe.
Para birimi TRY; farklı para birimleri birleştirilmez.
Tarih aralığı ve kaynaklar raporda belirtilir.
Eksik bilgi uydurulmaz.
Örnek belge kalemleri: A 100.00, B 250.50, C 49.50.
Bu metindeki kalemler test örneğidir; gerçek DB sonucu yerine kullanılmaz.
Teslimat tarihi bu belgede belirtilmemiştir.
```

UAT corpus’una yalnız bu sentetik içerik ve gerekli küçük sentetik görsel yüklenir. A08 DB fixture’ı seed komutuyla ayrı oluşturulur. İş verisi testinde belge içindeki örnek rakamları tekrar etmek DB çağrısı kanıtı sayılmaz.

## Başlangıç durumu

- Plan başlangıcı: `99de9f400c48f422348aae4af2d9025b68a7ff27`.
- A00 kabul edilmiş PR head: `f1e152a8dd35bfd7d9b8a86ecca197ec374daec8`.
- A00 merge commit (main): `535cb0e749accdb9e8cd5ede9c37f732c08e0f84`.
- İlk açık aşama (bu teslim): A01.

## A00 teknik kayıt

- Aşama: A00
- Başlangıç commit: `99de9f400c48f422348aae4af2d9025b68a7ff27`
- Teslim / kabul edilen PR head SHA: `f1e152a8dd35bfd7d9b8a86ecca197ec374daec8`
- Merge SHA (main): `535cb0e749accdb9e8cd5ede9c37f732c08e0f84`
- GitHub dalı ve PR: `codex/agent-a00-baseline-checks` — https://github.com/airospot/aira_agent/pull/1 (birleştirildi)
- Çalıştırma tarihi ve test profili: 2026-11-06; yerel Linux; `NATIVE_FLOW_A00_TEST` / unit pytest
- Otomatik test komutları ve sonuçları: `A00_TEST_DATABASE_URL=…/NATIVE_FLOW_A00_TEST pytest -q` → **33 passed**
- Gerçek PostgreSQL testi: geçti (`NATIVE_FLOW_A00_TEST`)
- Gerçek MCP entegrasyon testi: uygulanmaz
- Gerçek model testi: uygulanmaz (unit testlerde LLM yok)
- İnceleme: kabul (`f1e152a`)
- Manuel UAT sahibi: proje sahibi
- Manuel UAT: kabul (`f1e152a`)
- Beklenen davranış ve gözlenen davranış: A00 hardening + recovery kabul edildi
- İlgili run/submission kimlikleri ve güvenli kanıt: test ID’leri `a00-*` (secret yok)
- Bilinen sınırlar ve açık kusurlar: TOCTOU symlink yarışı iddia edilmez
- Geri alma: `535cb0e` öncesi `f1e152a` / `99de9f4`
- Sonraki aşamaya geçiş talimatı: A01 (merge sonrası)

## A01 teknik kayıt

- Aşama: A01
- Başlangıç commit: `535cb0e749accdb9e8cd5ede9c37f732c08e0f84` (A00 merge)
- Teslim commit SHA: PR / teslim raporunda (self-SHA amend yok)
- GitHub dalı ve PR: `codex/agent-a01-tool-registry` (URL teslimde)
- Çalıştırma tarihi ve test profili: 2026-11-07; yerel Linux; `NATIVE_FLOW_A00_TEST` + unit
- Otomatik test komutları ve sonuçları: `A00_TEST_DATABASE_URL=…/NATIVE_FLOW_A00_TEST pytest -q` → **45 passed** (inceleme düzeltmesi: boş izin + schema kopyası)
- Gerçek PostgreSQL testi: A00 regresyonu için `NATIVE_FLOW_A00_TEST` geçti (A01 DB şema değişikliği yok)
- Gerçek MCP entegrasyon testi: uygulanmaz
- Gerçek model testi: uygulanmaz (scriptlenmiş karar / mock LLM)
- İnceleme: BEKLEMEDE
- Manuel UAT sahibi: proje sahibi
- Manuel UAT: BEKLEMEDE
- Beklenen davranış ve gözlenen davranış: dört native araç registry/executor üzerinden; if/elif yok; sandbox/katalog/event/trace korunur
- İlgili run/submission kimlikleri ve güvenli kanıt: sentetik corpus fixture (secret yok)
- Bilinen sınırlar ve açık kusurlar: timeout/retry metadata yalnız bilgi; A03 kontrolü iddia edilmez; MCP/skill/Run API yok
- Geri alma: `main` @ `535cb0e`; şema değişikliği yok
- Sonraki aşamaya geçiş talimatı: beklemede

## A01 runtime hotfix (offset + embed + GPU kanıt)

- Aşama: A01 hotfix (A02 yok)
- Altyapı: agent repo dışı — `/home/airadev/Documents/Aira-Full-Stack/server_utlities/docker-compose.stack.yml` (yalnız ollama recreate notu; volume `/data/models` korundu)
- Uygulama teslim SHA: `d294305e4f1e21976d5efb7226b767294dc5b522`
- GitHub dalı ve PR: `codex/agent-a01-tool-registry` / PR #2
- Otomatik test: `pytest -q` → önceki 45 + offset/embed/dsn testleri
- Gerçek GPU/model: ayrı kanıt (mock değil); inceleme/UAT: **BEKLEMEDE**
- Backfill komutu sunuldu; onaysız toplu çalıştırılmadı
- Sonraki: merge/A02 yok — inceleme + kısa manuel UAT bekleniyor

## A01 birleştirme

- Merge SHA (main): `29137b4c62a6cf9af68d808506f9206c05810437`
- PR: https://github.com/airospot/aira_agent/pull/2
- Otomatik test (merge öncesi): `A00_TEST_DATABASE_URL=…/NATIVE_FLOW_A00_TEST pytest -q` → **62 passed**

## A02 teknik kayıt

- Aşama: A02
- Başlangıç commit: `29137b4c62a6cf9af68d808506f9206c05810437`
- Teslim commit SHA: `72c465c03b5b65cb81bbeaa7daf907e0c88f099c`
- İnceleme düzeltmesi SHA: `53c212cf3cd5ecbd723b7f4b30654839e6a5f502`
- GitHub dalı ve PR: `codex/agent-a02-run-service` — https://github.com/airospot/aira_agent/pull/3
- Merge SHA (main): `10bfa146a90e8ed28bd2fc6a1040305ed9d3f385`
- Çalıştırma tarihi ve test profili: 2026-11-07; yerel Linux; `NATIVE_FLOW_A00_TEST` + fake servis testleri
- Otomatik test (merge öncesi): `A00_TEST_DATABASE_URL=…/NATIVE_FLOW_A00_TEST pytest -q` → **80 passed**
- Manuel UAT: **KABUL** (PNG isim arama + show_image)
- İnceleme: tamamlandı (merge)

## Tenant document storage teknik kayıt

- Aşama: tenant-document-storage (A03 değil)
- Başlangıç commit: `10bfa146a90e8ed28bd2fc6a1040305ed9d3f385` (A02 merge)
- Teslim commit SHA: `98c10eb2e5959945eeb42de41886c0cbcb96328b`
- GitHub dalı ve PR: `codex/tenant-document-storage` — https://github.com/airospot/aira_agent/pull/4 (draft)
- Çalıştırma: 2026-11-07; `NATIVE_FLOW_A00_TEST`
- Otomatik test: `A00_TEST_DATABASE_URL=…/NATIVE_FLOW_A00_TEST pytest -q` → **91 passed**
- Dizin: `data/tenants/<customer_id>/{uploads,corpus}`; orijinal indirme `/agent/documents/<upload_id>/original`
- Gerçek eski veri migration: **uygulanmadı** (script dry-run varsayılan; `--apply` bu teslimde çalıştırılmadı)
- İnceleme: **BEKLEMEDE**
- Manuel UAT: **BEKLEMEDE**
- Kısa UAT: DOCX+TXT yükle → orijinal indir → çıkarımı sor/görsel göster → ayrı tenant’ta arama/URL erişilemez → profili geri al
- Merge / A03: yok

## A03 teknik kayıt

- Aşama: A03 (run budgets + bounded context)
- Başlangıç commit: `2febf5d1cfa16445f1f1c0e6e53f1997531dfe26` (PR #4 head; merge yetkisi bu kayıtta yok)
- Teslim commit SHA: (push sonrası)
- GitHub dalı ve PR: `codex/agent-a03-run-budgets` (draft)
- Çalıştırma tarihi ve test profili: 2026-11-07; yerel Linux; fake monotonic clock/client; `NATIVE_FLOW_A00_TEST`
- Otomatik test: `A00_TEST_DATABASE_URL=…/NATIVE_FLOW_A00_TEST pytest -q` → **128 passed**
- Gerçek PostgreSQL testi: geçti (`NATIVE_FLOW_A00_TEST` URL ile suite; A03 şema migration yok)
- Gerçek MCP entegrasyon testi: uygulanmaz
- Gerçek model testi: beklemede
- İnceleme: **BEKLEMEDE**
- Manuel UAT sahibi: proje sahibi
- Manuel UAT: **BEKLEMEDE**
- Uygulanan timeout/bütçe (`.env` / `.env.example`; kodda numeric default yok):
  - `AGENT_MAX_STEPS=8`
  - `AGENT_RUN_TIMEOUT_SECONDS=180` (yalnız runner/agent loop; upload/OCR/DB/HTTP request bütünü değil)
  - `AGENT_TOOL_TIMEOUT_SECONDS=15` (cooperative native slice)
  - `AGENT_MAX_OBSERVATION_BYTES=65536`
  - `AGENT_MAX_CONTEXT_BYTES=131072`
  - `AGENT_MAX_TOOL_RETRIES=1`
- Otomatik kanıt: max_steps=1 terminal-only; deadline LLM/tool engeli; context/observation UTF-8 byte limit + identity koruma; duplicate history yok; native duplicate/retry/write-no-retry; persist/replay
- Bilinen sınırlar: urllib timeout kesin wall-clock kill değildir; native sync tool zorla kesilmez; submission_timeout ≠ run deadline
- Geri alma: branch sil / önceki `2febf5d`; şema migration yok
- Merge / A04: yok

### A03 manuel UAT talimatı (kullanıcı)

1. Normal `.env` profili: `04_multilingual_unicode.docx` özeti → “bu belgedeki denetim sıklığı?”; sonra `03_lowres_scan_inside_word.docx` özeti → “bu belgedeki görseli göster”. Gerçek belge adı / takip bozulmamalı.
2. Geçici override `AGENT_MAX_STEPS=1` (yalnız app config/.env; shell prefix’e güvenme): yeni belge okuma → uydurma özet yerine anlaşılır STOP/açıklama. Flaky gerçek-model hızıyla PASS üretme.
3. Sentetik büyük TXT: kısaltma görünür, kaynak adı korunur. Yenileme / yeni konuşma davranışı korunur.
4. Override’ları geri al; normal `.env` commit edilmez.
