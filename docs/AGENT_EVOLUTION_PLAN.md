# Agent runtime geliştirme ve kabul planı

Bu plan mevcut belge agent’ını ortak araç sözleşmesi, uygulama skill’leri, gerçek MCP bağlantısı, run API’si ve sınırlı bir DB raporlama pipeline’ı ile genişletir. Cursor her aşamayı ayrı uygular ve GitHub’a gönderir. Kod incelemesini bu sohbetten, manuel kullanıcı kabul testlerini proje sahibi yapar. Her aşama iki kontrol de geçene kadar kapalı kalır.

Başlangıç: 6 Kasım 2026; yerel ve GitHub üzerinde doğrulanan commit `99de9f400c48f422348aae4af2d9025b68a7ff27`. Bu commit sandbox, migration bağlantısı, auth/secret yapılandırması ve submission idempotency değişikliklerini içerir. İçermesi kabul edildiği anlamına gelmez; A00 bunları doğrular.

## Çalışma düzeni

1. Cursor yalnız açıkça verilen aşamayı uygular. Bir sonraki aşamaya kendiliğinden geçmez.
2. Her aşama mevcut kabul edilmiş commit’ten başlar. `codex/agent-aNN-<konu>` dalı, bir odaklı ana commit ve gerekirse inceleme düzeltme commit’leri kullanılır. Dal GitHub’a push edilir; draft PR açılır. Otomatik merge yapılmaz.
3. Cursor başlangıç SHA’sını, son SHA’yı, PR/dal bağlantısını, çalıştırdığı kontrolleri, test sınırlarını ve UAT adımlarını teslim eder. Lokal commit veya yalnız kod çıktısı teslim sayılmaz; uzak SHA doğrulanır.
4. İnceleme ve UAT aynı kesin SHA üzerinde yapılır. Sonradan kod değişirse etkilenen kontroller ve UAT tekrarlanır. Önceki kabul yeni SHA’ya otomatik aktarılmaz.
5. Ben inceleme sonucunu veririm; kullanıcı UAT sonucunu verir. Kullanıcı `Axx UAT PASS, SHA ...` demeden UAT geçilmiş yazılmaz. Başarısızlıkta aynı aşamada kalınır.
6. İki kontrol geçince kullanıcı birleştirme ve sonraki aşamaya geçme talimatı verir. Sonraki dal kabul edilmiş ve birleştirilmiş sürümden açılır.
7. `.env`, corpus, gerçek müşteri verisi, credential ve yerel loglar commit edilmez. Fixture’lar sentetiktir. Kullanıcının başka değişiklikleri temizlenmez veya stage edilmez.
8. Git dalı/PR oluşturma ya da push engellenirse durum açıkça bildirilir. Yerel başarı uzak başarı gibi raporlanmaz. Force push, otomatik rollback veya production migration yapılmaz.

Her aşamanın kayıt şablonu `docs/UAT_CHECKPOINTS.md`; Cursor için başlangıç talimatı `docs/CURSOR_STAGE_PROMPT.md` içindedir.

## İlk hedef ve son hedef

İlk yetenek hedefi A05’tir: mevcut belge akışı çalışırken bir uygulama skill’i yüklenir ve gerçek bir MCP subprocess’i keşfedilip çağrılır. Bu hedef tamamlanınca MCP/skill sınırını doğrulamış oluruz; bütün platformun üretim dayanıklılığını kanıtlamış olmayız.

Son hedef A09’dur: web ve JSON API aynı uygulama servisini kullanır; sentetik tenant verisi üzerinde deterministik DB raporu üretilir; bir skill dosya, DB ve MCP araçlarını aynı run içinde kullanır; sonuç ve trace yeniden açılabilir.

## A00 Mevcut güvenilirlik commit’ini doğrula

**Amaç:** `99de9f4` değişikliklerini yeniden yazmadan regresyon testleriyle güvenilir başlangıç oluşturmak.

