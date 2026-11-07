# Embedding profile (Ollama Qwen3)

Tek yapılandırma:

| Anahtar | Değer |
| --- | --- |
| provider | `ollama` |
| model | `qwen3-embedding:4b` |
| dimensions | `1536` (API `dimensions` parametresi; varsayılan model çıktısı 2560) |
| profile tag | `ollama:qwen3-embedding:4b:d1536` |

Ortam:

- `KNOWLEDGE_FLOW_EMBED_BASE_URL` (yoksa `OLLAMA_BASE_URL` / `http://127.0.0.1:11434`)
- `KNOWLEDGE_FLOW_EMBED_MODEL`
- `KNOWLEDGE_FLOW_EMBED_DIMENSIONS`
- `KNOWLEDGE_FLOW_EMBED_TIMEOUT_SECONDS` (varsayılan 8)

Query rolü sabit Qwen talimatı kullanır; document rolü ham metindir. Boyut uyuşmazlığında pad/truncate yok.

Semantik arama yalnız `metadata.embedding_profile` eşleşen satırlarda çalışır. Bilinmeyen eski vektörler otomatik Qwen sayılmaz.

Benzerlik eşiği (bu profil): `DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD = 0.45`.

Sentetik ölçüm (canlı `qwen3-embedding:4b`, dimensions=1536):

| sorgu | tr_invoice | en_invoice | tr_unrelated |
| --- | ---: | ---: | ---: |
| TR: fatura ne zaman ödenmeli | 0.697 | 0.651 | 0.204 |
| EN: when is the invoice due | 0.481 | 0.678 | 0.163 |

Eski 0.7 eşiği OpenAI/nomic karışımı içindi; EN→TR çiftini keserdi.

Backfill: `python scripts/backfill_conversation_embeddings.py --dry-run` (onaysız toplu çalıştırma yok).
