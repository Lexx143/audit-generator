# Audit Generator AI

[Read in English](#english-version)

Веб-приложение для генерации отчетов по ИТ-аудитам в формате PowerPoint.
Аудитор вводит сырые данные осмотра (что за компания, какие проблемы нашли,
общие выводы) — приложение с помощью LLM формирует структуру отчета:
кейсы с описанием уязвимостей, рисков и рекомендаций, генерирует
иллюстрации и собирает готовый брендированный `.pptx` по корпоративному шаблону.

Ключевая особенность — **самообучающаяся база знаний**: каждый одобренный
отчет пополняет векторную базу примеров (кейсы, формулировки, выводы,
иллюстрации), и следующие отчеты генерируются с опорой на реальные
образцы, становясь точнее и ближе по тону к «ручным» отчетам компании.

## Возможности

- **Генерация структуры аудита** из сырого текста: кейс на каждую указанную
  уязвимость (без ограничения количества), приоритеты, категории, обзор, выводы
- **RAG few-shot**: промпт обогащается похожими кейсами из прошлых аудитов
  (ChromaDB + OpenAI embeddings)
- **Иллюстрации кейсов**: генерация (gpt-image-2, три стиля — 3D-иконка,
  плоский вектор, изометрия), загрузка своих картинок/фото, автоподбор
  ранее сгенерированных из библиотеки по смыслу кейса (с перелистыванием)
- **Умные правки**: свободной формулировкой («убери кейс про антивирус,
  риски сделай жестче») — ИИ переписывает структуру; отдельная кнопка
  улучшения текста на каждом кейсе
- **Профили аудиторов**: имя и фото (с интерактивным кадрированием,
  маска-«капелька» как в фирменном шаблоне) — подставляются в отчет
- **Экспорт PPTX**: динамическое клонирование слайдов под любое число
  кейсов и категорий, автонумерация разделов, перекраска плашек приоритета,
  раздельные строки «Уязвимость / Риски / Рекомендации», авторазмещение
  картинок без наездов на текст
- **Два типа аудита**: экспресс (уязвимости + риски) и полный (+ рекомендации)
- **Черновики** в localStorage (F5 не теряет работу), мобильная верстка,
  темная/светлая тема

## Архитектура

```
┌──────────────┐   /api/*    ┌────────────────────────────────┐
│ React + Vite │ ──────────► │ FastAPI (async)                │
│    (SPA)     │             │  ├─ llm.py     — GPT (structured outputs)
└──────────────┘             │  ├─ imaging.py — gpt-image-2 + фолбэки
       ▲                     │  ├─ rag.py     — ChromaDB, база знаний
       │ static              │  └─ pptx_builder.py — python-pptx
┌──────┴───────┐             └────────────────┬───────────────┘
│    Nginx     │                              │
│ (контейнер   │                      ┌───────▼──────┐
│  frontend)   │                      │  backend/db/ │
└──────────────┘                      │ chroma+файлы │
                                      └──────────────┘
```

- **backend/** — FastAPI: `routers/` (тонкие эндпоинты), `llm.py` (структурная
  генерация через structured outputs), `rag.py` (коллекции знаний, семантический
  дедуп подсказок, библиотека картинок), `imaging.py` (генерация с каскадом
  фолбэков: gpt-image-2 → Pollinations → локальный плейсхолдер),
  `pptx_builder.py` (сборка отчета: клонирование слайдов, динамические таблицы)
- **frontend/** — React SPA, собирается в статику, раздается Nginx,
  который проксирует `/api/` на бэкенд
- **Хранилище** — ChromaDB (sqlite) + файлы в `backend/db/`:
  без внешних СУБД, вся база знаний переносится копированием папки

## Требования

- Python 3.11+, Node 18+ (для разработки) или Docker + Docker Compose (для прода)
- OpenAI API key с доступом к текстовым и графическим моделям
- **Шаблон отчета** `backend/assets/template.pptx` — в репозиторий не входит
  (фирменный дизайн). Ожидаемая структура: титул, введение, ревью, счетчики,
  долевое распределение, слайд-разделитель секции, слайды кейсов
  (таблица 2×1 + плашка приоритета), выводы, контакты

## Быстрый старт (разработка)

```bash
# бэкенд
cd backend
python -m venv venv && ./venv/bin/pip install -r requirements.txt
# создать .env (см. таблицу ниже)
./venv/bin/uvicorn main:app --reload --host 0.0.0.0

# фронтенд (отдельный терминал)
cd frontend
npm install
npm run dev -- --host           # http://localhost:5173
```

Переменные `.env`:

| Переменная | По умолчанию | Описание |
|---|---|---|
| `OPENAI_API_KEY` | — | ключ OpenAI (текст + картинки) |
| `TEXT_MODEL` | `gpt-5.5` | модель генерации структуры |
| `REASONING_EFFORT` | `medium` | глубина рассуждений (low/medium/high) |
| `IMAGE_MODEL` | `gpt-image-2` | модель генерации иллюстраций |
| `IMAGE_QUALITY` | `medium` | качество картинок (low/medium/high) |
| `IMAGE_SIZE` | `1024x1024` | размер картинок |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | эмбеддинги для RAG |

## Продакшен (Docker)

```bash
docker compose up -d --build
```

Поднимаются два контейнера: `audit-backend` (uvicorn) и `audit-frontend`
(nginx со статикой + прокси `/api/`; порт 3000 привязан к docker-мосту,
из интернета напрямую недоступен). Наружу приложение публикуется внешним
reverse-proxy (Caddy/Nginx) с TLS и basic auth.

Деплой одной командой: `./deploy.sh [backend|frontend]` — пуш в GitHub,
пуш на сервер (git push-to-deploy), пересборка контейнеров. Адрес сервера
хранится в локальном файле `.deploy-server` (не в git).

## Обслуживание базы знаний

| Скрипт | Назначение |
|---|---|
| `backend/import_examples.py` | первичный импорт кейсов из `data/*.json` в векторную базу |
| `backend/normalize_hints.py` | LLM-ревизия выпадающего списка частых уязвимостей: дедуп, единый стиль, категории (запускать периодически) |

База знаний пополняется автоматически: при скачивании отчета с включенной
галочкой «сохранить в базу знаний» кейсы, выводы, подсказки и переиспользуемые
иллюстрации записываются в ChromaDB. Фотографии объектов клиентов
в библиотеку не сохраняются.

## Данные и приватность

В репозитории **нет**: фирменного шаблона, базы знаний, реальных кейсов
аудитов, ключей и адресов инфраструктуры — все это живет только на
рабочей машине и сервере (`backend/db/`, `backend/data/`,
`backend/assets/template.pptx`, `.env`, `.deploy-server` — в `.gitignore`).

## Автор

Lexx · [deuslevolt013@gmail.com](mailto:deuslevolt013@gmail.com)



---

<a id="english-version"></a>
# Audit Generator AI (English)

Web application for generating IT audit reports in PowerPoint format.
The auditor inputs raw inspection data (company details, discovered issues, general conclusions) — the application uses LLM to generate the report structure: cases detailing vulnerabilities, risks, and recommendations, generates illustrations, and compiles a ready-to-use branded `.pptx` following the corporate template.

A key feature is the **self-learning knowledge base**: every approved report populates the vector database with examples (cases, phrasing, conclusions, illustrations), so subsequent reports are generated based on real samples, becoming more accurate and closer in tone to the company's "manual" reports.

## Features

- **Audit structure generation** from raw text: a case for each specified vulnerability (no limit on quantity), priorities, categories, overview, conclusions.
- **RAG few-shot**: the prompt is enriched with similar cases from past audits (ChromaDB + OpenAI embeddings).
- **Case illustrations**: generation (gpt-image-2, three styles — 3D icon, flat vector, isometric), upload custom pictures/photos, auto-selection of previously generated images from the semantic library (with swipe).
- **Smart edits**: using free-form phrasing ("remove the antivirus case, make the risks harsher") — the AI rewrites the structure; individual text improvement button on each case.
- **Auditor profiles**: name and photo (with interactive cropping, "teardrop" mask matching the branded template) — automatically inserted into the report.
- **PPTX Export**: dynamic slide cloning for any number of cases and categories, auto-numbering of sections, recoloring priority badges, separate rows for "Vulnerability / Risks / Recommendations", auto-placement of images without overlapping text.
- **Two audit types**: express (vulnerabilities + risks) and full (+ recommendations).
- **Drafts** in localStorage (F5 does not lose work), mobile-responsive layout, dark/light theme.

## Architecture

```
┌──────────────┐   /api/*    ┌────────────────────────────────┐
│ React + Vite │ ──────────► │ FastAPI (async)                │
│    (SPA)     │             │  ├─ llm.py     — GPT (structured outputs)
└──────────────┘             │  ├─ imaging.py — gpt-image-2 + fallbacks
       ▲                     │  ├─ rag.py     — ChromaDB, knowledge base
       │ static              │  └─ pptx_builder.py — python-pptx
┌──────┴───────┐             └────────────────┬───────────────┘
│    Nginx     │                              │
│ (frontend    │                      ┌───────▼──────┐
│  container)  │                      │  backend/db/ │
└──────────────┘                      │ chroma+files │
                                      └──────────────┘
```

- **backend/** — FastAPI: `routers/` (thin endpoints), `llm.py` (structured generation via structured outputs), `rag.py` (knowledge collections, semantic hint deduplication, image library), `imaging.py` (generation with fallback cascade: gpt-image-2 → Pollinations → local placeholder), `pptx_builder.py` (report assembly: slide cloning, dynamic tables).
- **frontend/** — React SPA, built as static files, served by Nginx, which proxies `/api/` to the backend.
- **Storage** — ChromaDB (sqlite) + files in `backend/db/`: no external DBMS, the entire knowledge base is portable simply by copying the folder.

## Requirements

- Python 3.11+, Node 18+ (for development) or Docker + Docker Compose (for production).
- OpenAI API key with access to text and image models.
- **Report template** `backend/assets/template.pptx` — not included in the repository (branded design). Expected structure: title, introduction, review, counters, distribution chart, section divider slide, case slides (2x1 table + priority badge), conclusions, contacts.

## Quick Start (Development)

```bash
# backend
cd backend
python -m venv venv && ./venv/bin/pip install -r requirements.txt
# create .env (see table below)
./venv/bin/uvicorn main:app --reload --host 0.0.0.0

# frontend (separate terminal)
cd frontend
npm install
npm run dev -- --host           # http://localhost:5173
```

`.env` variables:

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | — | OpenAI key (text + images) |
| `TEXT_MODEL` | `gpt-5.5` | Model for structure generation |
| `REASONING_EFFORT` | `medium` | Reasoning depth (low/medium/high) |
| `IMAGE_MODEL` | `gpt-image-2` | Model for illustration generation |
| `IMAGE_QUALITY` | `medium` | Image quality (low/medium/high) |
| `IMAGE_SIZE` | `1024x1024` | Image size |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embeddings for RAG |

## Production (Docker)

```bash
docker compose up -d --build
```

Spins up two containers: `audit-backend` (uvicorn) and `audit-frontend` (nginx with static files + `/api/` proxy; port 3000 is bound to the docker bridge, not accessible directly from the internet). The application is exposed externally via a reverse proxy (Caddy/Nginx) with TLS and basic auth.

One-command deploy: `./deploy.sh [backend|frontend]` — push to GitHub, push to server (git push-to-deploy), rebuild containers. Server address is stored in the local file `.deploy-server` (not in git).

## Knowledge Base Maintenance

| Script | Purpose |
|---|---|
| `backend/import_examples.py` | Initial import of cases from `data/*.json` into the vector database |
| `backend/normalize_hints.py` | LLM-revision of the frequent vulnerabilities dropdown: deduplication, unified style, categories (run periodically) |

The knowledge base populates automatically: when downloading a report with the "save to knowledge base" checkbox checked, cases, conclusions, hints, and reusable illustrations are written to ChromaDB. Photos of client sites are not saved to the library.

## Data and Privacy

The repository does **not** contain: the branded template, the knowledge base, real audit cases, keys, and infrastructure addresses — all of this lives only on the local machine and the server (`backend/db/`, `backend/data/`, `backend/assets/template.pptx`, `.env`, `.deploy-server` — in `.gitignore`).

## Author

Lexx · [deuslevolt013@gmail.com](mailto:deuslevolt013@gmail.com)