**İş:** Hafif bir test altyapısı ve ayrı geliştirme bağımlılıkları ekle. Symlink sandbox, migration ayar önceliği, zorunlu secret/login yapılandırması ve DB submission tekilliğini doğrula. README/VERIFICATION yeni submission migration’ını ve gerçek auth davranışını anlatsın. İdempotency testleri mevcut oturum yanında `new_conversation=1`, boş session başlangıcı, eşzamanlı aynı istek, aynı ID ile farklı içerik ve farklı tenant/kullanıcı kapsamını kapsasın. Persistence hatası olduğunda üretilen yanıtın kaybolması ve submission durumunun yanlış tamamlanması da kontrol edilsin. Bulunan kusurlar yalnız bu kapsamda düzeltilsin.

**Otomatik kabul:** Unit testleri harici LLM çağırmaz. Ayrı test PostgreSQL’i üzerinde migration iki kez çalışır ve gerçek iki bağlantıyla yarış testinde tek rezervasyon kazanır. DB testi yapılmadıysa açıkça beklemede kalır; mock bunun yerine geçmez.

**UAT A00:** Kullanıcı izole test DB’sini hazırlar ve belgelenen migration’ları çalıştırır. Yeni konuşma açar, `uat-guide.md` yükler, içerik sorar, sayfayı yeniler ve geçmişten yeniden açar. Aynı gönderimi çift tıklama/yeniden gönderme ile dener; tek cevap/tek agent çalışması beklenir. Normal tarayıcı yenilemesi ile POST tekrarının aynı şey olmadığı UAT notunda açıklanır. Yeni konuşma ve mevcut konuşma ayrı denenir.

**Commit:** `test: verify standalone hardening and submission behavior`

## A01 Ortak araç registry ve executor

**Amaç:** Yeni bir araç için runner’a yeni `if/elif` ekleme zorunluluğunu kaldırmak.

**İş:** `ToolSpec`, `ToolRegistry`, `ToolExecutor` ve `ToolResult` sözleşmelerini oluştur. Spec; ad/sürüm, açıklama, giriş/çıkış şeması, handler, yan etki sınıfı, tekrar/cache davranışı ve timeout bilgisini taşısın. Result; durum, içerik blokları/veri, kaynak referansı ve kodlu hatayı taşısın. Dört mevcut dosya aracını adapter ile kaydet. Araç listesi ile dispatch aynı registry’den gelsin; argüman/sonuç doğrulaması executor sınırında uygulansın. Önceki tool JSON ve UI sonuçlarını korumak için geçiş adapter’ı kullan; gereksiz toplu yeniden yazım yapma.

**Otomatik kabul:** Bilinmeyen veya izinsiz araç çalışmaz; hatalı giriş handler’a ulaşmaz; hatalı çıkış açık hata olur. Aynı isim çakışması başlangıçta reddedilir. Dört native araç eski fixture’larla çalışır. Registry’de görünmek yetki anlamına gelmez.

**UAT A01:** Aynı dosya için dosya adı arama, içerik arama, okuma ve mevcut sentetik görsel gösterme senaryolarını dene. Cevap, kaynak yolu ve timeline korunmalı.

**Commit:** `refactor: route native tools through registry and executor`

## A02 Uygulama servisi ve açık execution context

**Amaç:** Web, API ve gelecekte worker aynı çalışma yolunu kullanabilsin.

**İş:** `AgentRunService` ile `ExecutionContext` ekle. Context; sunucuda doğrulanan customer/user, conversation, submission/run kimlikleri, izinler, corpus kökü ve çalışma bütçelerini taşısın. Route yalnız giriş/auth, servis çağrısı ve sunum/yönlendirme yapsın. Bellek ve run/submission depolama erişimlerini dar arayüzlerle servise geçir. Domain çekirdeği Flask session veya `g` okumamalı; SQLAlchemy adapter’ının app context ihtiyacı açıkça adapter/bootstrap tarafında kalsın. Legacy bellek servisini tek aşamada tamamen yeniden yazma.

**Otomatik kabul:** Sahte bellek/depoyla servis Flask request context’i olmadan çalışır. Web yolu aynı servisi kullanır. Tenant/user form veya model argümanıyla değiştirilemez. Session ownership ve A00 idempotency kontrolleri korunur.

