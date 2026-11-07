# Yerel Ollama GPU ve bellek düzeltmesi

7 Kasım 2026 tarihli kaynak ve canlı runtime kontrolüne dayanır. A02 başlamadan bu UAT engelleri giderilir. A01 registry/executor refactor’ı yeniden yazılmaz. Yerel CSS değişikliği, untracked scripts/ ve diğer kullanıcı dosyaları korunur.

## Doğrulanmış bulgular

- Uygulama: `http://127.0.0.1:11434/v1`, `qwen3.5:9b`, timeout 300 saniye.
- `/api/ps`: model yüklü, `size_vram=0`; container logunda CPU compute buffer kayıtları var.
- Host: RTX 5090 Laptop GPU, 24463 MiB, NVIDIA driver 595.99.02; host `nvidia-smi` çalışıyor.
- Ollama container: `server-utilities-stack-ollama`, image `ollama/ollama:latest`, sunucu sürümü 0.32.0.
- Container GPU isteği mevcut: tüm GPU’lar; görünür aygıtlar all, yetenekler compute/utility. Buna rağmen container içindeki `nvidia-smi`: `Failed to initialize NVML: Unknown Error`.
- Docker: `systemd` cgroup sürücüsü, cgroup v2; NVIDIA Container Toolkit 1.20.1, runtime mode auto.
- Compose kaynağı: `/home/airadev/Documents/Aira-Full-Stack/server_utlities/docker-compose.stack.yml`. Bu dosya mevcut agent reposunun dışındadır; okuma ve gerekli yazma izinlerini kendi çalışma ortamında doğrula.
- Kurulu embedding modeli `qwen3-embedding:4b`; model metadata’sında doğal boyut 2560. Nomic kurulu değil.
- `memory_service._create_embedding` hâlâ sabit nomic modelini çağırıyor; 768 boyutu 1536’ya sıfırla dolduruyor. Query ve kullanıcı mesajı yazımı senkron embedding çağrısı yapabiliyor.
- `bridge.list_agent_conversations` offset gönderiyor; ConversationService ve repository list_conversations imzalarında offset yok. TypeError doğrulandı; görünür sayfa ORM fallback sayesinde açılıyor.

## Cursor’a verilecek talimat

