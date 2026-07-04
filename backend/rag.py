import hashlib
import os
import json
import re
import uuid

import chromadb
from chromadb.utils import embedding_functions

import config

chroma_client = chromadb.PersistentClient(path=config.CHROMA_PATH)

openai_ef = embedding_functions.OpenAIEmbeddingFunction(
    api_key=config.OPENAI_API_KEY,
    model_name=config.EMBEDDING_MODEL,
)

cases_collection = chroma_client.get_or_create_collection(
    name="audit_cases", embedding_function=openai_ef
)
conclusions_collection = chroma_client.get_or_create_collection(
    name="audit_conclusions", embedding_function=openai_ef
)
# Полные структурированные кейсы из прошлых аудитов — few-shot примеры для генерации
case_examples_collection = chroma_client.get_or_create_collection(
    name="audit_case_examples", embedding_function=openai_ef
)
# Индекс подсказок для семантического дедупа выпадающего списка
hints_collection = chroma_client.get_or_create_collection(
    name="audit_hints", embedding_function=openai_ef
)

HINT_CATEGORIES = [
    "I. Серверная инфраструктура",
    "II. Сеть и ИТ-поддержка",
    "III. Безопасность",
    "IV. 1C",
    "V. Видеонаблюдение и СКУД",
    "VI. Прочее",
]
# Ближе этого порога (cosine distance) считаем подсказку дублем существующей.
# Замер на реальных данных: перефразы 0.15-0.38, новые темы 0.44+.
HINT_DEDUP_THRESHOLD = 0.40


def retrieve_case_examples(query: str, n: int = 3) -> list[str]:
    try:
        res = case_examples_collection.query(query_texts=[query], n_results=n)
        return res["documents"][0] if res["documents"] else []
    except Exception:
        return []


def retrieve_case_phrases(query: str, n: int = 5) -> list[str]:
    try:
        res = cases_collection.query(query_texts=[query], n_results=n)
        return res["documents"][0] if res["documents"] else []
    except Exception:
        return []


def retrieve_conclusion_examples(query: str, n: int = 3) -> list[str]:
    try:
        res = conclusions_collection.query(query_texts=[query], n_results=n)
        return res["documents"][0] if res["documents"] else []
    except Exception:
        return []


def get_hints() -> list:
    """Возвращает подсказки как [{text, category}], отсортированные по категории."""
    if not os.path.exists(config.HINTS_FILE):
        return []
    with open(config.HINTS_FILE, "r") as f:
        raw = json.load(f)
    hints = [
        {"text": h, "category": "VI. Прочее"} if isinstance(h, str) else h
        for h in raw
    ]
    order = {c: i for i, c in enumerate(HINT_CATEGORIES)}
    hints.sort(key=lambda h: (order.get(h.get("category"), 99), h["text"].lower()))
    return hints


def save_hints(hints: list):
    if not os.path.exists("db"):
        os.makedirs("db")
    with open(config.HINTS_FILE, "w") as f:
        json.dump(hints, f, ensure_ascii=False, indent=2)


def normalize_hint_text(text: str) -> str:
    """Убирает нумерацию вида 'Кейс 3:' и приводит формулировку в порядок."""
    text = re.sub(r"^\s*Кейс\s*№?\s*\d+\s*[:.\-—]\s*", "", text, flags=re.IGNORECASE)
    text = " ".join(text.split()).strip(" .")
    if text:
        text = text[0].upper() + text[1:]
    return text


def add_hint(text: str, category: str = "VI. Прочее") -> bool:
    """Добавляет подсказку, если семантически похожей еще нет. True если добавили."""
    text = normalize_hint_text(text)
    if len(text) < 8:
        return False
    if category not in HINT_CATEGORIES:
        category = "VI. Прочее"

    try:
        if hints_collection.count() > 0:
            res = hints_collection.query(query_texts=[text], n_results=1)
            if res["distances"][0] and res["distances"][0][0] < HINT_DEDUP_THRESHOLD:
                return False
    except Exception:
        pass

    hints = get_hints()
    hints.append({"text": text, "category": category})
    save_hints(hints)
    hints_collection.upsert(
        documents=[text],
        ids=[hashlib.md5(text.encode("utf-8")).hexdigest()],
        metadatas=[{"category": category}],
    )
    return True


def save_report_to_memory(data):
    """Сохраняет кейсы и выводы сгенерированного отчета в базу знаний RAG."""
    for case in data.cases:
        case_text = (
            f"Тема: {case.title}. Категория: {case.category}. "
            f"Риск: {case.risk}. Рекомендация: {case.recommendation}"
        )
        cases_collection.upsert(documents=[case_text], ids=[str(uuid.uuid4())])

        example_text = json.dumps(
            {
                "title": case.title,
                "vulnerability": case.vulnerability,
                "risk": case.risk,
                "recommendation": case.recommendation,
            },
            ensure_ascii=False,
        )
        case_examples_collection.upsert(
            documents=[example_text], ids=[str(uuid.uuid4())]
        )

        add_hint(case.title, case.category)

    for conc in data.conclusions:
        conclusions_collection.upsert(documents=[conc], ids=[str(uuid.uuid4())])