**UAT A02:** Yeni/eski konuşma, geçmiş ve tekrar gönderim A00 ile aynı davranır. Yetkisiz konuşma kimliği erişimi reddedilir; başka konuşmanın içeriği görünmez.

**Commit:** `refactor: extract agent run service and execution context`

## A03 Bütçeler ve context üretimi

**Amaç:** Araç/skill sayısı arttığında süre ve context büyümesini yönetmek.

**İş:** `RunPolicy`/budget ve context builder ekle. Adım limiti, toplam deadline, araç başına timeout ve observation/context boyutu limiti yapılandırılsın. Token kullanımı raporlanıyorsa kaydedilsin; henüz raporlanmayan modelde kesin token limiti uygulanmış gibi sunulmasın. Prompt temel politika, görev talimatı ve seçilmiş araç kataloğundan üretilsin. Tekrarlayan çağrı davranışı araç politikasına taşınsın: mevcut dosya araçları tekrar engellemeyi koruyabilir; değişken API/DB okuması açık politika ile yeniden çağrılabilir. Retry sınırlı olsun; yazma araçları otomatik tekrar edilmesin.

**Otomatik kabul:** Sahte saat/model ile deadline, adım limiti, büyük sonuç ve tekrar politikası deterministik test edilir. Deadline sonraki çağrıyı engeller; çalışan I/O’nun sonlandırılması transport timeout’una bağlıdır. Python thread’inin veya senkron handler’ın zorla durdurulduğu iddia edilmez. Sonuç kısaltıldığında truncation ve kaynak referansı korunur.

**UAT A03:** Eksik belge sorusunda uydurma cevap yerine açıklama/durma; düşük adım limitinde anlaşılır sonuç; büyük belgede kontrollü davranış. Testteki düşük limitler normal profilin ayarlarını kalıcı bozmaz.

**Commit:** `feat: add run budgets and bounded context construction`

## A04 İlk uygulama skill’i

**Amaç:** Prompt’a gömülü görev bilgisini sürümlenebilir uygulama skill’ine ayırmak.

**İş:** Repo içindeki `agent_skills/document-review/SKILL.md` ve açık metadata ile ilk skill’i ekle. Bu, Cursor/Codex host skill’i değil, bu uygulamanın yüklediği bir skill’dir. Loader güvenilir tanımlı kökten okur; metadata için güvenli parser ve şema kullanır. Skill kimliği/sürümü, açıklaması, gereken araçları, talimatları ve yardımcı kaynakları tanımlanır. UI’da açık skill seçimi ekle; seçim request hash’ine dahil olsun. Temel çalışma modu geriye uyumlu kalsın. Kullanılabilir araçlar sunucu izinleri ile skill kapsamının kesişimidir; skill yetki vermez. Skill içeriği ile yüklenen kullanıcı belgeleri farklı güven seviyelerinde işlensin.

**Skill davranışı:** Kullanıcının belirttiği belgeyi bul/oku; özeti, eksik veya çelişen noktaları ve dosya/konum kaynaklarını ver; bulunmayan bilgiyi açıkça belirt. Sabit metin cevabı veya sahte araç gözlemi kullanma.

**Otomatik kabul:** Geçerli, bozuk ve bilinmeyen skill; kök dışı kaynak; eksik araç; yetkiyi genişletmeye çalışan metadata ve skill değişmiş replay testleri. Skill içeriği context bütçesine tabidir. Dosya adı/metadata shell komutu çalıştırmaz.

**UAT A04:** `document-review` seç; sentetik `uat-guide.md` belgesini incelet. Skill kimliği/sürümü ve native araç çağrıları trace’te görünür. Belgede olmayan bir detayı sor; uydurmamalı. Aynı soruyu temel modda da sorarak iki yolun çalıştığını doğrula.

**Commit:** `feat: load document review skill with explicit tool scope`

## A05 Gerçek MCP adapter ve yerel doğrulama

**Amaç:** Uygulamanın gerçek bir MCP sunucusunu keşfedip aynı executor üzerinden çağırdığını göstermek.