```text
Önce ilgili kaynakları oku. A01 registry/executor koduna ve A00 güvenilirlik
düzeltmelerine dokunma. A02'yi başlatma. Yeni framework, worker veya genel
pipeline mimarisi kurma. Bu dosyadaki bulguları canlı durumda yeniden doğrula;
runtime sonradan değişmiş olabilir. Test ve kanıt olmadan "GPU düzeldi" deme.

1) Önce yalnız Ollama GPU erişimini düzelt

- Ollama host CLI bulunmayabilir; gerçek server container içindedir.
- Host ve container nvidia-smi, DeviceRequests, ilgili GPU logları, runtime/CDI
  ayarlarını karşılaştır. İkinci bir ollama serve başlatma; CPU fallback'i
  bastırıp sağlıklıymış gibi gösterme; rastgele driver/model güncelleme yapma.
- NVIDIA'nın bilinen container GPU erişim kaybı belgesini kullan. systemd
  daemon-reload/container update olası tetikleyicidir; bu makinede kanıt
  olmadan kesin neden diye yazma. Gerekli runtime/CDI düzeltmesini gerçek
  kurulu sürümün desteklediği ayarla ve yalnız ilgili servisle sınırlı tut.
- Container yeniden oluşturulacaksa model volume'larını koru; devam eden
  Ollama isteğine etkisini bildir. Tüm stack'i down etme, volume silme veya
  bütün Docker daemon'ını gelişigüzel yeniden başlatma. Sistem/genel ayar
  değişiklikleri gerekiyorsa kapsamını ve diğer servislere etkisini açıkla.
- Container NVML erişimi çalıştıktan sonra küçük bir sentetik qwen3.5:9b isteği
  çalıştır. /api/ps ve GPU offload loglarıyla gerçekten GPU kullandığını
  doğrula; yalnız host nvidia-smi başarısı yeterli değildir.
- Model soğukken /api/ps boş olabilir; bunu CPU fallback diye sınıflandırma.
  Yüklü model CPU'daysa yerel GPU beklenen çalışma profilinde anlaşılır
  kontrol/diagnostic ver; yüzlerce saniye sessiz bekleme davranışını gizleme.
- Başarılı runtime/image sürümünü ve kalıcı compose değişikliğini kaydet.
  Runtime düzeltmesi agent reposunda yapılmış gibi raporlanmasın; dosya yolu
  ve diff'i ayrıca teslim et. Restart tek başına kalıcı çözüm diye sunulmasın.

2) Sonra sınırlı uygulama düzeltmesi

- Offset'i ConversationService → ConversationMemoryRepository boyunca geçir.
  Geçersiz offset'i doğrula, parametreli SQL OFFSET uygula, sıralamaya session_id
  gibi deterministik bağlayıcı ekle. Fallback'i sırf log kaybolsun diye kaldırma.
  Tenant/user/page filtreleri ve mevcut UI sonuçları korunmalı.
- Tek embedding yapılandırması kullan: provider=ollama,
  model=qwen3-embedding:4b, boyut=1536, ayrı base URL ve kısa timeout.
  Ortam değişkeni isimlerini .env.example ve README'de açıkça belgeleyebilirsin.
  Mevcut kurulu modeli kullan; nomic indirme veya sessiz OpenAI fallback yapma.
- Eski deprecated langchain_community.OllamaEmbeddings yerine küçük, açık
  Ollama /api/embed adapter'ı kullanmak yeterli. Mevcut HTTP olanaklarını kullan;
  gereksiz yeni paket ekleme. Query/document rolünü ayır; Qwen query talimatını
  uyguluyorsan belgelerde de aynı metni otomatik kullanma ve şablonu sabitle.
- Önce gerçek kurulu model/API üzerinde sentetik metinle dimensions=1536
  desteğini doğrula. Model 2560 dönerse bunu gizleme; boyut doğrulamasında dur.
  Doğrulanmış 1536 çıktıyla mevcut vector(1536) kolonu korunabilir.
  Sıfır doldurma veya model değişikliğini yalnız etiketle çözdüğünü varsayma.
- Eski model vektörleri ile yeni Qwen vektörlerini aynı aramada karıştırma.
  Mevcut metadata üzerinden model/boyut/profil işaretle ve aramayı aynı profile
  sınırla. Bilinmeyen eski profil otomatik Qwen sayılmasın. Mesajları silmeden
  kontrollü, tekrar çalıştırılabilir backfill komutu sun; backfill'i onaysız
  topluca çalıştırma. Büyük şema migration'ı bu dar düzeltmenin ilk tercihi değil.
- Yeni model için eski sabit benzerlik eşiğini doğru kabul etme; küçük sentetik
  Türkçe ve diller arası retrieval setinde sonuçları kontrol et ve ayarı belge.
- Uygun geçmiş vektörü yoksa query embedding üretmeden boş retrieval dön.
  Embedding kapalı/erişilemez durumda cevap ve konuşma kaydı kaybolmamalı;
  isteğe bağlı semantik retrieval durumu açıkça raporlanmalı. DB/kimlik hatasını
  sessiz embedding hatasına dönüştürme. Yeni background job sistemi ekleme.
- AUTH_DISABLED yerel profilindeki beklenen RBAC fallback tekrarlarını azalt;
  production JWT/rol kontrollerini gevşetme. Development-server ve favicon
  mesajlarını performans arızasıyla karıştırma.
- Repository connection string/parola parçalarını loglama; mevcut connection
  string[:50] debug/info satırlarını da güvenli biçime getir.

Teslim/kanıt

- Altyapı değişikliği ile uygulama değişikliğini ayrı göster; uygulama değişikliği
  odaklı ayrı commit olsun. Mevcut A01 PR'a eklenecekse son head SHA'yı ver ve
  inceleme/UAT'i tekrar BEKLEMEDE bırak. Kendiliğinden merge veya A02 yapma.
- Mevcut 45 testi koru. Offset pagination için iki farklı sayfa/tenant testi;
  embedding provider/model/dimensions/timeout/profile izolasyonu için adapter
  testleri; gerçek Qwen embedding smoke ve Türkçe/diller arası retrieval deneyi.
- Gerçek GPU/model testlerini mock'lardan ayrı raporla. Önce/sonra toplam süre,
  load süresi ve mümkünse model token/s bilgilerini kaydet. Yeni araç, skill veya
  MCP ekleme; bu mevcut runtime'ın çalışma düzeltmesidir.
- Kullanıcı için kısa UAT: iki mesajlık belge konuşması, yenileme/geçmiş,
  Türkçe retrieval ve sonrasında container GPU kontrolü. Yapılmayan testleri
  açıkça bildir. Teslimden sonra DUR.
```

## Resmî kaynaklar

- [NVIDIA container GPU erişim kaybı](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/troubleshooting.html)
- [Ollama GPU durumu](https://docs.ollama.com/faq)
- [Qwen3 Embedding 4B model kartı](https://huggingface.co/Qwen/Qwen3-Embedding-4B)
- [Ollama embed API ve dimensions](https://docs.ollama.com/api/embed)
