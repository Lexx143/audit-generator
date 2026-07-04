import base64
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
# Библиотека картинок кейсов: документ = тема кейса, в метаданных путь к файлу
images_collection = chroma_client.get_or_create_collection(
    name="case_images", embedding_function=openai_ef
)

IMAGES_DIR = os.path.join(config.CHROMA_PATH, "images")
AUDITORS_FILE = os.path.join(config.CHROMA_PATH, "auditors.json")
CATEGORIES_FILE = os.path.join(config.CHROMA_PATH, "categories.json")

DEFAULT_CATEGORIES = [
    "Серверная инфраструктура",
    "Сеть и ИТ-поддержка",
    "Безопасность",
    "1C",
    "Видеонаблюдение и СКУД",
]


def strip_category_number(cat: str) -> str:
    """Убирает римскую нумерацию ('II. Сеть' -> 'Сеть')."""
    return re.sub(r"^\s*[IVXivx]+\.\s*", "", (cat or "").strip())


def get_categories() -> list[str]:
    if os.path.exists(CATEGORIES_FILE):
        with open(CATEGORIES_FILE, "r") as f:
            return json.load(f)
    return list(DEFAULT_CATEGORIES)


def add_category(name: str) -> list[str]:
    name = strip_category_number(name)
    cats = get_categories()
    if name and name.lower() not in [c.lower() for c in cats]:
        cats.append(name)
        os.makedirs(config.CHROMA_PATH, exist_ok=True)
        with open(CATEGORIES_FILE, "w") as f:
            json.dump(cats, f, ensure_ascii=False, indent=2)
    return cats

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
        # категории кейсов теперь без нумерации — сопоставляем по названию
        bare = strip_category_number(category).lower()
        category = next(
            (h for h in HINT_CATEGORIES if strip_category_number(h).lower() == bare),
            "VI. Прочее",
        )

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


def _image_doc(title: str, vulnerability: str) -> str:
    return f"{title}. {vulnerability or ''}".strip()


def save_case_image(title: str, vulnerability: str, image_b64: str):
    """Сохраняет картинку кейса в библиотеку (файл + семантический индекс)."""
    if not image_b64 or not image_b64.startswith("data:image"):
        return
    header, b64_payload = image_b64.split(",", 1)
    raw = base64.b64decode(b64_payload)
    ext = "png" if "png" in header else "jpg"
    img_id = hashlib.md5(raw).hexdigest()

    os.makedirs(IMAGES_DIR, exist_ok=True)
    path = os.path.join(IMAGES_DIR, f"{img_id}.{ext}")
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(raw)

    images_collection.upsert(
        documents=[_image_doc(title, vulnerability)],
        ids=[img_id],
        metadatas=[{"file": path, "mime": f"image/{'png' if ext == 'png' else 'jpeg'}"}],
    )


def find_similar_images(title: str, vulnerability: str, n: int = 6) -> list[dict]:
    """Возвращает картинки из библиотеки для похожих кейсов: [{id, b64}]."""
    if images_collection.count() == 0:
        return []
    res = images_collection.query(
        query_texts=[_image_doc(title, vulnerability)],
        n_results=min(n, images_collection.count()),
    )
    out = []
    for img_id, meta in zip(res["ids"][0], res["metadatas"][0]):
        path = meta.get("file")
        if not path or not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            b64_payload = base64.b64encode(f.read()).decode("utf-8")
        out.append({"id": img_id, "b64": f"data:{meta.get('mime', 'image/jpeg')};base64,{b64_payload}"})
    return out


def get_auditors() -> list[dict]:
    if os.path.exists(AUDITORS_FILE):
        with open(AUDITORS_FILE, "r") as f:
            return json.load(f)
    return []


def save_auditor(name: str, photo_b64: str | None) -> dict:
    auditors = get_auditors()
    auditor = {
        "id": hashlib.md5(name.strip().lower().encode("utf-8")).hexdigest()[:12],
        "name": name.strip(),
        "photo_b64": photo_b64,
    }
    auditors = [a for a in auditors if a["id"] != auditor["id"]]
    auditors.append(auditor)
    auditors.sort(key=lambda a: a["name"].lower())
    os.makedirs(config.CHROMA_PATH, exist_ok=True)
    with open(AUDITORS_FILE, "w") as f:
        json.dump(auditors, f, ensure_ascii=False, indent=2)
    return auditor


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

        # Иллюстрации (сгенерированные или помеченные как переиспользуемые)
        # сохраняем в библиотеку; фотографии объектов (image_reusable=False) — нет
        if case.image_b64 and case.image_reusable:
            try:
                save_case_image(case.title, case.vulnerability, case.image_b64)
            except Exception as e:
                print(f"Failed to save case image: {e}")

    for conc in data.conclusions:
        conclusions_collection.upsert(documents=[conc], ids=[str(uuid.uuid4())])
