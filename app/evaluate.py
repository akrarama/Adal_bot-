"""Автопроверка качества: python -m app.evaluate

Прогоняет вопросы из tests/questions.json через RAG и проверяет:
  - для обычных вопросов: бот ответил и в ответе есть хотя бы одно ожидаемое слово;
  - для no_info: бот честно сказал, что подтверждённой информации нет.
"""
import asyncio
import json
from pathlib import Path

from . import rag

CASES = Path(__file__).resolve().parent.parent / "tests" / "questions.json"


async def main() -> None:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    ok = 0
    for c in cases:
        res = await rag.answer(c["q"])
        text = res.text.casefold()
        if c.get("no_info"):
            passed = not res.answered
        else:
            passed = res.answered and any(k.casefold() in text for k in c["expect_any"])
        ok += passed
        dist = f"{res.best_dist:.2f}" if res.best_dist is not None else "—"
        print(("PASS" if passed else "FAIL"), "|", c["q"], f"(dist={dist})")
        if not passed:
            print("      ->", res.text[:250].replace("\n", " "))
        await asyncio.sleep(8)  # бережём лимиты бесплатного Gemini
    print(f"\nИтого: {ok}/{len(cases)}")


if __name__ == "__main__":
    asyncio.run(main())
