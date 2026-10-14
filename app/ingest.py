"""Загрузка документов из data/sources в базу знаний.

Формат файла (.md / .txt): необязательная шапка с метаданными, пустая строка, текст:

    title: Конституция Республики Казахстан (2026)
    url: https://adilet.zan.kz/...
    type: constitution        # constitution | law | address | concept | other
    lang: ru                  # ru | kk

    Статья 1. ...

PDF тоже поддерживаются (метаданные берутся из имени файла).
Запуск:  python -m app.ingest
"""
import asyncio
import re
from pathlib import Path

from . import db, llm

SRC = Path(__file__).resolve().parent.parent / "data" / "sources"
HEADING = re.compile(r"^(Статья\s+\d+[\.\d]*|Раздел\s+[IVX\d]+|Глава\s+\d+|\d+-бап|\d+-тарау|Бап\s+\d+|Қағидат.*|Принцип.*)", re.I)
MAX_CHARS = 1200


def read_file(path: Path) -> tuple[dict, str]:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        text = "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
        return {"title": path.stem}, text
    raw = path.read_text(encoding="utf-8")
    meta: dict = {}
    head, _, body = raw.partition("\n\n")
    if re.match(r"^\s*(title|url|type|lang)\s*:", head, re.I):
        for line in head.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.split("#")[0].strip() if k.strip().lower() == "type" else v.strip()
    else:
        body = raw
    meta.setdefault("title", path.stem)
    return meta, body


def chunk(text: str) -> list[tuple[str | None, str]]:
    """Режем по абзацам, запоминаем текущий заголовок (статья/раздел), пакуем до MAX_CHARS."""
    chunks, section, buf = [], None, ""
    sec_of_buf = None
    for para in re.split(r"\n\s*\n|\n(?=(?:Статья|Раздел|Глава|Бап)\s)", text):
        para = para.strip()
        if not para:
            continue
        m = HEADING.match(para)
        if m:
            section = m.group(1).strip()
        if buf and (len(buf) + len(para) > MAX_CHARS or (m and buf)):
            chunks.append((sec_of_buf, buf))
            buf = ""
        if not buf:
            sec_of_buf = section
        # слишком длинный абзац — режем по предложениям
        while len(para) > MAX_CHARS:
            cut = para.rfind(". ", 0, MAX_CHARS)
            cut = cut + 1 if cut > 200 else MAX_CHARS
            chunks.append((section, (buf + "\n" + para[:cut]).strip()))
            buf, para = "", para[cut:].strip()
        buf = (buf + "\n\n" + para).strip()
    if buf:
        chunks.append((sec_of_buf, buf))
    return chunks


async def main() -> None:
    db.init_schema()
    files = [p for p in sorted(SRC.glob("*")) if p.suffix.lower() in {".md", ".txt", ".pdf"} and p.name != "README.md"]
    if not files:
        print(f"Нет файлов в {SRC}. Добавьте документы и запустите снова.")
        return
    with db.connect() as conn:
        for path in files:
            meta, body = read_file(path)
            parts = chunk(body)
            if not parts:
                continue
            conn.execute("DELETE FROM documents WHERE filename = %s", (path.name,))
            doc_id = conn.execute(
                "INSERT INTO documents (title, url, doc_type, lang, filename) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (meta["title"], meta.get("url"), meta.get("type", "other"), meta.get("lang"), path.name),
            ).fetchone()[0]
            vecs = await llm.embed([f"{meta['title']}. {s or ''}\n{t}" for s, t in parts])
            for (section, text), v in zip(parts, vecs):
                conn.execute(
                    "INSERT INTO chunks (doc_id, section, content, embedding) VALUES (%s,%s,%s,%s)",
                    (doc_id, section, text, v),
                )
            print(f"✓ {path.name}: {len(parts)} фрагментов")


if __name__ == "__main__":
    asyncio.run(main())
