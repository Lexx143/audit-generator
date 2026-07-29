import os
from dotenv import load_dotenv

load_dotenv()

# --- Текст: Claude (оплачивает компания) ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
TEXT_MODEL = os.environ.get("TEXT_MODEL", "claude-opus-5")
# Глубина рассуждений: low | medium | high | xhigh | max
REASONING_EFFORT = os.environ.get("REASONING_EFFORT", "medium")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "16000"))

# --- Эмбеддинги RAG: локальная мультиязычная модель, ключ не нужен ---
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")

# --- Картинки, основной путь: nano banana через Antigravity CLI (agy) на
#     отдельном хосте. Бэкенд зовёт его по SSH ключом с forced-command:
#     этим ключом можно только попросить картинку, шелл получить нельзя.
#     Путь включается, если заданы все три переменные. ---
AGY_SSH_HOST = os.environ.get("AGY_SSH_HOST", "")
AGY_SSH_USER = os.environ.get("AGY_SSH_USER", "imagegen")
AGY_SSH_KEY = os.environ.get("AGY_SSH_KEY", "")

# --- Картинки, запасной путь: Gemini API (нужен биллинг Google), затем Pollinations ---
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "gemini-2.5-flash-image")
IMAGE_SIZE = os.environ.get("IMAGE_SIZE", "1024x1024")

CHROMA_PATH = "db"
HINTS_FILE = "db/hints.json"
