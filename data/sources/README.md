Положите сюда официальные документы (.md / .txt / .pdf) и запустите `python -m app.ingest`.

Формат .md/.txt:

```
title: Конституция Республики Казахстан (2026)
url: https://adilet.zan.kz/...
type: constitution
lang: ru

Статья 1. ...
```

Типы: constitution | law | address | concept | other.
Берите тексты ТОЛЬКО с официальных сайтов (adilet.zan.kz, akorda.kz, egov.kz) и обязательно указывайте url.
Файл README.md не загружается в базу.
