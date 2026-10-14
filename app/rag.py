from dataclasses import dataclass

from . import config, db, llm

KK_LETTERS = set("әіңғүұқөһӘІҢҒҮҰҚӨҺ")

NO_INFO = {
    "ru": "К сожалению, в моей базе официальных источников нет подтверждённой информации по этому вопросу. "
    "Попробуйте переформулировать запрос или обратитесь к первоисточникам: adilet.zan.kz, akorda.kz.",
    "kk": "Өкінішке қарай, менің ресми дереккөздер базамда бұл сұрақ бойынша расталған ақпарат жоқ. "
    "Сұрақты өзгертіп көріңіз немесе бастапқы дереккөздерге жүгініңіз: adilet.zan.kz, akorda.kz.",
}

SYSTEM = """Ты — «Адал қоғам AI»: справочник-навигатор по внутренней политике и идеологической работе Казахстана.
Отвечай ТОЛЬКО на основе фрагментов официальных источников из блока КОНТЕКСТ. Свои знания не добавляй.
Правила:
1. Отвечай на языке вопроса ({lang_name}).
2. Структурируй ответ кратко и понятно; после утверждений ставь ссылки на источники вида [1], [2].
3. Если в КОНТЕКСТЕ нет ответа на вопрос, ответь ровно одним словом: NO_INFO. Ничего не придумывай и не предполагай.
4. Если понятие/принцип/ценность из вопроса упомянуто в источнике типа «constitution» (Конституция 2026), обязательно прямо укажи это и назови статью/раздел.
5. Это справочная информация, а не юридическая консультация; не давай личных политических оценок.
6. Не используй Markdown-разметку (никаких ** и #). Пиши обычным текстом, списки через тире."""


@dataclass
class Answer:
    text: str
    sources: list[dict]
    answered: bool
    lang: str
    best_dist: float | None


def detect_lang(text: str) -> str:
    return "kk" if any(ch in KK_LETTERS for ch in text) else "ru"


def search(conn, qvec: list[float]) -> list[dict]:
    rows = conn.execute(
        """
        SELECT c.content, c.section, d.title, d.url, d.doc_type,
               c.embedding <=> %s::vector AS dist
        FROM chunks c JOIN documents d ON d.id = c.doc_id
        ORDER BY dist
        LIMIT %s
        """,
        (qvec, config.TOP_K),
    ).fetchall()
    keys = ("content", "section", "title", "url", "doc_type", "dist")
    return [dict(zip(keys, r)) for r in rows]


async def answer(question: str, user_id: int | None = None) -> Answer:
    lang = detect_lang(question)
    try:
        [qvec] = await llm.embed([question], query=True)
        with db.connect() as conn:
            hits = [h for h in search(conn, qvec) if h["dist"] <= config.MAX_DISTANCE]
            best = min((h["dist"] for h in hits), default=None)

            if not hits:
                _log(conn, user_id, lang, question, False, None)
                return Answer(NO_INFO[lang], [], False, lang, None)

            context = "\n\n".join(
                f"[{i}] (тип: {h['doc_type']}; документ: {h['title']}; раздел: {h['section'] or '—'})\n{h['content']}"
                for i, h in enumerate(hits, 1)
            )
            prompt = f"КОНТЕКСТ:\n{context}\n\nВОПРОС: {question}"
            text = await llm.generate(
                SYSTEM.format(lang_name="казахский" if lang == "kk" else "русский"), prompt
            )

            if not text or text.strip().strip(".").upper() == "NO_INFO":
                _log(conn, user_id, lang, question, False, best)
                return Answer(NO_INFO[lang], [], False, lang, best)

            used = [i for i in range(1, len(hits) + 1) if f"[{i}]" in text] or [1]
            sources = [
                {"n": i, "title": hits[i - 1]["title"], "section": hits[i - 1]["section"], "url": hits[i - 1]["url"]}
                for i in used
            ]
            _log(conn, user_id, lang, question, True, best)
            return Answer(text, sources, True, lang, best)
    except Exception as e:  # обработка ошибок: бот не должен падать
        print("RAG error:", repr(e))
        msg = {
            "ru": "Произошла техническая ошибка. Пожалуйста, повторите запрос чуть позже.",
            "kk": "Техникалық қате орын алды. Сәлден соң қайталап көріңіз.",
        }[lang]
        return Answer(msg, [], False, lang, None)


def _log(conn, user_id, lang, q, answered, dist):
    conn.execute(
        "INSERT INTO query_log (user_id, lang, question, answered, best_dist) VALUES (%s,%s,%s,%s,%s)",
        (user_id, lang, q[:500], answered, dist),
    )


def format_sources(sources: list[dict]) -> str:
    if not sources:
        return ""
    lines = []
    for s in sources:
        part = f"[{s['n']}] {s['title']}" + (f", {s['section']}" if s["section"] else "")
        if s["url"]:
            part += f" — {s['url']}"
        lines.append(part)
    return "\n\n📚 Источники:\n" + "\n".join(lines)
