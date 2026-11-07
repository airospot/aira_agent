# Tenant altında orijinal ve çıkarılmış dosya saklama

A02'nin PNG düzeltmesi `e98132db16e828cfcc70968a498ad5fc8c0f8d1d` üzerinde incelendi; 80 test bağımsız geçti. PNG isim arama/gösterme manuel UAT'i ve A02 merge'i tamamlandıktan sonra bu çalışma ayrı PR olarak yapılır. A03 bu çalışmanın kapsamına girmez.

## Karar

Kabul edilen her upload'ın orijinal baytları saklanır. Orijinaller ve türetilmiş içerik tenant altında fiziksel olarak ayrılır. Tenant, bu uygulamada doğrulanmış `customer_id` değeridir; form, model argümanı veya serbest URL değeri değildir. Aynı tenant içindeki yetkili kullanıcılar için mevcut erişim politikası korunur; yeni kullanıcı ACL sistemi eklenmez.

Basit yerleşim:

- `data/tenants/<customer_id>/uploads/<upload_id>/<safe_filename>`: orijinal dosya ve upload manifest'i.
- `data/tenants/<customer_id>/corpus/`: agent'ın görebildiği türetilmiş corpus. Office/PDF için mevcut `extracted_data/.../content.md`, `images/`, `meta.json` düzeni burada sürer. Metin upload'ının corpus kopyası da burada bulunur.

Orijinal dosya deposu agent'ın genel corpus tarama kökünün dışında kalır. Aynı dosyanın orijinal metni ve türevi arama sonuçlarına iki kez sokulmaz. Üst tenant veri kökü yapılandırılabilir; mevcut `AGENT_CORPUS_DIR` için yeni anlam/uyumluluk README'de açıkça anlatılır.

## Cursor'a talimat

