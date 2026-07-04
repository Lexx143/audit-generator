import asyncio
import base64
import hashlib
import io
import uuid
from urllib.parse import quote

from openai import AsyncOpenAI

import config

client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

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


async def _generate_openai(full_prompt: str) -> str:
    response = await client.images.generate(
        model=config.IMAGE_MODEL,
        prompt=full_prompt,
        size=config.IMAGE_SIZE,
        quality=config.IMAGE_QUALITY,
        output_format="jpeg",
        output_compression=85,
        n=1,
    )
    b64 = response.data[0].b64_json
    return f"data:image/jpeg;base64,{b64}"


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
    """gpt-image-2 -> Pollinations -> локальный плейсхолдер."""
    full_prompt = build_full_prompt(prompt, style)

    try:
        return await _generate_openai(full_prompt)
    except Exception as e:
        print(f"OpenAI image generation failed ({config.IMAGE_MODEL}): {e}")

    try:
        return await asyncio.to_thread(_generate_pollinations_sync, full_prompt)
    except Exception as e:
        print(f"Pollinations image generation failed: {e}")

    return _placeholder_b64(prompt)
