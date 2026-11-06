# Native tool kayıtları

Kayıt yeri: `run_knowledge_agent` → `permitted_tools`. Her araç kendi `tool.json` adını taşır.

| Tool | Uygulama | Veri |
| --- | --- | --- |
| `file_name_search` | `flow/tools/file_name_search/execute.py` | `AGENT_CORPUS_DIR` — dosya adı / path |
| `file_search` | `flow/tools/file_search/execute.py` | Aynı corpus — yalnız içerik |
| `file_read` | `flow/tools/file_read/execute.py` | Aynı corpus; kök dışına çıkamaz |
| `show_image` | `flow/tools/show_image/execute.py` | Corpus imaj path → `/agent/corpus/...` display_url |

Şema ve sonuç sözleşmeleri her klasörde `tool.json` ve `result.json` dosyalarıdır.
