"""Индексирует полные кейсы из data/cases_*.json в коллекцию audit_case_examples.

Запуск: ./venv/bin/python import_examples.py
Идемпотентен: id = md5 содержимого кейса, повторный запуск не плодит дубли.
"""
import glob
import hashlib
import json

import rag


def main():
    files = sorted(glob.glob("data/cases_*.json"))
    if not files:
        print("Нет файлов data/cases_*.json — нечего импортировать.")
        return

    docs, ids = [], []
    skipped = 0
    for path in files:
        try:
            with open(path, "r") as f:
                cases = json.load(f)
        except Exception as e:
            print(f"Пропущен {path}: {e}")
            skipped += 1
            continue

        if not isinstance(cases, list):
            cases = [cases]

        for case in cases:
            if not isinstance(case, dict) or not case.get("title"):
                continue
            doc = json.dumps(
                {
                    "title": case.get("title", ""),
                    "vulnerability": case.get("vulnerability", ""),
                    "risk": case.get("risk", ""),
                    "recommendation": case.get("recommendation") or "",
                },
                ensure_ascii=False,
            )
            doc_id = hashlib.md5(doc.encode("utf-8")).hexdigest()
            if doc_id not in ids:
                docs.append(doc)
                ids.append(doc_id)

    if not docs:
        print("Кейсы не найдены.")
        return

    batch = 50
    for i in range(0, len(docs), batch):
        rag.case_examples_collection.upsert(
            documents=docs[i:i + batch], ids=ids[i:i + batch]
        )
        print(f"Загружено {min(i + batch, len(docs))}/{len(docs)}")

    print(f"Готово: {len(docs)} уникальных кейсов, файлов пропущено: {skipped}.")
    print(f"Всего в коллекции: {rag.case_examples_collection.count()}")


if __name__ == "__main__":
    main()