**Seçim:** Resmî `@modelcontextprotocol/server-everything`, yerel stdio. Referans/test sunucusudur; iş verisi servisi değildir. API anahtarı veya ücretli servis hesabı gerektirmez. Model kullanımı ve bilgisayar kaynakları kendi mevcut koşullarına tabidir. Açılan güncel upstream README Node.js 24+ ister; uygulama sırasında seçilen yayın sürümünün gerçek engine/SDK uyumluluğunu doğrula ve sürümleri sabitle. `latest`, sürümsüz otomatik indirme veya her run’da paket indirme kullanma.

**İş:** Resmî Python MCP SDK ile bir adapter ekle. Uyumlu SDK/protokol/sunucu sürümleri kurulum kaydına yazılsın. İlk kapsam stdio, tool discovery ve tool call’dur. MCP kendi async yaşam döngüsünde açılıp kapansın; farklı event loop’larda aynı session taşınmasın. Sınırlı başlangıç için run başına bağlantı kabul edilir; global daemon/pool gerekmez. Süreç ve pipe cleanup hata/timeout yolunda da çalışsın. Sunucu komutu/argümanları yalnız sunucu yapılandırmasından gelsin; kullanıcı/model shell komutu veremesin. Çocuğa yalnız gerekli ortam verilsin; uygulamanın `.env` değerleri aktarılmasın.

**Araç kapsamı:** Yalnız `echo` ve `get-sum` (seçilen pinned sürümde discovery ile doğrulanacak) allowlist’e alınır. İç isimler `mcp.everything.echo` ve `mcp.everything.get_sum` gibi namespace kullanır. Upstream `get-env` gibi diğer araçlar görünmez ve çağrılamaz. MCP text/structured/error içerikleri ortak ToolResult’a çevrilir; desteklenmeyen içerik tipi açıkça ele alınır. Bu aşamada resources, prompts, sampling, elicitation, remote OAuth ve MCP tasks desteği iddia edilmez.

**Otomatik kabul:** Adapter testleri fake transport ile; ayrı entegrasyon testi gerçek subprocess ile discovery/echo/toplam çağrısı yapar. Server bulunamıyor, hatalı argüman, `isError`, timeout ve kapatma test edilir. MCP kapalıyken native belge akışı çalışır. Fake testler gerçek entegrasyon başarısı sayılmaz.

**UAT A05:** Uygulama ekranından `MCP echo aracını kullanarak UAT-MCP-001 metnini geri getir` ve `MCP toplam aracıyla 125 ve 275'i topla` isteklerini gönder. Beklenen echo ve 400 cevabı yanında gerçek namespaced tool call ve sunucu kimliği/sürümü trace’te görünmeli. Modelin kendi başına 400 demesi PASS değildir. Bağlantıyı kapatıp native belge sor; çalışmalı. MCP zorunlu bir istek ise açık kullanılamıyor sonucu vermeli. MCP kapalı kontrolü aynı ID’li tamamlanmış submission replay’iyle yapılmamalı.

**Commit:** `feat: integrate a pinned local MCP reference server`

## A06 Kalıcı run ve adım kayıtları

**Amaç:** Trace’i yalnız turun sonunda kaydetmek yerine çalışma kimliğine bağlamak.

**İş:** Migration/repository ile tenant-scoped `agent_runs` ve sıralı `agent_run_events` ekle. Run durumları ile ANSWER/CLARIFY gibi model sonuçları ayrı alanlar olsun. Submission ile run arasında açık ilişki kur; mevcut idempotency’yi ikinci bağımsız mekanizmayla çoğaltma. Başlangıç, araç başlangıç/bitiş, model kararı ve sonuç olaylarını sınırlı/sansürlenmiş biçimde kaydet. Model, skill, tool sürümleri ve mevcut usage bilgilerini ekle. Core event üretimi bozulmadan adapter persist etsin; kalıcı kayıt hatasına uygulanacak davranış açıkça belgelensin. Stale çalışan run `interrupted` olarak tanımlanabilsin; otomatik yeniden yürütme yapılmasın.

