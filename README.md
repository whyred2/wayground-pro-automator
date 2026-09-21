<p align="center">
  <img src="assets/logo.png" alt="Wayground Pro Automator Logo" width="100" height="100">
</p>

<p align="center">
  <h1 align="center">🚀 Wayground Pro Automator v3.0</h1>
  <p align="center">
    Automated test-taking on <b>wayground.com</b> with Smart Hybrid AI Solver & Direct API Interception
    <br />
    <a href="#-english">English</a> · <a href="#-русский">Русский</a>
    <br /><br />
    <a href="https://github.com/whyred2/wayground-pro-automator/releases/latest">
      <img src="https://img.shields.io/github/v/release/whyred2/wayground-pro-automator?style=for-the-badge&logo=windows&logoColor=white&label=Download%20.EXE&color=00c853" alt="Download Latest Release">
    </a>
  </p>
</p>

---

## ⚠️ Disclaimer / Отказ от ответственности

> **EN:** This tool is for educational and research purposes only. The developers are not responsible for any misuse or violations of terms of service of the target platforms.

> **RU:** Данный инструмент создан исключительно в образовательных и ознакомительных целях. Разработчики не несут ответственности за любое нарушение правил использования сторонних платформ.

---

## 🇬🇧 English

### Table of Contents

- [What's New in v3.0](#whats-new-in-v30)
- [What's New in v2.4](#whats-new-in-v24)
- [What's New in v2.3](#whats-new-in-v23)
- [What's New in v2.2](#whats-new-in-v22)
- [Features](#features)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Parameters](#cli-parameters)
- [How It Works](#how-it-works)

### What's New in v3.0

- **Smart Hybrid AI Solver Gateway** — Full integration with Cloudflare Workers AI and Groq Cloud. Pure zero-config experience for `.exe` releases:
  - **Cloudflare Workers AI (Primary)**: Solves questions autonomously using `@cf/meta/llama-3.3-70b-instruct` for complex reasoning and `@cf/meta/llama-3.2-11b-vision-instruct` for diagrams, geometry, and visual options.
  - **Groq Cloud (Fallback)**: Seamless failover to high-speed `qwen/qwen3.8-27b` if Cloudflare daily quotas are exceeded.
  - **100% Secure**: Zero hardcoded API keys in client binaries; all secret keys are protected behind the Cloudflare AI Gateway with IP-based rate limiting.
- **Fill-in-the-Blank (FIB) & Keystroke Automation** — Native automated resolution for text blank questions. Automatically extracts context, consults AI for the exact missing terminology, fills inputs with synthetic keystrokes, and generates human-like mistakes when deliberate errors are configured.
- **KaTeX & LaTeX Formula Extraction** — Complete mathematical formula support. Parses raw LaTeX expressions from KaTeX and MathML DOM trees, preventing empty option texts on math tests.
- **Assessment & Test Mode Auto-Navigation** — Full native support for the new assessment interface (`data-testid="question-scroll-container"` with radio groups and Next/Submit button navigation).
- **Secure BYOK & .env Architecture** — Support for `.env` and `.env.example`, allowing users to optionally provide their own personal OpenAI/Groq keys without modifying source code.

### What's New in v2.4

- **AI Solver Engine (Groq / OpenAI SDK with `qwen/qwen3.8-27b`)** — Real-time automated test-solving powered by the OpenAI Python SDK connected to Groq's high-speed API (`qwen/qwen3.8-27b`). Delivers top accuracy across academic, business, and scientific subjects.
- **Fill-in-the-Blank (FIB) & Text Input Support** — Native automated resolution for text blank questions. Automatically extracts context, consults AI for the exact missing terminology, fills inputs with synthetic keystrokes, and advances smoothly.
- **Auto-Fallback & Gap-Filling** — If Direct API and CheatNetwork cannot locate answers, the automator seamlessly switches to the AI Solver. Missing database questions are resolved by AI instead of guessing randomly.
- **Support for Modern Wayground/Quizizz Assessment & Test Mode** — Full native support for the new assessment interface (`data-testid="question-scroll-container"` with radio groups `data-testid="option-trigger-*"` and question stem `[data-highlight-block="stem"]`).
- **Auto-Advance / Next Button Navigation ("Далі ->" / "Next" / "Submit")** — In assessment mode where choosing a radio button does not auto-advance, the automator automatically locates and clicks the "Next" / "Submit" button (`Далі`, `Далее`, `Next`, `Submit`, `Завершити`, `Finish`) to transition to the next question.
- **Multi-Language Question Counter Detection** — Seamlessly reads test progress from footers in Ukrainian (`Питання 1 з 50`), Russian (`Вопрос 1 из 50`), English (`Question 1 of 50`), or classic spans. Live total updates dynamically if questions differ from initial database count.
- **Accurate Radio Button Text Extraction** — Ignores letter badges (`A`, `B`, `C`, `D`) inside `data-testid="radio"`, directly extracting the actual answer text from `.text-renderer` / `[data-highlight-block="option:*"]`.
- **Protected Intermission Logic** — Prevents accidental skipping of active questions while animations load, ensuring answers are always submitted before proceeding.

### What's New in v2.3

- **Redemption Question Support (Second Chance)** — Automatically detects the Redemption Question screen (`screen-redemption-question-selector`), clicks a card, and solves the retry question without freezing.
- **Ranked Option Matching & Anti-Distractor Engine** — Strict 100% exact match priority. Eliminates false clicks on deceptive teacher distractors (e.g. `less` vs `more`, `perihelion` vs `aphelion`, `July` vs `January`).
- **Clean Question Display & Accurate Mistakes Count** — Filters out internal MongoDB ObjectIds, `id:`, and `img:` alias keys from Phase 1. The test summary and mistakes settings now reflect the real number of questions in the test (e.g. 20 instead of 61).
- **Dedicated Browser Profile for Instant Attach** — Uses `%LocalAppData%\WaygroundAutomator\BrowserProfile` for Edge/Chrome CDP mode. Port 9222 opens in < 1 second with zero conflicts, even if you have 100 tabs open in your personal browser. Logins are remembered forever across runs.
- **Quizit Bot Deduplication & Toggle** — Single-flight lock prevents duplicate `Reconnecting...` player bots in live lobbies. Added interactive toggle and `--no-bot` CLI flag.
- **Media & Image Question Support** — Matches questions and choices using `data-quesid`, `alt` attributes, and image filenames. Intelligently waits for animations and intermission leaderboards.

### What's New in v2.2

- **Automation Resilience (Stale/Detached DOMs)** — Added a safe click wrapper. If you manually click an option in the browser before the script does, it gracefully continues without crashing.
- **Mid-Test Resume Support** — Resuming a quiz mid-way (e.g. from question 10) now works perfectly. The script lazily re-samples deliberate wrong indices and uses the real page question counter.
- **CheatNetwork Login Modal Handler** — Automatically detects "Not logged in" / "Access denied" modals on CheatNetwork, navigates back to the form, and retries up to 3 times (with zero reloads to prevent IP blocks).
- **Auto-Redirection** — If a PIN code or quiz URL is provided at startup, the Wayground browser automatically navigates to it, eliminating manual copying.
- **CLI Quiz Input** — Target URL/PIN can now be passed via the command line using `-q / --quiz-input`.

### Features

- **Hybrid Answer Engine** — Intercepts the Wayground API in the background for 100% accurate answers instantly. If that fails, auto-falls back to scraping `cheatnetwork.eu` (opened lazily, only when needed).
- **Smart Image-Variant Handling** — Automatically groups answers for graphically distinct questions with identical text to maximize accuracy.
- **Graceful Fallbacks** — If a question's options change entirely, the script intelligently selects a random choice instead of crashing.
- **Dual-mode operation** — Launch a new browser (recommended) or attach to your existing Edge/Chrome session (preserves logins).
- **Human-like behavior** — Dynamic "thinking" delays based on character count (`min 10s + 0.05s/char`), randomized click logic, and jitter ±30%.
- **Intentional errors** — Use `--wrong N` or answer interactively after seeing the question count to avoid a suspicious 100% score.
- **Clean UI** — A fully revamped terminal UI with minimal spam, dynamic animated spinners, and clear testing phases.

### Project Structure

```
src/
├── main.py          # Entry point, CLI, interactive menu
├── config.py        # Constants, selectors, timing, colors, AI settings
├── ai_solver.py     # AI real-time solver (OpenAI SDK / Groq / Qwen, text & vision)
├── ui.py            # Logging, Spinner, banners
├── browser.py       # Edge/Chrome detection & launch
├── api.py           # Network interception, Wayground API
├── scraper.py       # CheatNetwork parsing (lazy fallback)
├── matching.py      # Exact / substring / fuzzy matching
├── automation.py    # Test automation loop, highlights, results
└── tabs.py          # Tab picker (attach mode)
```

### Installation

#### Option 1: Using the Standalone `.exe` (Recommended)

1. Download the latest **[WaygroundAutomator.exe](https://github.com/whyred2/wayground-pro-automator/releases/latest)** from the **[GitHub Releases Page](https://github.com/whyred2/wayground-pro-automator/releases)**.
2. Double-click to run — no Python, Node.js, or API keys required! It works out-of-the-box using the built-in Cloudflare AI Gateway.

#### Option 2: Running from Python Source

**Prerequisites:** Python 3.10+, pip

```powershell
# 1. Install dependencies
pip install -r requirements.txt

# 2. Install Chromium browser for Playwright
python -m playwright install chromium

# 3. Configure API keys (for AI Solver)
cp .env.example .env
# Edit .env and paste your free Groq API key (from https://console.groq.com/keys)
```

### Quick Start

The simplest way is to run the interactive menu — it will guide you through everything:

```powershell
python src/main.py
```

_(Or just run the `.exe` file)_

**What happens:**

1. Select Mode `1` (New browser — recommended).
2. A Chromium browser window opens with Wayground.
3. Log into your account and navigate to the test waiting room.
4. Go back to the console and press **Enter**.
5. The script intercepts the test API, loads answers, and shows you the total question count.
6. Choose how many questions to answer wrong (or press Enter for 100%).
7. Automation begins!

### CLI Parameters

You can skip the interactive menu by providing arguments directly:

| Parameter                 | Description                                              | Default                                    |
| ------------------------- | -------------------------------------------------------- | ------------------------------------------ |
| `--ai`                    | Use AI solver exclusively (no database lookups)          | `False`                                    |
| `--no-ai`                 | Disable AI solver and auto-fallback completely           | `False`                                    |
| `--ai-key KEY`            | Custom API key for AI solver (OpenAI/Groq compatible)    | From `.env` / `OPENAI_API_KEY`             |
| `--ai-model MODEL`        | Custom model for AI solver                               | `qwen/qwen3.8-27b`                         |
| `--ai-base URL`           | Custom OpenAI API base URL                               | `https://api.groq.com/openai/v1`           |
| `--attach`                | Attach to Edge/Chrome (auto-launch if needed)            | `False`                                    |
| `--wrong N`               | Number of intentionally wrong answers                    | `0` (asks interactively if not set)        |
| `-q, --quiz-input STR`    | Quiz URL or game PIN code for answer extraction          | `None`                                     |
| `--no-bot`                | Disable Quizit solver bot in live games                  | `False`                                    |
| `--test-url URL`          | URL of the test page (for normal mode)                   | `https://wayground.com`                    |
| `--answers-url URL`       | URL of the answer key page (for fallback)                | `https://cheatnetwork.eu/services/quizizz` |

**Examples:**

```powershell
# Interactive menu (recommended)
python src/main.py

# Auto-start with AI solver directly
python src/main.py --ai

# Auto-start attach mode with 5 intentionally wrong answers
python src/main.py --attach --wrong 5
```

### How It Works

#### Phase 1: Retrieving Answer Keys

The script attaches a stealth listener to the browser's network layer. When you join the test, it instantly extracts the secret `quiz_id` from the hidden `/join` payload. It then queries the direct Wayground REST API for a 100% exact copy of the correct answers.
_If the API fails, a CheatNetwork tab is opened automatically, answers are scraped, and the tab is closed — all without manual intervention._

#### Phase 2: Test Automation

The script reads the screen and matches the prompt.

1. Computes a human-like read time (`min 10s + 0.05s/char`).
2. Highlights the screen elements being processed.
3. Solves Single-Select and Multi-Select (MSQ) questions.
4. Injects deliberate failures if `--wrong` was requested.

---

## 🇷🇺 Русский

### Содержание

- [Что нового в v3.0](#что-нового-в-v30)
- [Что нового в v2.4](#что-нового-в-v24)
- [Что нового в v2.3](#что-нового-в-v23)
- [Что нового в v2.2](#что-нового-в-v22)
- [Возможности](#возможности)
- [Структура проекта](#структура-проекта)
- [Установка](#установка)
- [Быстрый старт](#быстрый-старт)
- [Параметры запуска](#параметры-запуска)
- [Как это работает](#как-это-работает)
- [Устранение проблем](#устранение-проблем)

### Что нового в v3.0

- **Умный гибридный ИИ-шлюз (Smart Hybrid AI Gateway)** — Полная интеграция с Cloudflare Workers AI и Groq Cloud. Работа «из коробки» для пользователей `.exe` без необходимости регистрироваться на зарубежных сайтах или вводить ключи:
  - **Cloudflare Workers AI (Основной):** Автономное решение тестов с помощью флагманской модели `@cf/meta/llama-3.3-70b-instruct` (70 млрд параметров) и мультимодальной `@cf/meta/llama-3.2-11b-vision-instruct` для вопросов с картинками, графиками и геометрией.
  - **Groq Cloud (Резервный):** Автоматическое прозрачное переключение на скоростной Groq (`qwen/qwen3.8-27b`) при превышении дневных квот Cloudflare.
  - **100% безопасность:** Ключи скрыты за защищенным шлюзом Cloudflare с защитой от спама (Rate Limiter по IP).
- **Автоматизация Fill-in-the-Blank (Ввод пропущенных слов)** — Распознавание текстовых пропусков, запрос точного ответа у нейросети, посимвольный ввод и генерация реалистичных человеческих ошибок при включенном режиме намеренных ошибок (`--wrong`).
- **Извлечение формул KaTeX / LaTeX** — Нативная поддержка математики и физики. Программа извлекает исходный LaTeX-код из скрытых блоков KaTeX/MathML, гарантируя правильное понимание формул моделью.
- **Поддержка Assessment / Test Mode** — Полноценная навигация по обновленной оболочке тестов Wayground с автоматическим нажатием кнопок «Далі ->» / «Next» / «Submit».
- **Архитектура .env (BYOK)** — Возможность указать свой личный ключ через `.env` файл или флаг `--ai-key`.

### Что нового в v2.4

- **Поддержка новой оболочки тестов Wayground/Quizizz (Assessment / Test Mode)** — Полноценная работа с обновлённым интерфейсом тестирования (`data-testid="question-scroll-container"`, радиокнопки `data-testid="option-trigger-*"` и вопрос в `[data-highlight-block="stem"]`).
- **Автоматический переход к следующему вопросу («Далі ->» / «Next» / «Submit»)** — В режиме экзамена/теста, где выбор радиокнопки не перелистывает вопрос автоматически, программа нажимает кнопку перехода («Далі», «Далее», «Next», «Submit», «Завершити», «Finish»).
- **Мультиязычный счётчик вопросов** — Считывание номера вопроса и общего количества из любого футера на украинском («Питання 1 з 50»), русском («Вопрос 1 из 50»), английском («Question 1 of 50») или классических span. Если реальный тест больше загруженной базы, общее число автоматически синхронизируется.
- **Точное извлечение текста вариантов** — Буквы маркировки (`A`, `B`, `C`, `D`) внутри радио-переключателей игнорируются, а текст варианта извлекается напрямую из `.text-renderer` / `[data-highlight-block="option:*"]`.
- **Защита от ложного пропуска вопросов** — Программа гарантирует, что кнопка «Далее» нажимается только после выбора ответа, а не во время анимации или загрузки вопроса.

### Что нового в v2.3

- **Поддержка Redemption Question (Второй шанс)** — Программа автоматически распознаёт экран искупления (`screen-redemption-question-selector`), выбирает карточку и решает повторный вопрос без зависания на таймаутах.
- **Ранжированный скоринг вариантов и защита от дистракторов** — Строгий приоритет 100% точного совпадения. Варианты-ловушки (дистракторы), похожие на 85–92% и отличающиеся всего одним словом (*less/more*, *perihelion/aphelion*, *July/January*), больше не нажимаются ошибочно.
- **Чистый список вопросов и точная настройка ошибок** — Из таблицы Phase 1 удалены внутренние технические MongoDB ObjectIds, префиксы `id:` и `img:`. Программа отображает ровно то количество вопросов, которое есть в тесте (например, 20 вместо 61), а намеренные ошибки распределяются точно.
- **Мгновенное подключение к Edge/Chrome через изолированный профиль** — Профиль `%LocalAppData%\WaygroundAutomator\BrowserProfile` запускает отладочный порт за 1 секунду без конфликтов с вашим личным Edge и фоновыми процессами. Сессии и логины навсегда сохраняются, а браузер не закрывается при выходе из консоли.
- **Дедупликация Quizit Bot и флаг `--no-bot`** — Защита от дублирования ботов `Reconnecting...` в лобби учителя (Single-Flight блокировка). Добавлен флаг `--no-bot` и интерактивное подтверждение в меню.
- **Полноценная поддержка вопросов с картинками** — Точное сопоставление по `data-quesid`, `alt` и именам файлов изображений. Умное ожидание промежуточных анимаций, таблиц лидеров и страйков.

### Что нового в v2.2

- **Повышенная стабильность (Stale/Detached DOM)** — Безопасный обход ошибок Playwright. Если вы кликнете по варианту ответа раньше скрипта, программа продолжит работу без краша.
- **Запуск теста с любого вопроса** — Поддерживается довыполнение тестов с середины (например, с 10-го вопроса). Индексы намеренных ошибок перераспределяются среди оставшихся вопросов.
- **Авто-обход окон авторизации CheatNetwork** — Скрипт распознает сообщения «Not logged in» / «Access denied», возвращается на форму и пробует отправить запрос заново до 3 раз без перезагрузки страниц (предотвращает бан IP).
- **Авто-переход к тесту** — Браузер Wayground автоматически перейдет по ссылке или введенному PIN-коду при старте, избавляя вас от ручного копирования.
- **Флаг запуска `--quiz-input`** — Возможность передавать URL или PIN-код игры сразу через консоль при запуске с помощью `-q / --quiz-input`.

### Возможности

- **Гибридный движок** — Скрипт перехватывает сетевой трафик (Wayground API) в фоне и достаёт 100% точные ответы за долю секунды. При неудаче автоматически открывает CheatNetwork, парсит ответы и закрывает вкладку.
- **Умная обработка картинок** — Аккумулирует и группирует варианты ответов для вопросов с одинаковым текстом, но разными картинками.
- **Не падает при ошибках (Graceful Fallback)** — Если варианты ответов в тесте мутировали до неузнаваемости, скрипт не крашится, а делает "умную" случайную догадку и идёт дальше.
- **Два режима работы** — Новый браузер (рекомендуется) или подключение к вашему Edge/Chrome (сохраняет логины).
- **Имитация человека** — Динамические задержки на чтение (`минимум 10 сек + 0.05 сек/символ`), хаотичные движения и jitter ±30%.
- **Намеренные ошибки** — Используйте `--wrong N` или ответьте интерактивно после загрузки вопросов, чтобы не вызывать подозрений идеальным 100%.
- **Чистый интерфейс консоли** — Анимированные загрузки, статусы фаз и аккуратный лог.

### Структура проекта

```
src/
├── main.py          # Точка входа, CLI, интерактивное меню
├── config.py        # Константы, селекторы, тайминги, цвета
├── ui.py            # Логирование, Spinner, баннер
├── browser.py       # Обнаружение и запуск Edge/Chrome
├── api.py           # Перехват сети, прямой API Wayground
├── scraper.py       # Парсинг CheatNetwork (ленивый fallback)
├── matching.py      # Exact / substring / fuzzy matching
├── automation.py    # Цикл автоматизации, подсветка, результаты
└── tabs.py          # Выбор вкладок (attach-режим)
```

### Установка

#### Способ 1: Использование готового `.exe` (Рекомендуется)

1. Скачайте свежую версию **[WaygroundAutomator.exe](https://github.com/whyred2/wayground-pro-automator/releases/latest)** со страницы **[Релизов GitHub](https://github.com/whyred2/wayground-pro-automator/releases)**.
2. Запустите файл двойным кликом — установка Python, браузеров и ввод API-ключей **не требуются**! Программа сразу готова к работе через встроенный Cloudflare AI Gateway.

#### Способ 2: Запуск из исходников Python

**Требования:** Python 3.10+, pip

```powershell
# 1. Загрузите библиотеки
pip install -r requirements.txt

# 2. Установите браузер Chromium для Playwright
python -m playwright install chromium

# 3. Настройте API-ключ для ИИ-решателя (AI Solver)
cp .env.example .env
# Откройте .env и вставьте ваш бесплатный ключ Groq (получить на https://console.groq.com/keys)
```

### Быстрый старт

Самый простой способ — запустить интерактивное меню:

```powershell
python src/main.py
```

_(Или просто откройте файл `.exe`)_

**Что произойдёт:**

1. Выберите режим `1` (Новый браузер — рекомендуется).
2. Откроется окно Chromium с сайтом Wayground.
3. Авторизуйтесь под своим аккаунтом и перейдите на страницу ожидания теста.
4. Вернитесь в консоль и нажмите **Enter**.
5. Скрипт перехватит API, загрузит ответы и покажет общее количество вопросов.
6. Укажите сколько вопросов ответить неправильно (или нажмите Enter для 100%).
7. Автоматизация начнётся!

### Параметры запуска

Можно пропустить интерактивное меню, передав аргументы:

| Параметр                 | Описание                                                | По умолчанию                               |
| ------------------------ | ------------------------------------------------------- | ------------------------------------------ |
| `--ai`                   | Решать тест напрямую через AI Solver (без поиска базы)  | `False`                                    |
| `--no-ai`                | Полностью отключить ИИ-солвер и авто-переключение на ИИ | `False`                                    |
| `--ai-key KEY`           | Пользовательский API ключ (Groq / OpenAI)               | Из `.env` / `OPENAI_API_KEY`               |
| `--ai-model MODEL`       | Модель для решения (Groq / OpenAI)                     | `qwen/qwen3.8-27b`                         |
| `--ai-base URL`          | Базовый URL OpenAI-совместимого API                     | `https://api.groq.com/openai/v1`           |
| `--attach`               | Подключиться к Edge/Chrome (автозапуск при нужде)       | `False`                                    |
| `--wrong N`              | Сделать N намеренных ошибок (иначе спросит в меню)      | `0` (100% правильных)                      |
| `-q, --quiz-input STR`   | Ссылка на тест или PIN-код игры для выгрузки ответов    | `None`                                     |
| `--no-bot`               | Отключить гостевого бота Quizit для live-игр            | `False`                                    |
| `--test-url URL`         | URL страницы теста                                      | `https://wayground.com`                    |
| `--answers-url URL`      | URL сервиса ответов CheatNetwork (fallback)             | `https://cheatnetwork.eu/services/quizizz` |

**Примеры:**

```powershell
# Запуск напрямую через AI Solver (qwen/qwen3.8-27b)
python src/main.py --ai

# Запуск с 6 специальными ошибками через attach-режим
python src/main.py --attach --wrong 6
```

### Как это работает

#### Выгрузка правильных ответов (Phase 1)

Скрипт мониторит вкладку "Network" (Сеть) вашего браузера через протокол отладки. Во время входа в тест ловится скрытый запрос `/join`, из которого достаётся ID теста. Затем напрямую из закрытого API вытаскиваются все правильные ответы.
_Если API не сработал, скрипт автоматически откроет вкладку CheatNetwork, спарсит ответы и закроет её — без вашего вмешательства._

#### Решение (Phase 2)

1. Вычисляет время на чтение человеком (`минимум 10 сек + 0.05 сек на символ`).
2. Отыскивает правильную кнопку. При совпадении текстов (у задач с картинками) фильтрует несуществующие кнопки.
3. В случае `--wrong` специально кликает на неправильный ответ N раз за весь тест.

### Устранение проблем

<details>
<summary><b>❌ Could not connect on port 9222</b></summary>

**Причина:** Ваш Edge работает в фоне и мешает подключиться к порту отладки.
**Решение:** Нажмите `Ctrl+Shift+Esc` (Диспетчер задач) и завершите все процессы `msedge.exe`. Затем запустите программу снова.

</details>

<details>
<summary><b>❌ [SKIP] Answer options changed or not found</b></summary>

**Причина:** Кнопки на экране не совпадают ни с одним ответом из базы (например, вопрос содержит сложное форматирование).
**Решение:** Программа автоматически отработает эту исключительную ситуацию (угадает случайный ответ вместо того, чтобы зависнуть или "упасть"). Ничего делать не нужно!

</details>

<p align="center">
  <sub>Built with <a href="https://playwright.dev/python/">Playwright</a> · Python 3.10+</sub>
</p>
