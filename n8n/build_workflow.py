"""Генерирует n8n-workflow ``support-bot.workflow.json`` из базы знаний проекта.

Сценарий повторяет Python-бота: Telegram Trigger → поиск по встроенной базе
(Code, упрощённый BM25) → IF → Basic LLM Chain с Anthropic Chat Model и
Structured Output Parser → IF «ответ найден?» → ответ клиенту либо сообщение
о передаче + карточка в чат оператора.

Структура узлов и соединений собрана по мотивам шаблонов с n8n.io:
«Telegram AI bot assistant: ready-made template for voice & text messages»
(автор yulia, workflow 2534) и «Manage Telegram task reminders with Claude and
n8n data tables» (автор sambhramp, workflow 15933), а также демо-workflow из
n8n-io/self-hosted-ai-starter-kit (Apache-2.0). Код узлов написан заново.

Запуск: ``python n8n/build_workflow.py`` (из корня проекта). База знаний
встраивается в узел Code, поэтому после правки ``knowledge/*.md`` файл нужно
перегенерировать.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from support_bot.assistant import ESCALATION_TEXT  # noqa: E402
from support_bot.config import DEFAULT_MODEL  # noqa: E402
from support_bot.knowledge import load_knowledge  # noqa: E402
from support_bot.llm import SYSTEM_PROMPT, AnswerSchema  # noqa: E402
from support_bot.search import _REFLEXIVE, _SUFFIXES, STOPWORDS  # noqa: E402

OUTPUT = ROOT / "n8n" / "support-bot.workflow.json"

SEARCH_JS = r"""// База знаний встроена при генерации файла (см. n8n/build_workflow.py).
// Поиск — упрощённый BM25 с отсечением русских окончаний, как в Python-боте.
const KB = __KB__;
const STOP = new Set(__STOP__);
const SUFFIXES = __SUFFIXES__;
const REFLEXIVE = new Set(__REFLEXIVE__);
const MIN_OVERLAP = 0.3; // доля слов вопроса, которые должны найтись в статье
const TOP_K = 3;

function stem(w) {
  for (let pass = 0; pass < 2; pass++) {
    let changed = false;
    for (const s of SUFFIXES) {
      if (!w.endsWith(s)) continue;
      const rest = w.length - s.length;
      const min = REFLEXIVE.has(s) ? 5 : (s.length === 1 ? 3 : 4);
      if (rest >= min) { w = w.slice(0, rest); changed = true; break; }
    }
    if (!changed) break;
  }
  return w;
}

function tokenize(text) {
  const words = text.toLowerCase().replace(/ё/g, "е").match(/[а-яa-z0-9]+/g) || [];
  return words.filter((w) => !STOP.has(w) && w.length > 1).map(stem);
}

const docs = KB.map((e) => [
  ...tokenize(e.q), ...tokenize(e.q), ...tokenize(e.t), ...tokenize(e.t), ...tokenize(e.a),
]);
const N = docs.length;
const avgdl = docs.reduce((s, d) => s + d.length, 0) / N;
const df = new Map();
for (const d of docs) for (const t of new Set(d)) df.set(t, (df.get(t) || 0) + 1);
const K1 = 1.5, B = 0.75;

function bm25(doc, query) {
  const tf = new Map();
  for (const t of doc) tf.set(t, (tf.get(t) || 0) + 1);
  let score = 0;
  for (const t of query) {
    const f = tf.get(t) || 0;
    if (!f) continue;
    const n = df.get(t) || 0;
    const idf = Math.log((N - n + 0.5) / (n + 0.5) + 1);
    score += (idf * f * (K1 + 1)) / (f + K1 * (1 - B + (B * doc.length) / avgdl));
  }
  return score;
}

const msg = $input.item.json.message || {};
const question = (msg.text || "").trim();
const query = tokenize(question);
const uniq = new Set(query);
const hits = docs
  .map((doc, i) => {
    const set = new Set(doc);
    const matched = [...uniq].filter((t) => set.has(t)).length;
    return { i, score: bm25(doc, query), overlap: uniq.size ? matched / uniq.size : 0 };
  })
  .filter((h) => h.score > 0 && h.overlap >= MIN_OVERLAP)
  .sort((a, b) => b.score - a.score)
  .slice(0, TOP_K);

