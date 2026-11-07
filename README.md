# Native Knowledge Flow

Taşınabilir paket. Ekran, API, runner ve native tool uygulamaları kaynaktaki halleriyle durur.

## Kurulum

Python 3.12 gerekir.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` içine gerçek `SECRET_KEY`, `DATABASE_URL` ve `KNOWLEDGE_FLOW_LLM_API_KEY` yazın. Bu değerler pakette yoktur.

`SECRET_KEY` boş veya placeholder olamaz. `AUTH_DISABLED` kapalıysa `LOGIN_UI_URL` zorunludur (varsayılan provider login yolu uydurulmaz). Yerel geliştirmede `AUTH_DISABLED=1` kullanılabilir.

Geliştirme testleri:

```bash
pip install -r requirements-dev.txt
# isteğe bağlı gerçek PG: ayrı DB (ör. NATIVE_FLOW_A00_TEST)
export A00_TEST_DATABASE_URL="postgresql://USER:PASS@127.0.0.1:5432/NATIVE_FLOW_A00_TEST"
pytest -q
```

PostgreSQL ve pgvector:

```bash
python migrations/create_conversation_memory_table.py
python migrations/add_embedding_to_conversation_memory.py
python migrations/create_agent_submissions_table.py
psql "$DATABASE_URL" -f schema/structured_memory.sql
```

İlk betik `conversation_memory` tablosunu kurar. İkincisi `embedding vector(1536)` kolonunu ekler. Üçüncüsü `agent_submissions` tablosunu kurar (tenant/user kapsamlı propose idempotency; PK: `customer_id, user_id, submission_id`). `schema/structured_memory.sql`, kaynakta migration'ı olmayan `extracted_memory` ve `memory_event_log` tablolarının ORM karşılığıdır.

Migration betikleri `DATABASE_URL` (veya zorunlu `POSTGRES_*`) ile bağlanır; süreç ortamı `.env` üzerine yazılmaz (`load_dotenv(..., override=False)`).

`ConversationMemory.user_id` modeli `users.user_id` ilişkisi taşır. Kaynak migration bu yabancı anahtarı yaratmaz. Kullanıcı tablosu yoksa bellek satırı, ilişki JOIN'i çalışana kadar yazılabilir.

## Başlatma

Paket kökünde:

```bash
python app.py
```

Native Flow ekranı: <http://127.0.0.1:5000/agent/assistant>

POST API: `/agent/assistant/propose`

Sağlık: `/health`

Ekran JWT ister (`AUTH_DISABLED` kapalıyken). Kimlik doğrulama `app/core/security.py` üzerinden dış Auth Provider'a gider; `LOGIN_UI_URL` gerçek giriş adresini tanımlar. `AUTH_PROVIDER_URL` boşsa varsayılan `https://auth.airaintelligence.ai` olur.

`POST /agent/assistant/propose` aynı `(customer_id, user_id, submission_id)` için tek agent çalışması rezervasyonu kullanır. Tamamlanan istek yeniden oynatılır; zaman aşımı/hata otomatik yeniden LLM çağırmaz. Aynı ID ile farklı soru/konuşma 400 döner.

CONFIG araması için `KNOWLEDGE_FLOW_CONFIG_CORPUS_CUSTOMER_ALLOWLIST` dolu olmalıdır. Boş liste isteği reddeder.

## Sistem paketleri

`pyodbc` import'u `libodbc.so.2` ister (`unixodbc`). `database_live_query` ayrıca Microsoft ODBC Driver 17 veya 18 ister. Sürücü yoksa araç hata döner; sonuç uydurulmaz.

## Dış servisler

| Servis | Ayar | Kullanan |
| --- | --- | --- |
| OpenAI uyumlu LLM | `KNOWLEDGE_FLOW_LLM_BASE_URL`, `KNOWLEDGE_FLOW_LLM_MODEL`, `KNOWLEDGE_FLOW_LLM_API_KEY` | `FlowLlmClient` |
| Auth Provider JWKS | `AUTH_PROVIDER_URL`, `AUTH_SITE_SLUG` | `jwt_required` |
| PostgreSQL | `DATABASE_URL` | konuşma belleği |
| Ollama embed | `KNOWLEDGE_FLOW_EMBED_BASE_URL`, `KNOWLEDGE_FLOW_EMBED_MODEL`, `KNOWLEDGE_FLOW_EMBED_DIMENSIONS`, `KNOWLEDGE_FLOW_EMBED_TIMEOUT_SECONDS` | `ollama_embed` / semantik bellek |
| SQL Server | `SQLSERVER_*`, `SQLSERVER_QUERY_*` | `database_live_query` |
| Rerank proxy | `RERANK_BASE_URL` | `config_parameter_semantic_rerank` |

Anlamsal uzun süreli bellek yalnız Ollama `qwen3-embedding:4b` + `dimensions=1536` profilini kullanır (`app/adapters/db/embeddings/ollama_embed.py`). OpenAI/nomic sessiz fallback yoktur. Profil etiketi: `docs/EMBEDDING_PROFILE.md`.

Ayrıntı: `CHANGES.md`, `DEPENDENCY_GRAPH.md`, `TOOLS.md`, `VERIFICATION.md`.
