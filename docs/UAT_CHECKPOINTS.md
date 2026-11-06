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
- A00–A09 henüz bu plan kapsamında uygulanıp kabul edilmedi.
- İlk aktif aşama: A00.

## A00 teknik kayıt

- Aşama: A00
- Başlangıç commit: `99de9f400c48f422348aae4af2d9025b68a7ff27`
- Teslim commit SHA: PR / teslim raporunda (self-SHA amend yok)
- GitHub dalı ve PR: `codex/agent-a00-baseline-checks` (URL teslimde)
- Çalıştırma tarihi ve test profili: 2026-11-06; yerel Linux; `NATIVE_FLOW_A00_TEST` / unit pytest
- Otomatik test komutları ve sonuçları: `A00_TEST_DATABASE_URL=…/NATIVE_FLOW_A00_TEST pytest -q` → **21 passed**
- Gerçek PostgreSQL testi: geçti (`NATIVE_FLOW_A00_TEST`; migration×2 + concurrent `try_begin_processing` tek kazanan + propose idempotency)
- Gerçek MCP entegrasyon testi: uygulanmaz
- Gerçek model testi: uygulanmaz (unit testlerde LLM yok)
- İnceleme: BEKLEMEDE
- Manuel UAT sahibi: proje sahibi
- Manuel UAT: BEKLEMEDE
- Beklenen davranış ve gözlenen davranış: symlink sandbox reddi; migration env önceliği; SECRET_KEY/LOGIN_UI_URL kapıları; submission tek rezervasyon + replay; persist hatasında `assistant_text`/`agent_reply` submission’da kalır
- İlgili run/submission kimlikleri ve güvenli kanıt: test ID’leri `a00-*` (secret yok)
- Bilinen sınırlar ve açık kusurlar: TOCTOU symlink yarışı iddia edilmez; production DB’de race test edilmez
- Geri alma: önceki kabul `99de9f4` / `main`; şema için izole test DB’de `DROP TABLE IF EXISTS agent_submissions`; production veri silinmez
- Sonraki aşamaya geçiş talimatı: beklemede (inceleme + manuel UAT PASS ve merge sonrası)
