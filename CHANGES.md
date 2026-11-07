# Başlangıç için yapılan zorunlu değişiklikler

Kaynak uygulamadaki runner, Agent route, tool ve şablon dosyaları değiştirilmedi.
Aşağıdaki farklar yalnız paketin `python app.py` ile ayağa kalkması içindir.

| Paket dosyası | Kaynak | Gerekçe |
| --- | --- | --- |
| `app.py` | Yok. Karşılığı `airacoder_new_version/app/__init__.py` içindeki `create_app`. | Kaynak factory Socket.IO, tüm ürün blueprint'leri ve veritabanı önbelleğini başlatır. Bu dosya yalnız Agent blueprint'ini `/agent` altına kaydeder, `assistant_markdown` filtresini bağlar, statik dosyayı sunar ve JWT ön kontrolünü kaynak `register_aira_knowledge` ile aynı yolda çalıştırır. `register_aira_knowledge` çağrılmaz; o fonksiyon diğer Knowledge blueprint'lerini yükler ve import hatalarını yutar. |
| `app/__init__.py` | `app/__init__.py` | Kaynak modül tüm AiraCoder uygulamasını kurar. Paket kökü boş bırakıldı. |
| `app/core/__init__.py` | `app/core/__init__.py` | Kaynak, monolith `Config` sınıfını ve `config_manager` yeniden ihracını import anında yükler. |
| `app/domain/agents/__init__.py` | `app/domain/agents/__init__.py` | Kaynak; code analyzer, tool router ve intent classifier'ı import anında yükler. Flow belleği yalnız `memory_service` çağırır. `from app.domain.agents import memory_service` yolu duruyor. |
| `app/domain/aira_knowledge/agents/knowledge/__init__.py` | aynı yol | Kaynak, `run_dynamic_supervisor` / `run_bounded_supervisor` yükler. Native Flow girişi `flow/execution/run_knowledge_agent.py`. |
| `app/adapters/db/airacoder/repositories/__init__.py` | aynı yol | Kaynak, git ve workflow dahil tüm repository'leri import anında yükler. Flow'un kullandığı alt modül yolları duruyor. |
| `app/adapters/db/aira_knowledge/catalog/__init__.py` | aynı yol | Kaynak, snapshot ve live catalog provider yükler. Live query yalnız `sqlserver_connection.connect_sqlserver` kullanır. |
| `app/domain/aira_knowledge/entities/aira_knowledge/toshiba/__init__.py` | aynı yol | Kaynak, `ToshibaFieldRecommendationPack` yükler. Flow yalnız `object_match_rules.normalize_object_key` kullanır. |
| `app.py` içinde `postgresql://` → `postgresql+psycopg2://` | `DATABASE_URL` | SQLAlchemy 2.1 düz `postgresql://` şemasını psycopg v3 sürücüsüne bağlar. Bellek katmanı psycopg2 kullanır. Ham `DATABASE_URL` psycopg2 çağrıları için aynı kalır. |
| `app.py` kabuk endpoint'leri | `templates/base.html` | Şablon `dashboard.index`, `knowledge.release_notes` ve diğer Knowledge sayfalarına `url_for` üretir. Bu sayfalar pakette yok. Endpoint adları 404 döner; veri uydurulmaz. |
| Dahil edilmeyen `config_builder.py` ve `project_runtime` | `config_manager.update_knowledge_graph_settings` | Bu yol Neo4j/kod çalışma alanı içindir. Flow belleği `get_config` kullanır. Kaynak zaten `ImportError` yakalar. Modüller pakete alınmadı. |

Göreli veri yolları başlangıçta paket köküne çözülür. Amaç, `python /yol/app.py` komutunun çalışma dizinine bağlı kalmamasıdır.
