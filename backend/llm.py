import json

from anthropic import AsyncAnthropic

import config
import rag
from schemas import AuditData, Case, ParseRequest, ReviseRequest, ReviseCaseRequest

client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

STYLE_GUIDE = """
ТРЕБОВАНИЯ К КАЧЕСТВУ ТЕКСТА:
- Деловой русский язык, уверенный экспертный тон, без воды и общих фраз.
- Уязвимость: конкретика — что именно обнаружено, где, в каком состоянии (версии ПО, модели оборудования, конфигурации — если есть в данных).
- Риски: причинно-следственная цепочка "что случится -> к чему приведет для бизнеса". Указывай последствия: простой, потеря данных, финансовые и репутационные потери, штрафы.
- Рекомендации (если требуются): конкретные действия, а не "рекомендуется улучшить". Называй технологии, практики и стандарты (например: RAID1, правило бэкапов 3-2-1, политики GPO, сегментация VLAN, план DRP).
- Запрещено: канцелярит, повторы одной мысли разными словами, очевидные банальности ("безопасность очень важна").
- Пиши так, как в приложенных примерах из реальных аудитов — тот же тон, глубина и структура.
- ЖЕСТКИЕ ЛИМИТЫ ДЛИНЫ (текст идет в таблицу на слайде PowerPoint): vulnerability — до 250 знаков, risk — до 350 знаков, recommendation — до 350 знаков. Плотно и емко, каждое слово работает.
"""


def _build_rag_context(vulnerabilities: str, conclusions: str) -> str:
    parts = []

    examples = rag.retrieve_case_examples(vulnerabilities, n=4)
    if examples:
        parts.append("ПРИМЕРЫ ПОЛНЫХ КЕЙСОВ ИЗ ПРОШЛЫХ АУДИТОВ (образец тона и глубины):")
        for ex in examples:
            parts.append(f"---\n{ex}")

    phrases = rag.retrieve_case_phrases(vulnerabilities, n=5)
    if phrases:
        parts.append("\nУДАЧНЫЕ ФОРМУЛИРОВКИ ИЗ ПРОШЛЫХ АУДИТОВ:")
        for p in phrases:
            parts.append(f"- {p}")

    conc_examples = rag.retrieve_conclusion_examples(conclusions or vulnerabilities, n=3)
    if conc_examples:
        parts.append("\nПРИМЕРЫ ВЫВОДОВ ИЗ ПРОШЛЫХ АУДИТОВ:")
        for c in conc_examples:
            parts.append(f"- {c}")

    return "\n".join(parts)


