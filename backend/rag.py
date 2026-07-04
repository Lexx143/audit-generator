import os
import json
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
    if os.path.exists(config.HINTS_FILE):
        with open(config.HINTS_FILE, "r") as f:
            return json.load(f)
    return []


def save_hints(hints: list):
    if not os.path.exists("db"):
        os.makedirs("db")
    with open(config.HINTS_FILE, "w") as f:
        json.dump(hints, f, ensure_ascii=False, indent=2)


def save_report_to_memory(data):
    """Сохраняет кейсы и выводы сгенерированного отчета в базу знаний RAG."""
    current_hints = get_hints()
    new_hints_added = False

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

        if case.title not in current_hints:
            current_hints.append(case.title)
            new_hints_added = True

    for conc in data.conclusions:
        conclusions_collection.upsert(documents=[conc], ids=[str(uuid.uuid4())])

    if new_hints_added:
        save_hints(current_hints)