const context = hits
  .map((h, n) => `[${n + 1}] Вопрос: ${KB[h.i].q}\nОтвет: ${KB[h.i].a}`)
  .join("\n---\n");

return {
  json: {
    chat_id: msg.chat ? msg.chat.id : null,
    user_name: msg.from ? [msg.from.first_name, msg.from.last_name].filter(Boolean).join(" ") : "",
    username: msg.from && msg.from.username ? "@" + msg.from.username : "",
    question,
    found: hits.length > 0,
    best_question: hits.length ? KB[hits[0].i].q : "",
    best_score: hits.length ? Math.round(hits[0].score * 100) / 100 : 0,
    context,
  },
};
"""

USER_PROMPT = "=Выдержки из базы знаний:\n{{ $json.context }}\n\nВопрос клиента: {{ $json.question }}"


def _js(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _bool_condition(expression: str, cid: str) -> dict:
    return {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [
                {
                    "id": cid,
                    "leftValue": expression,
                    "rightValue": "",
                    "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                }
            ],
            "combinator": "and",
        },
        "looseTypeValidation": True,
        "options": {},
    }


def _telegram(name: str, chat_id: str, text: str, position: list[int], node_id: str) -> dict:
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.telegram",
        "typeVersion": 1.2,
        "position": position,
        "parameters": {"chatId": chat_id, "text": text, "additionalFields": {"appendAttribution": False}},
    }


def _sticky(content: str, position: list[int], node_id: str, width: int = 420, height: int = 180) -> dict:
    return {
        "id": node_id,
        "name": f"Заметка {node_id[-1]}",
        "type": "n8n-nodes-base.stickyNote",
        "typeVersion": 1,
        "position": position,
        "parameters": {"content": content, "width": width, "height": height, "color": 4},
    }


def build() -> dict:
    entries = load_knowledge(ROOT / "knowledge")
    kb = [{"q": e.question, "a": e.answer, "t": " ".join(e.tags)} for e in entries]
    js_code = (
        SEARCH_JS.replace("__KB__", _js(kb))
        .replace("__STOP__", _js(sorted(STOPWORDS)))
        .replace("__SUFFIXES__", _js(list(_SUFFIXES)))
        .replace("__REFLEXIVE__", _js(list(_REFLEXIVE)))
    )
    schema = AnswerSchema.model_json_schema()
    schema.pop("title", None)
    system_prompt = SYSTEM_PROMPT.format(company="автосервис «Вектор»")
    trigger_chat = "={{ $('Telegram Trigger').item.json.message.chat.id }}"

    nodes = [
        {
            "id": "n01",
            "name": "Telegram Trigger",
            "type": "n8n-nodes-base.telegramTrigger",
            "typeVersion": 1.2,
            "position": [0, 300],
            "parameters": {"updates": ["message"], "additionalFields": {}},
        },
        {
            "id": "n02",
            "name": "Настройки",
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [220, 300],
            "parameters": {
                "assignments": {
                    "assignments": [
                        {
                            "id": "s1",
                            "name": "operator_chat_id",
                            "value": "ЗАМЕНИТЕ_НА_ID_ЧАТА_ОПЕРАТОРА",
                            "type": "string",
                        }
                    ]
                },
                "includeOtherFields": True,
                "options": {},
            },
        },
        {
            "id": "n03",
            "name": "Поиск по базе знаний",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [440, 300],
            "parameters": {"mode": "runOnceForEachItem", "jsCode": js_code},
        },
        {
            "id": "n04",
            "name": "Есть статьи?",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2.2,
            "position": [660, 300],
            "parameters": _bool_condition("={{ $json.found }}", "c1"),
        },
        {
            "id": "n05",
            "name": "Ответ по базе (Claude)",
            "type": "@n8n/n8n-nodes-langchain.chainLlm",
            "typeVersion": 1.7,
            "position": [900, 180],
            "parameters": {
                "promptType": "define",
                "text": USER_PROMPT,
                "hasOutputParser": True,
                "messages": {"messageValues": [{"type": "SystemMessagePromptTemplate", "message": system_prompt}]},
            },
        },
        {
            "id": "n06",
            "name": "Anthropic Chat Model",
            "type": "@n8n/n8n-nodes-langchain.lmChatAnthropic",
            "typeVersion": 1.3,
            "position": [860, 400],
            "parameters": {
                "model": {"__rl": True, "mode": "id", "value": DEFAULT_MODEL},
                "options": {"maxTokensToSample": 2048},
            },
        },
        {
            "id": "n07",
            "name": "Формат ответа (JSON)",
            "type": "@n8n/n8n-nodes-langchain.outputParserStructured",
            "typeVersion": 1.2,
            "position": [1060, 400],
            "parameters": {"schemaType": "manual", "inputSchema": json.dumps(schema, ensure_ascii=False, indent=2)},
        },
        {
            "id": "n08",
            "name": "Ответ найден?",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2.2,
            "position": [1280, 180],
            "parameters": _bool_condition("={{ $json.output.covered }}", "c2"),
        },
        _telegram("Ответ клиенту", trigger_chat, "={{ $json.output.answer }}", [1540, 80], "n09"),
        _telegram("Сообщить о передаче", trigger_chat, ESCALATION_TEXT, [1540, 320], "n10"),
        _telegram(
            "Переслать оператору",
            "={{ $('Настройки').item.json.operator_chat_id }}",
            "=🆘 Обращение из Telegram\n"
            "От: {{ $('Поиск по базе знаний').item.json.user_name }} "
            "{{ $('Поиск по базе знаний').item.json.username }} "
            "(chat {{ $('Telegram Trigger').item.json.message.chat.id }})\n"
            "Вопрос: {{ $('Telegram Trigger').item.json.message.text }}",
            [1540, 520],
            "n11",
        ),
        _sticky(
            "## Приём и поиск\nTelegram Trigger ловит сообщения. Узел «Настройки» хранит id чата оператора. "
            "Code ищет 3 лучшие статьи базы знаний (упрощённый BM25) и отдаёт их в контекст.",
            [0, 20],
            "nA",
            640,
            160,
        ),
        _sticky(
            "## Ответ модели\nBasic LLM Chain + Anthropic Chat Model (claude-haiku-5-5). Structured Output Parser "
            "заставляет модель вернуть JSON {covered, answer}: covered=false → вопрос не покрыт базой.",
            [860, 560],
            "nB",
            620,
            160,
        ),
        _sticky(
            "## Исход\nЕсли статей нет или covered=false — клиенту уходит сообщение о передаче, "
            "а в чат оператора — карточка с вопросом. Иначе клиент получает ответ.",
            [1540, 700],
            "nC",
            420,
            160,
        ),
    ]

    def link(*targets: str, kind: str = "main") -> list[dict]:
        return [{"node": t, "type": kind, "index": 0} for t in targets]

    connections = {
        "Telegram Trigger": {"main": [link("Настройки")]},
        "Настройки": {"main": [link("Поиск по базе знаний")]},
        "Поиск по базе знаний": {"main": [link("Есть статьи?")]},
        "Есть статьи?": {"main": [link("Ответ по базе (Claude)"), link("Сообщить о передаче", "Переслать оператору")]},
        "Anthropic Chat Model": {"ai_languageModel": [link("Ответ по базе (Claude)", kind="ai_languageModel")]},
        "Формат ответа (JSON)": {"ai_outputParser": [link("Ответ по базе (Claude)", kind="ai_outputParser")]},
        "Ответ по базе (Claude)": {"main": [link("Ответ найден?")]},
        "Ответ найден?": {"main": [link("Ответ клиенту"), link("Сообщить о передаче", "Переслать оператору")]},
    }

    return {
        "name": "support-bot — ассистент автосервиса «Вектор»",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
        "pinData": {},
        "active": False,
    }


def main() -> None:
    workflow = build()
    OUTPUT.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Записан {OUTPUT.relative_to(ROOT)}: узлов {len(workflow['nodes'])}, статей в базе {len(load_knowledge(ROOT / 'knowledge'))}")


if __name__ == "__main__":
    main()
