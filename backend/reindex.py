"""Переиндексация базы знаний RAG под новую (локальную) модель эмбеддингов.

Старые коллекции ChromaDB записаны эмбеддингами OpenAI (1536-мерными). После
перехода на локальную модель размерность иная, и Chroma отказывается открывать
коллекцию с другой embedding-функцией. Скрипт читает сохранённые ДОКУМЕНТЫ
(текст в базе есть, .get() не эмбедит), сносит коллекции и пересоздаёт их,
переэмбедив документы локальной моделью. ids и метаданные сохраняются.

Запуск (из папки backend, venv с openai ещё установлен — нужен только чтобы
Chroma смогла сконструировать старую EF для чтения; сам OpenAI не вызывается):
    ./venv/bin/python reindex.py
"""
import os
# Старую openai-EF Chroma конструирует при открытии коллекции; ключ нужен лишь
# для конструктора, эмбеддинг не вызывается (мы только читаем документы).
os.environ.setdefault("OPENAI_API_KEY", "sk-reindex-dummy")

import chromadb
from chromadb.utils import embedding_functions

import config

COLLECTIONS = [
    "audit_cases",
    "audit_conclusions",
    "audit_case_examples",
    "audit_hints",
    "case_images",
]

client = chromadb.PersistentClient(path=config.CHROMA_PATH)
local_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=config.EMBEDDING_MODEL,
)


def reindex(name: str):
    try:
        old = client.get_collection(name)  # persisted (openai) EF, .get() не эмбедит
    except Exception as e:
        print(f"  {name}: коллекции нет ({str(e)[:60]}), создаю пустую")
        client.get_or_create_collection(name, embedding_function=local_ef)
        return

    data = old.get(include=["documents", "metadatas"])
    ids, docs, metas = data["ids"], data["documents"], data["metadatas"]
    metas = metas or [None] * len(ids)

    # выкинуть записи без текста (эмбедить нечего)
    keep = [(i, d, m) for i, d, m in zip(ids, docs, metas) if d]
    total = len(ids)

    client.delete_collection(name)
    new = client.create_collection(name, embedding_function=local_ef)

    # Chroma требует, чтобы в одном add метаданные были либо у всех (непустой
    # dict), либо ни у кого. Разделяем записи на две группы.
    with_meta = [(i, d, m) for i, d, m in keep if m]
    without_meta = [(i, d, m) for i, d, m in keep if not m]
    B = 128
    for group, use_meta in ((without_meta, False), (with_meta, True)):
        for k in range(0, len(group), B):
            chunk = group[k:k + B]
            new.add(
                ids=[c[0] for c in chunk],
                documents=[c[1] for c in chunk],
                metadatas=[c[2] for c in chunk] if use_meta else None,
            )
    print(f"  {name}: переиндексировано {len(keep)}/{total}")


if __name__ == "__main__":
    print(f"Модель эмбеддингов: {config.EMBEDDING_MODEL}")
    print(f"База: {os.path.abspath(config.CHROMA_PATH)}")
    for c in COLLECTIONS:
        reindex(c)
    print("Готово.")
