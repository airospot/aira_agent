# A04 analiz cevabı kaybı — inceleme ve düzeltme

2026-11-07; başlangıç HEAD `abe897b`. Yerel düzeltmeler commit edilmedi. Merge/A05 yok.

## Doğrulanan kanıt

Çalışan Flask stdout/stderr hedefi terminal `/dev/pts/1`; bulunan `/tmp/nkf-app.log` güncel olayları içermiyor. Canlı terminal geçmişi bu oturumdan geri okunamadı. Bunun yerine yerel uygulama DB'sinde yalnız salt okunur teşhis sorguları kullanıldı.

Ekrandaki 05 belgesinin son iki submission'ı completed; flow_status=ERROR. İlkinde `Agent error: FlowLlmClientError`, sonrakinde `Agent error: ValidationError` var. İkisinin de assistant_memory_id'si boş. Kullanıcı mesajı kalırken assistant mesajı yazılmıyor. Bu nedenle boş ekran “halen çalışıyor” anlamına gelmiyor.

Kesin görünürlük kusuru: memory bridge ERROR durumunda assistant metnini kaydetmiyor; template, conversation_turns doluyken agent_notice'ı göstermiyor. Recovery overlay ise yalnız agent_reply ekliyor. Bu üç davranış hata bildiriminin kaybolmasına neden oluyor. Eski error durumlarında memory complete hesabı da bu eksikliği işaretlemeyebiliyor.

Eski ValidationError'ın stage/validator ayrıntısı submission sonucunda korunmamış; ham exception/model cevabı da eldeki logda yok. Bu yüzden geçmişteki tek validation hatasının model kararı mı tool schema'sı mı olduğu kesin iddia edilmez. Aynı istek düzeltmeden önce de temiz konuşmada bir kez başarılı oldu; aralıklı davranış mevcut.

## Yerel değişiklikler

- Native Ollama body.format, gönderilen aktif decision_schema'yı kullanıyor (terminal-only dahil). Karar şeması bulunmayan bağımsız çağrıda JSON modu kullanılıyor. Prompt'a yazılmış şemaya uyması tek başına beklenmiyor.
- Model decision ValidationError kodlu invalid_model_decision STOP_INCOMPLETE ve kısa Türkçe kullanıcı bildirimi üretiyor. İkinci run/limitsiz retry eklenmedi; veri uydurulmuyor.
- memory bridge ERROR bildirimini assistant turn olarak kaydediyor; embedding üretilmiyor. Böylece geçmiş ve trace ilişkisi korunuyor.
- Dolu transcript'te de recovery agent_notice görünür; aynı metin assistant turn olarak varsa ikinci kez basılmıyor. Eski başarısız submission'lar DB değiştirilmeden görünür hâle geliyor.
- `tests/test_a04_analysis_failures.py`: native schema aktarımı, kodlu duruş, ERROR persist ve dolu transcript notice/dedupe regresyonları.

## Doğrulama

- İzole NATIVE_FLOW_A00_TEST dahil suite: **171 passed**, skip yok.
- Gerçek qwen3.5:9b, mevcut skill, 05_multipage_cross_reference.docx: yeni bağlamda ve önceki kullanıcı mesajlı bağlamda iki kez file_name_search → file_read → ANSWER; 5.43 / 5.54 sn. Kalıcı konuşma/submission yazılmadı; belge metni loglanmadı.
- Eski başarısız submission canonical GET: HTTP 200, eski ValidationError notice artık görünür. Uygulama test client'ı ile doğrulandı; LLM yeniden çalıştırılmadı.

## Cursor teslimi / sahip UAT

Yalnız ilgili dört uygulama dosyası + yeni regresyon testi + bu audit dokümanını inceleyip ayrı fix commit olarak teslim et; kullanıcıya ait diğer untracked promptları topluca stage etme. Gerçek model kontrolü belirli senaryoların kanıtıdır, genel kalite garantisi değildir. Kullanıcı normal tarayıcıda Belge inceleme modunda aynı 05 dosyasını tekrar inceletsin; cevap ve file_read trace'i görünmeli. Sahip UAT onayı olmadan PASS/merge/A05 yok.
