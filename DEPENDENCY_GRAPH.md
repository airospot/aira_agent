# Bağımlılık grafiği

## Ekran ve API

1. `GET /agent/` → `agent.home` → `home.html`
2. `GET /agent/assistant` → `agent.assistant` → `assistant.html`
3. `POST /agent/assistant/propose` → `agent.assistant_propose` → `run_knowledge_agent`
4. Şablon: `assistant.html` → `agent_chat_layout.html` → `base.html`
5. Statik: `agent_static` → `css/app.css`, `js/assistant.js`
6. Assistant prose: Jinja `assistant_markdown` → `interfaces/web/assistant_markdown.py` (`render_assistant_markdown`)
   ← `assistant.html` turn/reply bubbles; escape-first limited Markdown (tables, corpus images/links)

## Runner

`run_knowledge_agent` → `create_flow_llm_client` → `run_agent_loop` → `request_model_decision` → `_execute_tool` (`file_read` / `file_search` / `file_name_search` / `show_image`)

Sistem prompt: `flow/execution/decision/agent_system_prompt.py`

## Bellek

`flow/memory/bridge.py` → conversation service → PostgreSQL

## Tool veri

- Corpus: `AGENT_CORPUS_DIR` (varsayılan `data/corpus`)
