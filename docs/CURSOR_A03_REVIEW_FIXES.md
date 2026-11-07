# A03 inceleme — .env ve ölçülen yerel context

İncelenen HEAD: `57a9f60`. Bağımsız suite: `128 passed`, izole NATIVE_FLOW_A00_TEST dahil. Merge/A04 yok.

## .env incelemesi

Altı AGENT_* bütçesi `.env` → config.py/app.py overlay → parse_run_policy → ExecutionContext/runner hattında okunuyor. Eksik/geçersiz config için runtime sayısal fallback yok; bu kullanıcı talebine uygun. run_policy.py içindeki RECOMMENDED_RUN_POLICY sayıları dokümantasyon/test önerisi; runtime fallback olarak kullanılmıyor. Bunları işlevsel hata diye kaldırma zorunluluğu yok; tek örnek profil kaynağı tercih edilirse test fixture'a taşınabilir.

Ancak LLM client local dalında num_ctx=8192 ve max_tokens=2048 hâlâ sabit. Ayrıca Ollama context/thinking kontrolü kullanılan endpoint'te doğru uygulanmıyor. Bütçe ayarları taşınmış olması bu sağlayıcı ayarlarının da taşındığı anlamına gelmiyor.

## Gerçek ölçümler (2026-11-07, sentetik veri)

- Ollama 0.32.0; model qwen3.5:9b Q4_K_M. /api/show: qwen35.context_length=262144. Bu model kapasitesi, çalışma ayarı veya kalite garantisi değildir.
- GPU: RTX 5090 Laptop, 24463 MiB. Çalışan model GPU yerleşimi /api/ps ile doğrulandı.
- Servis env: OLLAMA_CONTEXT_LENGTH=8192.
- Aynı 110075 UTF-8 byte çok dilli metin, baş/orta/son üç kontrol kodu. Native /api/chat, think=false, num_predict=128:
  - num_ctx=8192: prompt_eval_count=4098, 2.37 sn; baş/orta kodları korunmadı, hedef cevap alınamadı.
  - num_ctx=32768: prompt_eval_count=16386, 8.16 sn; hedef cevap alınamadı, çıktı length ile bitti.
  - num_ctx=65536: prompt_eval_count=39666, output=38 token, 13.44 sn; üç kodun tamamı doğru, done_reason=stop. /api/ps context_length=65536; size=size_vram=7825134714 byte (yaklaşık 7.29 GiB).
- Mevcut /v1/chat/completions biçiminde options.num_ctx=65536 verilmesine rağmen /api/ps 8192 gösterdi: bu alana dayanarak context ayarlanmış sayılamaz.
- Aynı uçta think=false + max_tokens=16 çağrısı boş content, reasoning ve finish_reason=length döndürdü. Ayrı kısa kontrolde reasoning_effort=none geçerli ANSWER JSON, 11 output token ve finish_reason=stop verdi. İki kontrolün prompt/output bütçeleri farklı; kalite benchmark'ı değil, endpoint seçeneklerinin doğrulanmasıdır.

Kanıt dosyası bu çalışma ortamında `/tmp/aira_context_probe_results.json`; kişisel belge/secrets yok. Genel bağlam kalitesi veya bütün belgelerde 64K doğruluk iddiası değildir.

## Düzeltmeler

