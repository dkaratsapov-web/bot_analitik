"""
Ядро агента: цикл tool-use.

Модель получает вопрос на естественном языке, сама решает какие
инструменты вызвать (из tools.TOOL_SCHEMAS), получает результаты и
формулирует ответ. Это надёжнее, чем заливать все данные в промпт.

Здесь же — системный промпт, который задаёт агенту обе роли:
аналитик кампаний + специалист по Директу.
"""

from __future__ import annotations

import json

import anthropic

import config
import tools

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Ты — ИИ-ассистент маркетолога, ведущего ~10 рекламных проектов.
У тебя две роли:

1. АНАЛИТИК КАМПАНИЙ. Отвечаешь на вопросы по статистике (показы, клики,
   расход, конверсии, CTR, CPC, CPA, CR). Сравниваешь периоды, находишь
   аномалии, объясняешь причины изменений и даёшь конкретные рекомендации.

2. СПЕЦИАЛИСТ ПО ЯНДЕКС.ДИРЕКТУ. Помогаешь с семантикой (расширение ключей,
   минус-слова) и написанием объявлений. Объявления пиши сам, креативно, но
   ОБЯЗАТЕЛЬНО проверяй их через инструмент validate_ad — Директ жёстко
   ограничивает длину: Заголовок 1 ≤ 56, Заголовок 2 ≤ 30, Текст ≤ 81 символ.

Принципы:
- Всегда опирайся на цифры из инструментов, не выдумывай метрики.
- Отвечай кратко и по делу, с выводами, а не просто выгрузкой чисел.
- Если данных не хватает — вызови нужный инструмент, а не угадывай.
- Суммы — в рублях. Пиши на русском.
"""

MAX_TOOL_ITERATIONS = 6


def run_agent(user_text: str, history: list[dict]) -> tuple[str, list[dict]]:
    """Обработать одно сообщение пользователя.

    history — список сообщений в формате Anthropic (хранится по chat_id).
    Возвращает (текст ответа, обновлённая history).
    """
    history.append({"role": "user", "content": user_text})

    for _ in range(MAX_TOOL_ITERATIONS):
        resp = client.messages.create(
            model=config.MODEL,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            tools=tools.TOOL_SCHEMAS,
            messages=history,
        )
        # сохраняем ход ассистента (включая запросы на вызов инструментов)
        history.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text")
            return text.strip() or "(пустой ответ)", history

        # выполняем все запрошенные инструменты и возвращаем результаты модели
        tool_results = []
        for block in resp.content:
            if block.type == "tool_use":
                result = tools.run_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })
        history.append({"role": "user", "content": tool_results})

    return "Слишком много шагов — упростите, пожалуйста, запрос.", history


def trim_history(history: list[dict], max_messages: int = 20) -> list[dict]:
    """Не давать истории расти бесконечно (экономия токенов).
    Простой вариант — хранить последние N сообщений."""
    return history[-max_messages:]
