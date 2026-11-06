# Doğrulama

| Kontrol | Sonuç | Gözlem |
| --- | --- | --- |
| `python app.py` | | `127.0.0.1:3000`, `GET /health` 200 |
| Statik | | `css/app.css`, `js/assistant.js` |
| UI | | `GET /agent/` ve `/assistant` |
| Tool kaydı | | Yalnız `file_read`, `file_search` |
| Tool smoke | | Corpus `README.md` okuma + arama |
| Bellek | | PostgreSQL `DATABASE_URL` |