**Otomatik kabul:** Olay sıra/kimlikleri, tenant izolasyonu, tamamlanan run replay’i ve işlem ortasında kesinti test edilir. Uygulama yeniden açılınca tamamlanan run sonucu ve olayları okunur. Run event kaydı araç yazma işlemlerini tam bir exactly-once transaction’a dönüştürmüş sayılmaz.

**UAT A06:** Bir native ve bir MCP run oluştur; sayfayı yenile ve uygulamayı yeniden başlat; sonuçları/trace’i tekrar aç. İzole testte yarıda kalan run açık kesinti durumu göstermeli; kendiliğinden yeniden MCP çağrısı yapmamalı.

**Commit:** `feat: persist tenant scoped agent runs and events`

## A07 JSON Run API

**Amaç:** UI dışındaki istemci aynı servise güvenilir biçimde erişebilsin.

**İş:** POST `/agent/api/runs`, GET `/agent/api/runs/<run_id>` ve GET `/agent/api/runs/<run_id>/events` ekle. İlk POST mevcut senkron servis yolunu kullansın ve başarılı tamamlanmada 201 + run/result dönsün; replay 200, halen işlenen istek 202 + aynı run’a Location dönsün. 202 döndüğünde yeni bir arka plan işi oluşturulduğu iddia edilmesin: bu aşamada yalnız zaten çalışan duplicate isteğin durumudur. Queue/worker veya yeni uzun iş kabulü sonraki ayrı kapsamdır. Idempotency-Key, skill kimliği ve sunucu doğrulaması tanımlansın. Çakışma 409; auth hatası 401/403; başka tenant run’ı varlığını sızdırmadan reddedilsin. API hataları HTML redirect dönmesin. JWT veya yerel bypass mevcut auth politikasını kullansın; ID alanları istemciden sahiplik kaynağı olarak alınmasın. Cookie ile çağrılabilen değiştirici endpoint’lerde mevcut CSRF modelini incele, açık bir koruma veya yalnız header-auth sınırı uygula; salt CORS’a güvenme.

**Otomatik kabul:** API/UI aynı servis ve submission kontrolünü kullanır. Response şemaları, aynı anahtar replay’i, farklı payload/skill çakışması, eşzamanlı 202, cross-tenant GET ve auth hata biçimleri test edilir. README’de curl örnekleri gerçek secret içermez.

**UAT A07:** Belgelenen curl ile skill’li run başlat; sonucu ve olayları GET ile oku. Aynı anahtarı tekrar gönder; aynı run dönmeli. Aynı anahtarla farklı soru gönder; 409 beklenir. Aynı konuşmayı UI’da açıp sonucu kontrol et. Kullanıcı/tenant değiştirme kontrolleri gerçek JWT yoksa test harness ile kanıtlanır; manuel PASS gibi gösterilmez.

**Commit:** `feat: expose the shared agent run service through JSON API`

## A08 Deterministik DB rapor pipeline’ı

**Amaç:** LLM’e sınırsız SQL vermeden bir gerçek DB veri akışını doğrulamak.

**İş:** Ayrı demo tablo/repository ve idempotent sentetik seed komutu ekle. `get_sales_summary(start_date, end_date)` aracı yalnız parametreli, tenant-scoped SELECT ile adet, para birimi, Decimal toplam, sınırlı satır ve kaynak bilgisini döndürsün. DB komut/sonuç timeout’u ve satır sınırı tanımlansın. Mümkünse ayrı read-only rol kullan; kurulumda nasıl doğrulandığını göster. Para birimleri karıştırılmasın. Pipeline doğrulama → DB okuma → deterministik hesap/sonuç → model anlatımı olarak kurulsun. Hesaplama/model cümlesi ayrımı korunsun. İş verisi deposu, konuşma belleği ve run deposu ayrı sorumluluklardır; ilk iterasyonda aynı PostgreSQL instance kullanılabilir.

