# Cursor A01 uygulama talimatı

Bu aşamanın amacı mevcut dört aracı ortak registry ve executor üzerinden çalıştırmaktır. Kullanıcıya görünen davranış değişmez. Uygulama sade tutulur; A02 ve sonraki aşamalar uygulanmaz.

## Cursor’a verilecek prompt

```text
Önce kaynakları oku; yalnız plan metnine veya önceki teslim özetine dayanma:
- docs/AGENT_EVOLUTION_PLAN.md içindeki A01 ve aşama teslim kuralları
- app/domain/agents/flow/execution/run_knowledge_agent.py
- app/domain/agents/flow/execution/run_agent_loop.py
- app/domain/agents/flow/tools/ altındaki dört execute.py, tool.json ve result.json
- karar doğrulama, event/trace üretimi ve bunlara bağlı mevcut testler
- varsa geçerli AGENTS.md

A00 durumu:
Kod incelemesi ve kullanıcının manuel UAT kabulü tamamlandı.
Kabul edilmiş PR head: f1e152a8dd35bfd7d9b8a86ecca197ec374daec8.
GitHub PR #1 son kontrolde draft/açıktı. GitHub eklentisi ready işlemi için
Resource not accessible by integration hatası verdi; merge gerçekleşmedi.

1. PR #1'in güncel durumunu kontrol et. Açıksa head'in tam olarak yukarıdaki
   kabul edilen SHA olduğunu doğrula, ready yap ve normal merge commit ile
   birleştir. Head farklıysa veya merge engellenirse durumu bildir; yeni kodu
   kabul edilmiş varsayma. Zaten birleşmişse sonucu doğrula. Force veya admin
   bypass kullanma. Birleştirme başarılı değilse A01'i başlatma.
2. Güncel main'i al; gerçek merge SHA'sını başlangıç olarak kaydet.
   Temiz tabandan codex/agent-a01-tool-registry dalını aç. Kullanıcının ilgisiz
   yerel değişikliklerini silme veya stage etme.
3. Yalnız A01'i uygula. A00 kayıtlarının inceleme/UAT kabulünü bu yeni aşamadaki
   doküman güncellemesinde kabul edilmiş f1e152a SHA'sına bağlayarak kaydet.

Sade tasarım:
- ToolSpec: mevcut tool tanımı, giriş/çıkış şemaları ve çağrılabilir handler'ı
  bir arada tutan küçük bir yapı. İhtiyaç olan version/metadata doğrudan
  mevcut şema kimliklerinden veya açık kayıttan alınsın.
- ToolRegistry: ada göre kayıt/bulma ve model kataloğu üretme. Aynı ismi iki kez
  kaydetmek açık hata olsun. Tanımlar yüklenirken şemalar doğrulansın.
- ToolExecutor: kayıtlı + izin verilmiş araç kontrolü, giriş doğrulama,
  handler çağrısı ve çıkış doğrulama. İzin listesi açıkça verilsin; registry'de
  olmak kendiliğinden çalıştırma izni vermesin. Yetkisiz/bozuk giriş handler'ı
  çalıştırmamalı. Kayıtlı mutable şema/dict'ler model veya handler tarafından
  değiştirilip sonraki run'ı etkilememeli.
- Native bootstrap: mevcut dört aracı açık Python kayıtlarıyla bağla.
  Arbitrary klasör tarayıp kod import eden plugin sistemi yazma.
- Runner, model kataloğunu ve dispatch'i aynı registry kaynağından alsın.
  _execute_tool içindeki araç seçen if/elif zinciri kalksın. Mevcut event'ler,
  karar trace'i ve güvenli observation özetleri korunsun.

Uyumluluk:
- file_name_search, file_search, file_read, show_image adları, argümanları,
  tool.json/result.json sözleşmeleri, sandbox davranışı ve config aktarımı aynı.
- Ortak ToolResult sınırı mevcut dict sonuçlarını kayıpsız taşıyabilir.
  Bu aşamada her aracın cevabını yeni bir envelope'a zorla dönüştürme.
  Özellikle content, candidates, path, display_url, status, error ve kaynak
  alanlarını model/UI yolunda kaybetme. Gerekirse küçük bir tip/adapter yeterli.
- Mevcut execute_* fonksiyonlarının doğrudan kullanımını bozma.
  Doğrulama executor'a eklenirken doğrudan çağrıların korumasını kaldırma.
- Teknik hata ile tool'un geçerli not_found/invalid_path gibi sonucu ayrımı
  korunsun; mevcut loop'un terminal, hata ve tekrar davranışları değişmesin.
- Future timeout/side-effect/retry alanları eklenirse yalnız metadata olsun;
  A03 kontrol mekanizmaları uygulanmış gibi sunma.

Kapsam dışında:
Yeni framework/dependency, async/worker, MCP, skill loader, Run API,
AgentRunService/ExecutionContext, yeni DB tabloları, UI tasarımı ve prompt
davranışı değişikliği. DB idempotency/recovery/auth kodunu bu refactor'a katma.

Anlamlı testler:
- Bilinmeyen araç, kayıtlı fakat izinsiz araç, duplicate kayıt.
- Bozuk argümanda handler çağrılmaması; bozuk sonuçta açık doğrulama hatası.
- Dört native aracın sentetik corpus üzerinde executor'dan gerçek çağrıları:
  dosya adı arama, içerik arama, okuma, küçük sentetik görsel gösterme.
- Dış symlink için arama/okuma reddinin executor üzerinden de korunması.
- Runner'ın scriptlenmiş kararlarla registry/executor yolunu kullandığı ve
  observation/event/trace alanlarının bozulmadığı bir entegrasyon testi.
- Yalnız testte kayıtlı beşinci küçük araç için runner dispatch'ini değiştirmeden
  çağrı yapılabilmesi; bu aracın production registry'ye girmemesi.
- Mevcut 33 A00 testi geçmeye devam etmeli. Ayrı gerçek test PostgreSQL'ini kullan;
  eksik testleri açıkça bildir. Mock sonucu gerçek DB/LLM testi diye raporlama.
  Thread'li testlerde global patch'leri worker bazında üst üste açıp kapatma;
  gerekiyorsa ortak patch scope'u iki worker bitene kadar açık tut.

Teslim:
- Küçük, odaklı commit: refactor: route native tools through registry and executor
- Yeni dalı GitHub'a push et, A01 için ayrı draft PR aç. main'e doğrudan push etme.
- Başlangıç merge SHA'sı, son SHA, PR URL'si, değişen dosyalar, test komutları
  ve sonuçlarını ver. Sınırları ve yapılmayan kontrolleri açıkça yaz.
- docs/UAT_CHECKPOINTS.md içine A01 teknik kaydı ekle; A01 inceleme/UAT BEKLEMEDE.
- Kullanıcı UAT'i için dört kısa senaryo yaz: dosya adı bulma, içerik arama,
  dosya okuma ve görsel gösterme. Her birinde beklenen cevap/araç/trace belirt.
- Teslimden sonra DUR. Ben source/diff ve testleri inceleyeceğim, kullanıcı UAT
  yapacak. İkisi kabul edilmeden merge veya A02'ye geçiş yapma.
```
