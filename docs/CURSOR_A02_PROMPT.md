# Cursor A02 uygulama talimatı

Başlangıç: `29137b4c62a6cf9af68d808506f9206c05810437` (main, birleştirilmiş PR #2).
Mevcut temel: 62 geçen test; A00/A01 ve görsel gösterim düzeltmesi.

## Cursor’a verilecek prompt

```text
Yalnız A02'yi uygula. Başlangıç main SHA'sı:
29137b4c62a6cf9af68d808506f9206c05810437.
Güncel HEAD farklıysa farkı kontrol et; kullanıcı değişikliklerini silme.
Bu aşama için codex/agent-a02-run-service dalı aç.
Yeni docs/CURSOR_A02_PROMPT.md dosyasını bu aşamanın dokümantasyonuna dahil et.

Önce kaynakları oku:
- docs/AGENT_EVOLUTION_PLAN.md A02 ve teslim kuralları
- app/interfaces/web/agent_routes/propose.py
- app/interfaces/web/agent_routes/assistant.py ve submission_display.py
- app/domain/agents/flow/memory/bridge.py
- app/adapters/db/agents/repositories/submission_repository.py
- app/domain/agents/flow/execution/run_knowledge_agent.py
- İlgili idempotency, recovery, tenant ve registry testleri
- Varsa geçerli AGENTS.md

Amaç:
POST propose içindeki çalışma sırasını AgentRunService'e çıkar.
Route HTTP adaptörü olarak kalsın. Bu aşama yeni özellik değil davranışı
koruyan bir sorumluluk ayrımıdır. Mevcut dosya taşıma/naming düzenini koru.

Sade yapı:
1. Küçük, açık veri sözleşmeleri kullan: ExecutionContext, RunRequest,
   RunOutcome. Az sayıda dosya/dataclass yeterli; framework, DI container,
   base class hiyerarşisi veya her fonksiyon için ayrı sınıf ekleme.
2. ExecutionContext sunucuda doğrulanmış customer_id/user_id, corpus kökü
   ve izinli araçlar gibi ihtiyaç duyulan kapsamı taşısın. Pozitif kimlikler
   doğrulansın; bool/boş/geçersiz değerler kabul edilmesin. İzinleri form/model
   argümanından alma. Config/context'in tamamını model prompt'una serialize etme.
3. RunRequest soru, submission_id, istenen session_id ve new_conversation
   niyetini taşısın. Tarayıcının mevcut session ipucu yalnız adaydır;
   ownership doğrulamasının yerine geçmesin. Request'e gerçek Flask session
   nesnesi koyma; gerekiyorsa yalnız mevcut agent_session_id değerini aktar.
4. AgentRunService; session çözme, kapsamlı replay kontrolü, atomik rezervasyon,
   bellek okuma, mevcut runner çağrısı, sonuç/trace hazırlama, persist ve
   submission tamamlamayı yönetsin. Bu sıralamanın önemli garantilerini koru.
5. Servis küçük memory/submission adapter'ları ve runner callable'ı alsın.
   Constructor üzerinden açık bağımlılık aktarımı yeterli. Fake adapter'larla
   Flask app/request context olmadan çalışabilmeli. Çekirdek servis Flask,
   request, g, session, current_app veya SQLAlchemy global db import etmesin.
6. Mevcut bridge/repository fonksiyonlarını production adapter'larından çağır.
   SQLAlchemy'nin app context ihtiyacı adapter/bootstrap tarafında kalabilir.
   Legacy memory_service'i yeniden yazma veya ikinci bellek deposu oluşturma.
   Adapter commit/rollback sınırını açık tutsun; rezervasyon runner başlamadan
   commit edilmeli. Bütün model çağrısı boyunca transaction açık tutma.
7. RunOutcome HTTP Response/redirect/jsonify içermesin. Tamamlandı, işleniyor,
   kapsam uyuşmazlığı, kimlik reddi ve bellek hatası gibi mevcut sonuçları ve
   canonical session/turn işaretçilerini taşısın. HTTP kodu/303 ve cookie pointer
   güncellemesini route yapsın. Tam yanıt cookie'ye yeniden girmesin.
8. Mevcut timeline/trace biçimini koru. Saf presenter yardımcıları gerekiyorsa
   ortak modüle alınabilir veya bootstrap'tan callback geçirilebilir; servis
   HTTP route modülünü import etmesin. Aynı dönüşümü iki yerde yeniden yazma.

Korunacak davranışlar:
- Submission tekilliği customer/user kapsamlı kalır; eşzamanlı yeni/boş
  konuşmada tek agent çalışır ve iki istek aynı canonical session'a bağlanır.
- Aynı submission + farklı soru/session reddedilir; geçerli canonical replay
  yeniden model/tool/persist çalıştırmaz. Kimlik reddi fail-closed kalır.
- Persist hatasında tam cevap sunucu tarafındaki submission kaydında korunur.
  GET recovery, refresh, session eşleşmesi ve new=1 izolasyonu bozulmaz.
- Model kararları ANSWER/CLARIFY/STOP_INCOMPLETE ve teknik hata biçimleri,
  dört native araç, izin kontrolü, show_image zenginleştirme ve trace korunur.
- Qwen embedding profili, kalibre eşik, offset pagination ve mevcut auth
  ayarlarına bu aşamada davranış değişikliği yapılmaz.

Kapsam dışında:
MCP, skill loader, yeni Run API endpoint'i, worker/queue, async dönüşüm,
checkpoint/resume, yeni DB tablosu, A03 bütçe mekanizması, Docker/GPU ayarı
ve UI tasarımı. GET/upload/görsel route'larını topluca yeniden taşıma.

Testler:
- Fake memory/submission adapter'larıyla servis Flask context olmadan gerçek
  runner sözleşmesini kullansın; commit-before-runner sırası doğrulansın.
- Servis seviyesinde normal cevap, completed replay, processing, farklı
  içerik/session, kimlik reddi, bellek okuma/persist hatası senaryoları olsun.
- Web route aynı servise bağlansın; payload'daki customer/user veya araç
  izinleri doğrulanmış sunucu context'ini değiştiremesin.
- DB yarış ve recovery testlerini kaldırma. Patch hedeflerini taşınan gerçek
  sorumluluğa göre güncelle; sadece test geçsin diye ownership/reserve yolunu
  bütünüyle sabitleme. Thread'li testlerde global patch kapsamı güvenli olsun.
- Mevcut 62 test geçsin. Ayrı gerçek NATIVE_FLOW_A00_TEST DB'sini kullan.
  Unit testler harici modele çıkmasın. Gerçek DB ve fake test kanıtlarını ayır.

Teslim:
- Odaklı commit: refactor: extract agent run service and execution context
- Dalı GitHub'a push et; main'e yönelik ayrı draft PR aç. Otomatik merge yok.
- Başlangıç/son SHA, PR URL'si, değişen sorumluluklar ve gerçek test sonuçları.
- docs/UAT_CHECKPOINTS.md A02 kaydı; inceleme ve manuel UAT BEKLEMEDE.
- Kısa UAT: yeni konuşma + belge sorusu; takip sorusu; refresh/geçmiş;
  yeni konuşma izolasyonu; bilinen görsel. HTTP arayüzünün aynı kaldığı görülsün.
- Teslimden sonra DUR. Kaynak incelemesi ve kullanıcı UAT kabulünden önce
  A02 merge veya A03 başlatma.
```
