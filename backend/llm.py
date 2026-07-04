from openai import AsyncOpenAI

import config
import rag
from schemas import AuditData, Case, ParseRequest, ReviseRequest, ReviseCaseRequest

client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

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


async def _parse_structured(prompt: str, system: str, response_format):
    response = await client.beta.chat.completions.parse(
        model=config.TEXT_MODEL,
        reasoning_effort=config.REASONING_EFFORT,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        response_format=response_format,
    )
    return response.choices[0].message.parsed


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
3. cases: Выдели ровно 5 основных уязвимостей (самых критичных для бизнеса клиента). Для каждой заполни title, vulnerability, risk, priority ("ПЕРВЫЙ ПРИОРИТЕТ", "ВТОРОЙ ПРИОРИТЕТ" или "ТРЕТИЙ ПРИОРИТЕТ"), category — название раздела БЕЗ нумерации (обычно "Серверная инфраструктура" или "Сеть и ИТ-поддержка"; допустимы также "Безопасность", "1C", "Видеонаблюдение и СКУД"). ВАЖНО про порядок: в отчете кейсы 1-3 попадают в первый раздел, кейсы 4-5 — во второй. Упорядочи кейсы так, чтобы кейсы одной категории шли подряд (первые три — одна категория, последние два — другая). Также придумай image_prompt — промпт на английском (до 15 слов) для генерации ИТ-векторной картинки без текста, отражающий суть кейса.
4. conclusions: Массив из 3-5 строк для итогового слайда с предложениями — конкретные следующие шаги, а не лозунги.
"""

    return await _parse_structured(
        prompt,
        system="Ты ведущий эксперт по ИТ-аудитам с 15-летним опытом. Твои отчеты читают собственники бизнеса.",
        response_format=AuditData,
    )


async def revise_structure(req: ReviseRequest) -> AuditData:
    rag_context = _build_rag_context(req.revision_prompt, "")

    prompt = f"""
Текущая структура аудита:
{req.current_data.model_dump_json(indent=2)}

Комментарии и правки от пользователя:
{req.revision_prompt}

Тип аудита: {req.audit_type}. Если 'full', обязательно сохраняй/добавляй рекомендации. Если 'express', оставляй поле recommendation пустым.

{rag_context}

{STYLE_GUIDE}

Внимательно изучи комментарии пользователя и примени эти изменения к текущей структуре.
Верни обновленный JSON (AuditData).
ВАЖНО: Кейсов может быть от 1 до 5 (шаблон вмещает максимум 5). Если пользователь просит удалить или добавить кейс — сделай это. Без такой просьбы состав кейсов не меняй. Сохрани поля image_b64 и image_prompt без изменений, если пользователь явно не просил поменять картинку или тему кейса.
"""

    return await _parse_structured(
        prompt,
        system="Ты ведущий эксперт по ИТ-аудитам. Твоя цель — обновить JSON по просьбе пользователя.",
        response_format=AuditData,
    )


async def revise_single_case(req: ReviseCaseRequest) -> Case:
    rag_context = _build_rag_context(req.case.vulnerability, "")

    prompt = f"""
Текущий кейс из ИТ-аудита:
{req.case.model_dump_json(indent=2)}

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
