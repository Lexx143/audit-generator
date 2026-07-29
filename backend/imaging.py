import asyncio
import base64
import hashlib
import io
import uuid
from urllib.parse import quote

from google import genai
from google.genai import types

import config

_genai_client = genai.Client(api_key=config.GOOGLE_API_KEY) if config.GOOGLE_API_KEY else None

STYLE_PRESETS = {
    "3d_icon": (
        "Minimalist abstract 3D icon of {prompt}. Pure white background, "
        "absolutely no text, no letters, clean corporate IT infographic style, "
        "geometric, soft studio lighting."
    ),
    "flat_vector": (
        "Simple flat vector illustration of {prompt}. Pure white background, "
        "absolutely no text, no letters, minimal corporate style, "
        "2-3 accent colors, clean geometric shapes."
    ),
    "isometric": (
        "Isometric 3D illustration of {prompt}. Pure white background, "
        "absolutely no text, no letters, clean corporate IT style, "
        "soft muted colors, minimal detail."
    ),
}


def build_full_prompt(prompt: str, style: str) -> str:
    template = STYLE_PRESETS.get(style, STYLE_PRESETS["3d_icon"])
    return template.format(prompt=prompt)


def _to_jpeg_b64(raw: bytes, quality: int = 85) -> str:
    """PNG-байты -> data:image/jpeg;base64. Иконки кейсов уезжают в JSON и в
    PPTX, поэтому держим их лёгкими."""
    from PIL import Image

    img = Image.open(io.BytesIO(raw)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")


# Мост к хосту с agy: на той стороне ключ привязан forced-command к обёртке,
# которая принимает промпт в stdin и печатает base64 PNG в stdout. Никакой
# другой команды этим ключом выполнить нельзя (restrict в authorized_keys).
_BRIDGE_OPTS = [
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectTimeout=10",
    "-o", "BatchMode=yes",
]


async def _generate_agy_bridge(full_prompt: str) -> str:
    """Nano banana через Antigravity CLI (agy). Генерация ~25-40 сек."""
    if not (config.AGY_SSH_HOST and config.AGY_SSH_KEY):
        raise RuntimeError("AGY_SSH не настроен")
    argv = (
        ["ssh", "-i", config.AGY_SSH_KEY]
        + _BRIDGE_OPTS
        + [f"{config.AGY_SSH_USER}@{config.AGY_SSH_HOST}"]
    )
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(full_prompt.encode("utf-8")), timeout=180
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("agy: таймаут 180с")
    if proc.returncode != 0 or not out:
        raise RuntimeError(f"agy: {(err or b'')[-300:].decode(errors='replace').strip()}")
    # agy отдаёт PNG ~900 КБ; в JSON и PPTX это неподъёмно — жмём в JPEG,
    # как делал прежний путь (на 8 кейсов экономит порядка 7 МБ).
    return _to_jpeg_b64(base64.b64decode(out))


def _generate_gemini_sync(full_prompt: str) -> str:
    """Nano Banana (gemini-2.5-flash-image) через AI Studio.
    Требует включённого биллинга/квоты на Google — иначе 403/429."""
    if _genai_client is None:
        raise RuntimeError("GOOGLE_API_KEY не задан")
    resp = _genai_client.models.generate_content(
        model=config.IMAGE_MODEL,
        contents=full_prompt,
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )
    for part in resp.candidates[0].content.parts:
        inline = getattr(part, "inline_data", None)
        if inline and inline.data:
            mime = inline.mime_type or "image/png"
            b64 = base64.b64encode(inline.data).decode("utf-8")
            return f"data:{mime};base64,{b64}"
    raise RuntimeError("Gemini не вернул картинку")


def _generate_pollinations_sync(full_prompt: str) -> str:
    import requests

    seed = uuid.uuid4().int % 1_000_000
    url = (
        f"https://image.pollinations.ai/prompt/{quote(full_prompt)}"
        f"?width=1024&height=1024&nologo=true&model=flux&seed={seed}"
    )
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    b64 = base64.b64encode(resp.content).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def _placeholder_b64(seed_text: str) -> str:
    """Deterministic local fallback icon so the endpoint never hard-fails."""
    from PIL import Image, ImageDraw

    h = hashlib.md5(seed_text.encode("utf-8")).hexdigest()
    color = f"#{h[0:6]}"
    img = Image.new("RGB", (1024, 1024), "white")
    draw = ImageDraw.Draw(img)
    draw.ellipse((212, 212, 812, 812), outline=color, width=18)
    draw.rectangle((362, 362, 662, 662), outline=color, width=14)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def prepare_auditor_photo(photo_b64: str, size: int = 512) -> str:
    """Квадратный кроп + маска-капелька, как фото аудитора в шаблоне
    (круг с "острым" правым нижним углом)."""
    from PIL import Image, ImageDraw, ImageOps

    raw = base64.b64decode(photo_b64.split(",", 1)[-1])
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img = ImageOps.exif_transpose(img)
    img = ImageOps.fit(img, (size, size), Image.LANCZOS)

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)
    draw.rectangle((size // 2, size // 2, size, size), fill=255)  # угол капельки
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)

    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('utf-8')}"


async def generate_image_b64(prompt: str, style: str = "3d_icon") -> str:
    """agy-мост (nano banana) -> Gemini API -> Pollinations -> локальный плейсхолдер."""
    full_prompt = build_full_prompt(prompt, style)

    try:
        return await _generate_agy_bridge(full_prompt)
    except Exception as e:
        print(f'agy bridge image generation failed: {e}')

    try:
        return await asyncio.to_thread(_generate_gemini_sync, full_prompt)
    except Exception as e:
        print(f"Gemini image generation failed ({config.IMAGE_MODEL}): {e}")

    try:
        return await asyncio.to_thread(_generate_pollinations_sync, full_prompt)
    except Exception as e:
        print(f"Pollinations image generation failed: {e}")

    return _placeholder_b64(prompt)
