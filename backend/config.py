import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

TEXT_MODEL = os.environ.get("TEXT_MODEL", "gpt-5.5")
REASONING_EFFORT = os.environ.get("REASONING_EFFORT", "medium")

IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "gpt-image-2")
IMAGE_QUALITY = os.environ.get("IMAGE_QUALITY", "medium")
IMAGE_SIZE = os.environ.get("IMAGE_SIZE", "1024x1024")

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")

CHROMA_PATH = "db"
HINTS_FILE = "db/hints.json"