1. **Ollama transport/ayarları:** Yerel context'i gerçekten uygulanan mekanizmayla ayarla. Tercih: mevcut client'ın açıkça Ollama olarak yapılandırılmış kolunda /api/chat kullan; num_ctx/num_predict/think doğru native alanlarla gönderilsin. Cloud Chat Completions davranışını koru; yeni framework/genel provider sistemi kurma. Alternatif olarak mevcut /v1 yolu korunacaksa context'i model alias Modelfile'da ayarla ve /api/ps ile kanıtla; desteklenmeyen options alanını göndermek çözüm değildir. .env'deki num_ctx tek başına /v1 üzerinde etkiliymiş gibi sunulmasın.
2. Yerel ayarları `.env`/`.env.example` ve overlay/config/factory hattına al: KNOWLEDGE_FLOW_LLM_CONTEXT_TOKENS=65536, KNOWLEDGE_FLOW_LLM_MAX_OUTPUT_TOKENS=2048, KNOWLEDGE_FLOW_LLM_THINK=false. İsimler proje standardıyla uyarlanabilir; etkin değer tek kaynaktan gelsin. Boolean'ı bool('false') ile parse etme. Kullanıcı isteği gereği bu yeni sayısal ayarlar için gizli code fallback kullanma.
3. Thinking metnini karar JSON'u yerine parse etme. Empty content / finish_reason=length / native done_reason=length için kodlu output_limit veya malformed response ayrımı ve güvenli kullanıcı mesajı üret. Reasoning içinden süslü parantez arayıp başarılı karar çıkarma. Büyük TXT UAT FlowLlmClientError'ın kesin nedenini metadata ile doğrula; yalnız context'e bağlama.
4. **Gerçek serialize boyutu:** context_builder compact JSON ile sayıyor, client json.dumps varsayılan boşluklu biçim gönderiyor. Aynı örnekte 1616 vs 1816 byte ölçüldü. Builder/client aynı serializer kullansın; redaction sonrası gerçek gönderilen system+user metni üzerinden son kontrol yapılsın. Trace limiti aşılmadı derken gerçek metin aşılmasın. Chat şablonu/provider framing ve tokenlar ayrı kavramlardır.
5. **ToolExecutor tek çağrı:** _invoke_handler inspect.signature ile parametreyi seçtikten sonra handler içindeki TypeError'ı yakalayıp handler'ı ikinci kez çalıştırıyor. Bu implicit retry olup bütçe/yan etki politikasını aşabilir. Signature'a göre tek çağrı yap; handler gövdesindeki TypeError tekrar çağrıya sebep olmasın. Sayaçlı handler regresyon testi ekle.

## Profil kararı

64K gerçek model context'i uygulandıktan sonra mevcut başlangıç bütçelerini şimdilik koru:

```dotenv
AGENT_MAX_STEPS=8
AGENT_RUN_TIMEOUT_SECONDS=180
AGENT_TOOL_TIMEOUT_SECONDS=15
AGENT_MAX_OBSERVATION_BYTES=65536
AGENT_MAX_CONTEXT_BYTES=131072
AGENT_MAX_TOOL_RETRIES=1
```

128 KiB byte limiti token limiti değildir. Ölçülen 110 KB karışık metin ~39.7K token tuttu; dil/veri değişince oran değişir. 64K toplam pencerede output ve chat template payı ayrılmalı. Bütçenin her olası metni kesinlikle 64K'ya sığdırdığını iddia etme. Bu aşamada ağır tokenizer dependency/RAG/chunk pipeline ekleme. Provider truncation/usage farklarını ölçüp raporla; gerekiyorsa ölçülen profil için byte limitini düşür. Modelin 262K üst kapasitesini varsayılan yapma.

Orijinal .env secret değerlerini commit/log etme. Donanım/servis global ayarlarını kullanıcıdan habersiz değiştirme. Agent çağrısının gerçek context'i /api/ps veya servis kanıtıyla 65536 olmalı; OCR/embedding gibi diğer tüketicilere kör global override yapma.

## Teslim ve kabul

- Config missing/invalid testleri; native/OpenAI transport request contract testleri; thinking-off ve output-limit testi; gerçek serialized context sınırı; TypeError handler yalnız tek execution.
- Mevcut suite ve izole PG; skip ayrı bildirilsin.
- Gerçek agent yolu ile sentetik büyük TXT tekrar: başarılı veya anlaşılır coded STOP_INCOMPLETE; ham FlowLlmClientError ve sessiz provider truncation PASS değil.
- 04 dosyası takip sorusu ve 03 dosyası görsel regresyonu; yeni ayarlarla /api/ps context ve GPU doğrulaması.
- SHA + sonuç + UAT BEKLEMEDE/kanıtları ayrı; merge/A04 yok. PR #5'in PR #4 üzerine dayandığını kaydet; PR #4 merge yetkisi çıkarma.

Resmî referanslar: https://docs.ollama.com/api/openai-compatibility (context Modelfile ve reasoning_effort), https://docs.ollama.com/context-length (etkin context/GPU kontrolü).