```text
Ön koşul: A02 manuel UAT kabul edilmiş ve PR #3 main'e birleştirilmiş olmalı.
Durumu doğrula; gerçekleşmemişse merge yapma veya bu çalışmayı A02'ye ekleme.
Kabul edilmiş güncel main'den codex/tenant-document-storage dalını aç.
Bu prompt dosyasını kendi dokümantasyon commit'ine dahil et.

Önce document_upload.py, corpus_image_serve.py, corpus_path_sandbox.py,
run/factory.py, run/contracts.py, native file tool'ları, parser'lar ve güncel
testleri oku. İhtiyaç olmayan dosya taşıma, framework veya şema tasarımı yapma.

1. Tek bir tenant storage resolver kullan.
   customer_id doğrulanmış sunucu context'inden gelsin; eksik/geçersiz kimlikte
   ortak corpus'a fallback olmasın. Tenant kökünün güvenli veri kökü altında
   kaldığını doğrula. İstek bazında kök üret; global Flask config'i tenant'a göre
   değiştirerek eşzamanlı istekleri birbirine karıştırma.

2. Kabul edilen bütün upload'larda orijinal baytları koru.
   Metin, DOCX, PPTX, PDF gibi mevcut izin verilen tipler aynı kapsamda kalsın;
   bu istek yeni bütün uzantıları kabul etmek anlamına gelmez. Boyut/tip/isim
   doğrulaması korunsun. Bağımsız upload UUID'si kullan; eşzamanlı aynı isimler
   birbirini ezmesin. Orijinal SHA-256 ve gerçek source_filename manifest'te
   kaydedilsin. İşlenen yeni dosyada orijinal baytlar değişmemeli.

3. Parse başarısız olsa da kabul edilmiş orijinal dosya kalsın.
   Manifest uploaded/processing/ready/failed durumunu ve güvenli hata kodunu
   taşıyabilir; yeni DB tablosu gerekmiyor. Başarısız çıkarımı başarı gibi dönme.
   Kısmi çıktılar agent corpus'una görünür olmadan staging'de hazırlansın;
   tamamlanan türevler atomik yayımlansın. Parser/OCR retry mümkün olsun.
   Aynı tenant'taki hash cache, orijinal saklama adımını atlamasın. Tenant'lar
   arasında ortak cache/dedup ile dosya varlığı veya içerik sızdırma.

4. Aynı kapsamı bütün okuma yollarına uygula.
   Upload, ExecutionContext.corpus_root, file_name_search/file_search/file_read/
   show_image, görsel sunumu ve orijinal download aynı server-verified tenant
   resolver'ını kullansın. Model/client corpus kökünü veya tenant'ı değiştiremesin.
   Native araçların low-level sandbox'ı aynı kalsın; trusted context'ten gelen
   tenant corpus köküyle çalışmaları yeterli. Formdaki sahte customer_id ve
   ../ ile başka tenant'a geçiş, diğer tenant'a symlink reddedilsin.

5. Orijinal dosya için küçük, yetkili attachment-download endpoint'i ekle.
   Upload UUID ve doğrulanmış tenant üzerinden manifest'teki sabit dosyayı bul;
   istemcinin verdiği fiziksel path'i send_file'a aktarma. Başka tenant UUID'si
   404/403 dönsün. Download attachment ve nosniff olsun; HTML upload'ı sayfa olarak
   çalıştırılmasın. Hassas görsel/download yanıtlarında tenant/hesap değişiminde
   eski içeriğin cache'ten görünmesini önleyen cache politikası kullan.
   Upload response'ta orijinal download bağlantısı ve türetilmiş corpus-relative
   path açık olsun. Şimdilik dosya yöneticisi arayüzü oluşturma.

6. Mevcut verileri kayıpsız ele al.
   Eski data/corpus içeriğini silme veya bütün tenant'lara kopyalama.
   Sahipliği belirsiz eski içerik current tenant'a otomatik atanmasın.
   Önce dry-run raporlayan, açık source → tenant eşlemesiyle çalışan bir kopyalama
   komutu sun. --apply olmadan değişiklik yapmasın; gerçek veride apply çalıştırma.
   Eski corpus-relative dosya yolları hedef tenant corpus'unda korunabilsin;
   böylece doğru tenant'ın eski konuşma/görsel referansları çalışmaya devam eder.
   Kaynakta orijinal DOCX yoksa MD'den orijinal üretme; original_unavailable olarak
   raporla. Kaynaklar korunmalı, tekrar çalıştırma çakışmaları açık ele alınmalı.
   Eski shared kökü yeni tenant çalışma yoluna fallback olarak açma.

Test ve UAT:
- İki tenant, aynı dosya adı ve ayrı içerik/görsel ile gerçek fiziksel ayrımı test et.
- Her tenant yalnız kendi upload/search/read/show_image/download sonucuna erişsin.
  Tenant A'nın görüntü/download URL'sini tenant B ile açmak içeriği vermemeli.
- Orijinal download baytları/SHA kaynakla aynı olsun; türetilmiş metin/görseller
  aynı tenant altında oluşsun. Parse hatasında orijinal korunup durum failed olsun.
- Tenant bazlı dedup, eşzamanlı aynı isimler, path traversal ve cross-tenant
  symlink testleri; eksik tenant'ta fail-closed testleri ekle.
- Migration dry-run gerçek veri değiştirmesin; sentetik veride apply iki kez
  çalıştırılınca veri kaybı olmasın. Eksik orijinaller açık raporlansın.
- Önceki 80 testi koru veya yeni tenant kapsamına uygun fixture'larla güncelle;
  izolasyonu koruyan kontrolleri kaldırma. Gerçek LLM unit testlerde çağrılmasın.
- Kullanıcı UAT'i: frontend'den küçük DOCX + TXT yükle, orijinalleri indirip aç,
  çıkarılmış içeriği sor/görseli göster. Ayrı tenant profilinde önceki dosyanın
  arama ve URL ile erişilemediğini doğrula. Normal profil ayarlarını geri koru.

Teslim: ayrı draft PR, commit/HEAD SHA, test komutları/sonuçları, yeni dizin
yerleşimi ve kısa UAT adımları. Gerçek eski veri migration'ı uygulanmadıysa bunu
açıkça yaz. İnceleme/UAT BEKLEMEDE. Merge ve A03 yapmadan DUR.
```