async def build_image_prompt(title: str, vulnerability: str, risk: str) -> str:
    """Строит подробный английский промпт визуальной сцены под конкретный кейс —
    метафора именно этого риска, конкретные объекты. Стиль/фон добавит imaging."""
    system = ("You are an art director for corporate IT-audit report illustrations. "
              "You write vivid, concrete English image-generation prompts describing a scene.")
    user = f"""Опиши визуальную сцену-иллюстрацию для кейса ИТ-аудита. Верни ТОЛЬКО английский промпт одним абзацем, без пояснений и без указания стиля рисовки.

Кейс: {title}
Уязвимость: {vulnerability}
Риск: {risk}

Требования:
- Это ПЛОСКАЯ СХЕМАТИЧНАЯ инфографика (flat vector), НЕ фотореализм. Описывай ТОЛЬКО объекты и их взаимное расположение/композицию. НЕ описывай освещение, тени, атмосферу, текстуры, пыль, фон, помещение.
- Конкретная сцена, метафорически показывающая СУТЬ РИСКА кейса. Простые узнаваемые иконки-объекты: серверы, камеры, ключи, кабели, роутеры, облако, документы и т.п.
- Визуально передай проблему: единственная точка отказа, отсутствие резерва (пустой пунктирный силуэт/слот), угрозы вокруг (пламя, замок-шифровальщик, рука-кража), несовместимость (детали пазла), хаос кабелей — что подходит кейсу.
- Никакого текста, букв, цифр, логотипов.
- Ровно 2–3 коротких предложения. Только суть, без литературных деталей.
"""
    msg = await client.messages.create(
        model=config.TEXT_MODEL, max_tokens=250, system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()


async def _parse_structured(prompt: str, system: str, response_format):
    # Anthropic structured output: messages.parse сам ставит output_config.format
    # из output_format и валидирует ответ в Pydantic-модель (parsed_output).
    # Adaptive thinking + effort — вместо reasoning_effort у OpenAI.
    message = await client.messages.parse(
        model=config.TEXT_MODEL,
        max_tokens=config.MAX_TOKENS,
        system=system,
        thinking={"type": "adaptive"},
        output_config={"effort": config.REASONING_EFFORT},
        messages=[{"role": "user", "content": prompt}],
        output_format=response_format,
    )
    return message.parsed_output


async def generate_structure(req: ParseRequest) -> AuditData:
    rag_context = _build_rag_context(req.vulnerabilities, req.conclusions)

    prompt = f"""
Проанализируй предоставленные данные и сформируй структуру для ИТ-аудита.
Тип аудита: {req.audit_type}. Если 'full', обязательно добавь рекомендации (поле recommendation) для каждого кейса. Если 'express', оставь поле рекомендаций пустым.

ОБЩИЕ ДАННЫЕ О КЛИЕНТЕ:
{req.general_data}

ВЫЯВЛЕННЫЕ УЯЗВИМОСТИ:
{req.vulnerabilities}

ВЫВОДЫ/ЗАКЛЮЧЕНИЕ:
{req.conclusions}

{rag_context}

{STYLE_GUIDE}

ИНСТРУКЦИИ ДЛЯ СТРУКТУРЫ (AuditData):
1. client_name: Короткое название клиента.
2. review: Обобщающий текст-обзор на 2-3 предложения — по существу, с привязкой к специфике клиента.
3. cases: Создай отдельный кейс для КАЖДОЙ уязвимости/проблемы, указанной пользователем — сколько указано, столько кейсов. Не объединяй несколько проблем в один кейс и не пропускай ничего. Для каждого кейса заполни title, vulnerability, risk, priority ("ПЕРВЫЙ ПРИОРИТЕТ", "ВТОРОЙ ПРИОРИТЕТ" или "ТРЕТИЙ ПРИОРИТЕТ"), category — название раздела БЕЗ нумерации (обычно "Серверная инфраструктура" или "Сеть и ИТ-поддержка"; допустимы также "Безопасность", "1C", "Видеонаблюдение и СКУД"). Упорядочи кейсы по убыванию критичности, группируя кейсы одной категории подряд. Также придумай image_prompt — промпт на английском (до 15 слов) для генерации ИТ-векторной картинки без текста, отражающий суть кейса.
4. conclusions: Массив из 3-5 строк для итогового слайда с предложениями — конкретные следующие шаги, а не лозунги.
"""

    return await _parse_structured(
        prompt,
        system="Ты ведущий эксперт по ИТ-аудитам с 15-летним опытом. Твои отчеты читают собственники бизнеса.",
        response_format=AuditData,
    )


def _strip_images(data: AuditData) -> str:
    """JSON структуры БЕЗ base64-картинок — они раздувают промпт на сотни тысяч
    токенов и модель их всё равно не может воспроизвести. Возвращаем в промпт
    только image_prompt (по нему потом сопоставим картинки обратно)."""
    d = data.model_dump()
    for c in d.get("cases", []):
        c.pop("image_b64", None)
        c.pop("image_reusable", None)
    return json.dumps(d, ensure_ascii=False, indent=2)


def _reattach_images(revised: AuditData, original: AuditData) -> AuditData:
    """Возвращает картинки исходных кейсов новым по совпадению image_prompt/title."""
    by_prompt = {c.image_prompt: c for c in original.cases if c.image_b64}
    by_title = {c.title: c for c in original.cases if c.image_b64}
    for c in revised.cases:
        src = by_prompt.get(c.image_prompt) or by_title.get(c.title)
        if src:
            c.image_b64 = src.image_b64
            c.image_reusable = src.image_reusable
    return revised


async def revise_structure(req: ReviseRequest) -> AuditData:
    rag_context = _build_rag_context(req.revision_prompt, "")

    prompt = f"""
Текущая структура аудита:
{_strip_images(req.current_data)}

Комментарии и правки от пользователя:
{req.revision_prompt}

Тип аудита: {req.audit_type}. Если 'full', обязательно сохраняй/добавляй рекомендации. Если 'express', оставляй поле recommendation пустым.

{rag_context}

{STYLE_GUIDE}

Внимательно изучи комментарии пользователя и примени эти изменения к текущей структуре.
Верни обновленный JSON (AuditData). Поле image_b64 не заполняй — оставь пустым (картинки подставятся автоматически). Поле image_prompt сохраняй без изменений, если пользователь не просил поменять тему кейса.
ВАЖНО: Кейсов может быть любое количество (минимум 1). Если пользователь просит удалить или добавить кейс — сделай это. Без такой просьбы состав кейсов не меняй.
"""

    revised = await _parse_structured(
        prompt,
        system="Ты ведущий эксперт по ИТ-аудитам. Твоя цель — обновить JSON по просьбе пользователя.",
        response_format=AuditData,
    )
    return _reattach_images(revised, req.current_data)


async def revise_single_case(req: ReviseCaseRequest) -> Case:
    rag_context = _build_rag_context(req.case.vulnerability, "")

    case_no_img = req.case.model_dump()
    case_no_img.pop("image_b64", None)

    prompt = f"""
Текущий кейс из ИТ-аудита:
{json.dumps(case_no_img, ensure_ascii=False, indent=2)}

Контекст о клиенте:
{req.general_data}

Комментарий пользователя (что улучшить/изменить):
{req.comment or "Перепиши кейс качественнее: конкретнее, глубже, убедительнее."}

Тип аудита: {req.audit_type}. Если 'full', обязательно заполни recommendation. Если 'express', оставь recommendation пустым.

{rag_context}

{STYLE_GUIDE}

Перепиши ТОЛЬКО этот кейс с учетом комментария. Сохрани поля priority, category, image_prompt и image_b64 без изменений, если комментарий явно не требует их поменять (image_b64 никогда не меняй).
"""

    result = await _parse_structured(
        prompt,
        system="Ты ведущий эксперт по ИТ-аудитам. Улучши один кейс отчета по замечаниям пользователя.",
        response_format=Case,
    )
    # image_b64 через LLM не гоняем — возвращаем исходную картинку
    result.image_b64 = req.case.image_b64
    result.image_reusable = req.case.image_reusable
    return result
