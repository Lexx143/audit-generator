"""Разовая нормализация выпадающего списка частых уязвимостей.

Берет текущий db/hints.json (сырые заголовки кейсов с дублями и нумерацией),
прогоняет через LLM: дедуп, единый стиль формулировок, категории.
Перезаписывает hints.json объектами {text, category} и перестраивает
chroma-коллекцию audit_hints (индекс для семантического дедупа).

Запуск: ./venv/bin/python normalize_hints.py
"""
import asyncio
import hashlib
import json
from typing import Literal

from pydantic import BaseModel

import config
import rag
from llm import client


class Hint(BaseModel):
    text: str
    category: Literal[
        "I. Серверная инфраструктура",
        "II. Сеть и ИТ-поддержка",
        "III. Безопасность",
        "IV. 1C",
        "V. Видеонаблюдение и СКУД",
        "VI. Прочее",
    ]


class HintList(BaseModel):
    hints: list[Hint]


PROMPT = """
Ниже сырой список "частых уязвимостей" для выпадающего списка в генераторе ИТ-аудитов.
Он копился автоматически из заголовков кейсов: есть дубли, нумерация чужих отчетов
("Кейс 7: ..."), обрывочные и непонятные без контекста записи.

Приведи его в порядок:
1. Убери нумерацию "Кейс N:" — оставь суть.
2. Объедини семантические дубли в одну лучшую формулировку
   (например "Кабельменеджмент" / "Кабель-менеджмент в сетевом шкафу" / "Слабый кабель-менеджмент" -> одна запись).
3. Единый стиль: короткая констатация проблемы, 3-9 слов
   ("Отсутствует резервное копирование", "RDP опубликован в интернет", "Используется устаревшая несерверная ОС").
4. Обрывочные записи ("Share", "Облако", "Работа над ошибками") разверни в понятную формулировку,
   если суть ясна; если восстановить смысл нельзя — выброси.
5. Слишком специфичные для одного клиента записи (модель конкретного MacBook, конкретный домен) обобщи или выброси.
6. Каждой записи назначь категорию из списка. Внутри списка не должно остаться двух записей об одном и том же.

СЫРОЙ СПИСОК:
{raw}
"""


async def main():
    with open(config.HINTS_FILE) as f:
        raw = json.load(f)
    raw_texts = [h["text"] if isinstance(h, dict) else h for h in raw]
    print(f"На входе: {len(raw_texts)}")

    response = await client.beta.chat.completions.parse(
        model=config.TEXT_MODEL,
        reasoning_effort=config.REASONING_EFFORT,
        messages=[
            {"role": "system", "content": "Ты редактор базы знаний ИТ-аудитора. Наводишь порядок в справочниках."},
            {"role": "user", "content": PROMPT.format(raw=json.dumps(raw_texts, ensure_ascii=False, indent=1))},
        ],
        response_format=HintList,
    )
    hints = response.choices[0].message.parsed.hints

    # Точные дубли на всякий случай
    seen, clean = set(), []
    for h in hints:
        key = h.text.lower()
        if key not in seen:
            seen.add(key)
            clean.append({"text": h.text, "category": h.category})

    rag.save_hints(clean)
    print(f"На выходе: {len(clean)}")

    # Перестраиваем дедуп-индекс
    existing = rag.hints_collection.get()
    if existing["ids"]:
        rag.hints_collection.delete(ids=existing["ids"])
    rag.hints_collection.upsert(
        documents=[h["text"] for h in clean],
        ids=[hashlib.md5(h["text"].encode("utf-8")).hexdigest() for h in clean],
        metadatas=[{"category": h["category"]} for h in clean],
    )
    print(f"Индекс audit_hints: {rag.hints_collection.count()}")

    by_cat = {}
    for h in clean:
        by_cat.setdefault(h["category"], []).append(h["text"])
    for cat in rag.HINT_CATEGORIES:
        if cat in by_cat:
            print(f"\n{cat} ({len(by_cat[cat])}):")
            for t in sorted(by_cat[cat]):
                print(f"  - {t}")


if __name__ == "__main__":
    asyncio.run(main())