**Fixture:** Tenant 101 için 1–3 Kasım 2026 tarihlerinde TRY 100.00, 250.50, 49.50; tenant 202 için aynı aralıkta TRY 9999.00. Beklenti tenant 101: 3 kayıt, TRY 400.00. Seed yalnız açık demo/test DB hedefinde çalışır; gerçek müşteri tablosu oluşturmaz/değiştirmez. Kuruş alanlarıyla ek karşılaştırma gerekirse 10000, 25050, 4950 kullanılır.

**Otomatik kabul:** Ayrı test PostgreSQL’i üzerinde gerçek query testi, tarih sınırları, boş sonuç, başka tenant verisi, satır limiti ve DB kullanılamıyor durumu doğrulanır. DB kapalıyken model eski bilgiden rakam uyduramaz. Tenant filtresi model argümanına bağlı değildir.

**UAT A08:** İzole DB seed’ini çalıştır. Yerel test context’inde tenant 101 ve 202 için ayrı profiller kullan; tarayıcı session’larını ayır. 101 için 3/400.00, 202 için 1/9999.00 bekle. Boş tarih aralığı ve DB kapalı durumunu dene. Orijinal yerel `.env` dosyasını commit etme; test profillerini normal ayarlara geri döndür.

**Commit:** `feat: add a tenant scoped read only sales reporting pipeline`

## A09 Birleşik skill ve son kabul

**Amaç:** Native araç, uygulama skill’i, MCP, API ve DB aynı run zincirinde gerçekten çalışsın.

**İş:** İkinci skill `agent_skills/sales-report/SKILL.md` ekle. Native `file_read` ile sentetik rapor kurallarını oku, `get_sales_summary` ile DB verisini al, yalnız test karşılaştırması için MCP toplam aracını kullan ve kaynaklı rapor üret. Skill’in açık gereksinimleri eksikse sessiz fallback yerine bildir. 10000 + 25050 + 4950 kuruş toplamını iki MCP çağrısıyla doğrula; DB hesaplamasının otoritesi Decimal tabanlı pipeline’da kalsın. UI ve API’da aynı senaryo çalışsın. Kısa değerlendirme seti ekle: doğru araç seçimi, kaynak yokluğu, hatalı skill, MCP kapalı, DB kapalı, yetki reddi ve replay. Deterministik adapter testleri ile gerçek model değerlendirmeleri ayrı raporlansın; model testinde beklenen araç trace’i aranır, yalnız final metni yeterli sayılmaz.

**UAT A09:** Önce document-review regresyonu; sonra sales-report ile tenant 101 için kurallı rapor. Beklenen 3 kayıt/TRY 400.00, DB tool call, iki gerçek MCP toplam çağrısı, skill sürümü ve kaynak referansları aynı run’da görünür. Aynısını API ile yap; sonra aynı Idempotency-Key’i tekrar gönder: yeni LLM/DB/MCP yürütmesi olmamalı. Bağlantı hatası senaryolarında açık kısmi/başarısız sonuç; uydurulmuş başarı olmamalı.

**Commit:** `test: validate skills MCP API and DB reporting end to end`

## Sonraki ayrı geliştirmeler

A09 sonrasında ihtiyaç geldikçe: background worker ve job kabul API’si; belge parse/OCR/index ingestion pipeline’ı; remote MCP + OAuth; onay bekleyen yazma araçları ve operation idempotency; checkpoint/resume; kontrollü paralel araçlar. Bunlar bu plan tamamlandı diye mevcut kabul edilmez. Önceki aşamalarda bunlar için framework, çok agent sistemi veya genel DAG motoru kurulmaz.

## Kaynaklar

- [Everything resmî README](https://github.com/modelcontextprotocol/servers/blob/main/src/everything/README.md): referans/test amacı, stdio kullanımı ve runtime gereksinimleri.
- [Everything araçları](https://github.com/modelcontextprotocol/servers/blob/main/src/everything/docs/features.md): echo, get-sum ve kapsam dışında bırakılacak araçlar.
- [Resmî Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk): client/transport uygulaması; seçilen sürümün dokümanı kullanılmalı.

Bu kaynaklar 6 Kasım 2026 tarihinde kontrol edildi. Uygulama aşamasında paket sürümü ve araç şeması gerçek kurulan sürüm üzerinden yeniden doğrulanır.
