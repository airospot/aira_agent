# Konuşma devamlılığı ve tablo render düzeltmesi

İncelenen HEAD: `b4f88011d95b4876d145560114110c49145a90fe`.
Kapsam: küçük, ayrı düzeltme; yeni agent loop/store/framework yok. Merge ve A03 yok.

## Doğrulanan bulgular

1. `assistant_markdown.render_assistant_markdown` (eski: `safe_markdown`) tablo tanımıyordu. Geçerli pipe tablo girdisi `<table>` yerine üç `<p>` üretiyordu. CSS'de table-scroll desteği mevcut; sorun yalnız CSS değil.
2. `AgentRunService` geçmişi memory bridge'den alıp runner'a geçiriyor. `request_model_decision` güncel request ve conversation'ı LLM client'a iletiyor. Capture client ile bu aktarım doğrulandı; gerçek sorunlu isteğin DB geçmişi veya gerçek model davranışı bu kontrolle doğrulanmış değildir.
3. Bridge son N mesajı kronolojik gönderiyor (varsayılan 10 mesaj). UI tam transcript gösteriyor; modelin gördüğü pencere farklı. `turns` ve `active_conversation.turns` aynı geçmişi payload'da iki kez içeriyor.
4. System prompt'ta açık dosya yolu için file_read talimatı var; son açık belgeye takip referansı çözme önceliği yok. Historical tool refs aktif belge sayılmıyor. Bu bulgular iyileştirme noktalarıdır; ekranlardaki tekrarın kesin kök nedeni henüz kanıtlanmadı.

## Cursor uygulama sırası

1. Sentetik aynı-session senaryosunu üret: A oku → B oku → “bu belgedeki görseli göster” → B'nin tam yoluyla açıklama. Memory yükleme, client'a giden güncel request/geçmiş sırası ve dönen kararları kontrol et. Son request'in değişmediğini, persist sonrası son turn'lerin sonraki isteğe geldiğini doğrula. Üretim belge metni/secret loglama; gerçek UAT gerekirse izinli sentetik fixture kullan.
2. Bulguyla uyumlu en küçük düzeltmeyi yap. Referans önceliği: güncel açık dosya yolu > mevcut session'daki en son açık belge > gerçekten belirsizse CLARIFY. Eski CLARIFY cevabını yeni kullanıcı açıklamasına rağmen tekrarlama. Belge değişince referans değişsin. Yeni konuşmaya başka session/LTM belgesini otomatik taşıma. Geçmiş belge yolu içerik kanıtı değildir; gerekli içeriği file_read/show_image ile yeniden doğrula. Türkçe kelimelere özel if/regex yönlendirme veya global active_document değişkeni ekleme.
3. Güvenli Markdown renderer'a sınırlı pipe-table desteği ekle. Hücre kaçışını, mevcut güvenli link/görsel davranışını koru; ham HTML açma. Kod bloğundaki pipe satırlarını tablo yapma. Geçersiz/belirsiz tabloyu güvenli metin olarak bırak. Table-scroll wrapper kullan.
4. Regresyon: A→B referansı, tam yol ile clarification recovery, yeni session izolasyonu, history window sınırı; normal tablo, hücrede zararlı HTML/link, kod bloğunda tablo, mevcut show_image render. Fake model testi prompt taşımasını kanıtlar; gerçek konuşma kalitesini kanıtladığını söyleme.
5. İlgili testleri ve mevcut suite'i çalıştır; SHA, diff, sonuçlar ve gerçek-model testinin yapılıp yapılmadığını bildir. DUR; merge/A03 yok.

## Manuel kabul

- Kullanıcı tenant 1'de orijinal kayıt + çıkarma ve tenant 1 fiziksel klasörünü PASS kabul etti (2026-11-07).
- Başka tenant kontrolü kullanıcı isteğiyle atlandı; PASS olarak işaretlenmez. Önceden raporlanan root-symlink kusuru ayrıca açık takip edilir.
- Sonraki UAT: yeni konuşmada A özeti → B özeti → “bu belgedeki tabloyu göster” (B) → açık A yolu (A) → yenile/takip; yeni konuşmada “bu belge” (uygun açıklama isteği). Tablo ekranda gerçek tablo olmalı.
