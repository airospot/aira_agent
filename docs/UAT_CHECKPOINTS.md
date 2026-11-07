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
