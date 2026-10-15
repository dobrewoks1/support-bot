# support-bot

[![CI](https://github.com/dobrewoks1/support-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/dobrewoks1/support-bot/actions/workflows/ci.yml)

Telegram-ассистент для малого бизнеса. Отвечает клиентам только по утверждённой базе знаний, а всё,
чего в базе нет, передаёт живому оператору и доставляет его ответ обратно клиенту. Каждое обращение
попадает в журнал, по журналу считаются метрики: сколько закрыл бот, что спрашивают чаще всего.
Тот же сценарий собран и как workflow для n8n.

Показан на примере автосервиса «Вектор» (Омск). Компания, цены, адреса и телефоны в репозитории вымышленные.

## Как работает

```
клиент → Telegram → поиск по базе (BM25) → Claude: ответ строго по найденному + признак covered
                                   ↓ подходящих статей нет или covered = false
                            чат оператора ← карточка обращения #N
                            клиент ← ответ оператора (reply на карточку или /reply N текст)
                 журнал SQLite → /stats в боте и страница метрик (FastAPI: JSON и HTML)
```

Так это выглядит в консольном режиме. Ответы — Claude Haiku 5.5 по базе из 39 статей, без правок:

```
вы > Сколько стоит замена масла?
бот > Замена моторного масла и масляного фильтра стоит 900 рублей за работу. Масло и фильтр
      оплачиваются отдельно: их можно привезти свои или купить у нас. Для большинства легковых
      автомобилей полная стоимость с материалами составляет 3 500–6 500 рублей.
      [статья: «Сколько стоит замена масла?», score=10.1]

вы > До скольки вы работаете в выходные?
бот > В выходные дни мы работаем с 9:00 до 20:00, как и в обычные дни. Приём автомобилей
      заканчивается в 19:00. Рекомендуем бронировать время за 2–3 дня.
      [статья: «Какой у вас режим работы?», score=5.6]

вы > Какая гарантия на ремонт?
бот > На все выполненные работы действует гарантия 6 месяцев или 10 000 км пробега, в зависимости
      от того, что наступит раньше. Гарантия подтверждается заказ-нарядом, поэтому сохраняйте его.
      [статья: «Какая гарантия на работы?», score=4.9]

вы > Поможете оформить ОСАГО?
бот > Я не нашёл точного ответа в базе знаний, поэтому передаю ваш вопрос оператору.
      Ответим в этом чате в ближайшее время.
      → оператору: обращение #13
```

## Что здесь важно

- **База знаний — markdown-файлы** «вопрос → ответ → теги» в `knowledge/`. Правится без кода, из неё же
  собирается n8n-workflow.
- **Поиск — BM25** поверх простого стеммера русского языка, без внешних сервисов. База маленькая, вопросы
  короткие, поэтому лексического поиска с тегами хватает, и он работает за миллисекунды. Статьи, в которых
  нашлось меньше 30 % слов вопроса, модели не отдаются: явный мусор отсекается до LLM.
- **Модель отвечает по схеме** `{covered, answer}` (structured outputs, `client.messages.parse`). Решение
  «передать оператору» принимается по полю `covered`, а не по догадке из текста. Системный промпт запрещает
  добавлять факты, которых нет в выдержках.
- **Если API недоступен**, обращение уходит оператору с тем же текстом для клиента; на это есть тест.
- **Без ключа API** работает детерминированная заглушка: на ней идут тесты и CI, с ней сценарий можно
  показать офлайн.
- **Оператор отвечает** reply-ем на карточку или командой `/reply <номер> <текст>`; бот доставляет ответ
  клиенту и меняет статус обращения в журнале.

## Попробовать

```bash
git clone https://github.com/dobrewoks1/support-bot.git
cd support-bot
python -m venv .venv && .venv\Scripts\activate      # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                                # заполните нужные переменные
```

Без Telegram и без ключа (заглушка вместо модели):

```bash
python -m support_bot --console --provider fake
python -m support_bot --ask "Сколько стоит замена масла?" --provider fake
```

С Claude: задайте `ANTHROPIC_API_KEY` в `.env` или в окружении, провайдер `auto` выберет Claude сам.
Модель меняется переменной `ANTHROPIC_MODEL` (по умолчанию `claude-haiku-5-5`).

Telegram: создайте бота у @BotFather, впишите `BOT_TOKEN` и `OPERATOR_CHAT_ID` (личный чат или группа
оператора; узнать id — команда `/id` в боте), затем `python -m support_bot`. Для проверки в одиночку
достаточно одного чата: укажите свой id как операторский, задайте боту вопрос вне базы, получите карточку
обращения и ответьте на неё reply-ем.

Страница метрик (отдельный процесс, читает тот же SQLite): `python -m support_bot --metrics` →
http://127.0.0.1:8000 и `/metrics`.

Тесты (без сети и без ключей): `pytest`. Проверяется, что пять контрольных вопросов отвечаются из базы,
шестой передаётся оператору, журнал пишется, статистика считается, страница метрик отдаёт JSON и HTML,
консольный режим работает, n8n-workflow синхронен с базой.

Docker (образ собирается и проверяется в CI на каждый push):

```bash
docker build -t support-bot .
docker run --env-file .env -v %cd%/data:/app/data support-bot
```

Что показать за три минуты — [docs/walkthrough.md](docs/walkthrough.md).

## Версия на n8n

`n8n/support-bot.workflow.json` — тот же сценарий из узлов: **Telegram Trigger → Code (поиск по встроенной
базе, упрощённый BM25) → IF → Basic LLM Chain + Anthropic Chat Model + Structured Output Parser → IF «ответ
найден?» → ответ клиенту / сообщение о передаче + карточка оператору**.

Импорт: *Workflows → Create → Import from File*, выбрать JSON, в узлах Telegram и Anthropic Chat Model
указать свои credentials, в узле «Настройки» вписать id чата оператора. Файл генерируется из базы знаний
командой `python n8n/build_workflow.py`, после правки `knowledge/*.md` его нужно пересобрать.

## Устройство

```
support_bot/
  assistant.py   логика «ответить или передать»   search.py     BM25 + стеммер
  llm.py         Claude / заглушка, схема ответа    storage.py    журнал SQLite, метрики
  knowledge.py   разбор базы знаний (Markdown)      metrics.py    FastAPI-страница метрик
  bot/           aiogram: клиент, оператор, polling console.py    чат в терминале
  config.py      настройки из .env
knowledge/       база знаний: 5 файлов, 39 статей
n8n/             workflow JSON и генератор
tests/           pytest, 28 тестов, без сети
docs/            экскурсия за три минуты
```

Парный проект — [lead-pipeline](https://github.com/dobrewoks1/lead-pipeline): тот же вымышленный
автосервис, но с другой стороны: бот отвечает клиентам в чате, конвейер разбирает входящие заявки в таблицу.

## Что дальше

Планы — в [issues](../../issues): эмбеддинги вместо лексического поиска с тем же интерфейсом, контекст
диалога, вебхук вместо polling, напоминание оператору по обращениям без ответа.

## Как делалось

Собран в связке с Claude Code: сценарий, схема ответа, правила эскалации и проверки — мои; код и тесты
написаны агентом по ним и проверены живыми прогонами. Правила для агента в этом репозитории — [CLAUDE.md](CLAUDE.md).

## Источники

| Что взято | Откуда | Лицензия |
|---|---|---|
| Скелет бота на aiogram 3: `Dispatcher`, роутеры, запуск polling | [aiogram — examples/echo_bot.py, examples/multi_file_bot](https://github.com/aiogram/aiogram/tree/dev-3.x/examples) | MIT |
| Подход к поиску: `rank_bm25` + регулярные выражения для токенов, ответ модели только по найденным выдержкам | [levtmn/telegramRAG](https://github.com/levtmn/telegramRAG) | MIT |
| Структура n8n-workflow (Telegram Trigger → AI-узел → Telegram, подключение Chat Model / Output Parser) | шаблоны n8n.io [#2534](https://n8n.io/workflows/2534-telegram-ai-bot-assistant-ready-made-template-for-voice-and-text-messages/) и [#15933](https://n8n.io/workflows/15933-manage-telegram-task-reminders-with-claude-and-n8n-data-tables/), демо-workflow [n8n-io/self-hosted-ai-starter-kit](https://github.com/n8n-io/self-hosted-ai-starter-kit) | структура узлов; код узлов написан заново; starter-kit — Apache-2.0 |
| Формат structured outputs (`messages.parse` + Pydantic) | [документация Anthropic](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) | — |

Код проекта — MIT, см. [LICENSE](LICENSE).

---

**In English.** Telegram support assistant for a small business: BM25 retrieval over a Markdown knowledge
base, Claude answers strictly from the retrieved context and returns `{covered, answer}` via structured
outputs, uncovered questions are escalated to an operator chat and the operator's reply is routed back to
the client; every dialog is logged to SQLite with `/stats` and a FastAPI metrics page. Runs without an API
key through a deterministic fake provider (used by the test suite), ships a console mode, a Dockerfile and
the same flow exported as an n8n workflow. All data is fictional.
