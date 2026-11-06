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

PostgreSQL ve pgvector:

```bash
python migrations/create_conversation_memory_table.py
python migrations/add_embedding_to_conversation_memory.py
psql "$DATABASE_URL" -f schema/structured_memory.sql
```

İlk betik `conversation_memory` tablosunu kurar. İkincisi `embedding vector(1536)` kolonunu ekler. `schema/structured_memory.sql`, kaynakta migration'ı olmayan `extracted_memory` ve `memory_event_log` tablolarının ORM karşılığıdır.

`ConversationMemory.user_id` modeli `users.user_id` ilişkisi taşır. Kaynak migration bu yabancı anahtarı yaratmaz. Kullanıcı tablosu yoksa bellek satırı, ilişki JOIN'i çalışana kadar yazılabilir.

## Başlatma

Paket kökünde:

```bash
python app.py
```

Native Flow ekranı: <http://127.0.0.1:5000/agent/assistant>

POST API: `/agent/assistant/propose`

Sağlık: `/health`

Ekran JWT ister. Kimlik doğrulama `app/core/security.py` üzerinden dış Auth Provider'a gider. `AUTH_PROVIDER_URL` boşsa varsayılan `https://auth.airaintelligence.ai` olur.

CONFIG araması için `KNOWLEDGE_FLOW_CONFIG_CORPUS_CUSTOMER_ALLOWLIST` dolu olmalıdır. Boş liste isteği reddeder.

## Sistem paketleri

`pyodbc` import'u `libodbc.so.2` ister (`unixodbc`). `database_live_query` ayrıca Microsoft ODBC Driver 17 veya 18 ister. Sürücü yoksa araç hata döner; sonuç uydurulmaz.

## Dış servisler

| Servis | Ayar | Kullanan |
| --- | --- | --- |
| OpenAI uyumlu LLM | `KNOWLEDGE_FLOW_LLM_BASE_URL`, `KNOWLEDGE_FLOW_LLM_MODEL`, `KNOWLEDGE_FLOW_LLM_API_KEY` | `FlowLlmClient` |
| Auth Provider JWKS | `AUTH_PROVIDER_URL`, `AUTH_SITE_SLUG` | `jwt_required` |
| PostgreSQL | `DATABASE_URL` | konuşma belleği |
| SQL Server | `SQLSERVER_*`, `SQLSERVER_QUERY_*` | `database_live_query` |
| Rerank proxy | `RERANK_BASE_URL` | `config_parameter_semantic_rerank` |

Anlamsal uzun süreli bellek, çağrı anında `langchain_openai` veya `langchain_community` embedding sınıflarını yükler. Bu paketler `requirements.txt` içindedir.

Ayrıntı: `CHANGES.md`, `DEPENDENCY_GRAPH.md`, `TOOLS.md`, `VERIFICATION.md`.
