<p align="center">
  <img src="assets/logo.png" alt="Wayground Pro Automator Logo" width="100" height="100">
</p>

<p align="center">
  <h1 align="center">🚀 Wayground Pro Automator v3.2</h1>
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

- [What's New in v3.2](#whats-new-in-v32)
- [What's New in v3.0.1](#whats-new-in-v301)
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
- [Running Tests](#running-tests)

### What's New in v3.2

- **Separate keys for repeated questions** — Questions with identical wording retain their own IDs, answers, and option sets. A quiz with 51 questions now displays 51 rows instead of grouping repeated prompts. Matching uses question IDs first, then the visible option set when IDs are unavailable; option order can be shuffled.
- **Direct game lookup and verified public quiz keys** — Resolves game PINs, room hashes, quiz IDs, and URLs through the Wayground API. If a game hides its keys, the public library is searched and candidates are checked against the game's question IDs, content, and options. BLANK questions resolve explicit target/option mappings, including multiple blanks and accepted spellings.
- **No fabricated fallback answers** — Missing keys, ambiguous matches, incomplete blank answers, and failed AI requests stop automation before submission. The program no longer substitutes generic `yes` or `answer` fallbacks, repeats a partial answer across blanks, or selects a random option when no answer was found. Waiting timeouts do not count as test completion.
- **AI selection with real availability checks** — Choose Smart Hybrid, Qwen 3.8 27B via Groq, GPT-OSS 120B / 20B, a configured personal API, or no AI before starting. Each engine is checked with a test request. Qwen can use Groq through the gateway without a personal key; GPT-OSS can use the gateway when a Groq key is not configured. GPT-OSS presets are text-only.
- **Stable CheatNetwork fallback** — Offers existing answer tabs after target API lookup fails and preserves user-owned tabs. Waits for `Downloading answers...` for up to five minutes without refreshing; persistent `Not logged in` pauses for manual sign-in. Closed tabs and browsers are handled without continuing automation.
- **Quizit sign-in flow and regression checks** — Optional Quizit Standard fallback uses its website's normal account sign-in and captures the requested result. Unsolved responses are rejected, duplicate requests are avoided, and `--no-bot` disables this fallback. The `tests/` directory covers answer parsing, repeated prompts, navigation, AI failures, tabs, and gateway routing.

### What's New in v3.0.1

- **Cloudflare Workers AI Llama 3.3 70B Model Routing**: Corrected model routing to `@cf/meta/llama-3.3-70b-instruct-fp8-fast`, enabling seamless, full-capacity execution of Meta Llama 3.3 70B directly on Cloudflare edge.
- **Client Gateway Priority & Failover**: Configured the automator client to prioritize the Smart Hybrid Gateway by default, with automatic failover to local API keys if the gateway is ever offline.
- **Transparent AI Provider Labeling**: Console logs now dynamically report the exact active AI engine (`Smart Hybrid (Llama 3.3 70B)`) and tag every answer with its source (`[Cloudflare Workers AI]` or `[Groq Cloud (Fallback)]`).

### What's New in v3.0

- **Smart Hybrid AI Solver Gateway** — Full integration with Cloudflare Workers AI and Groq Cloud. Pure zero-config experience for `.exe` releases:
  - **Cloudflare Workers AI (Primary)**: Solves questions autonomously using `@cf/meta/llama-3.3-70b-instruct-fp8-fast` for complex reasoning and `@cf/meta/llama-3.2-11b-vision-instruct` for diagrams, geometry, and visual options.
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

- **Hybrid Answer Engine** — Retrieves explicit Wayground API keys, checks public quiz candidates against the game, and supports captured network responses, optional Quizit Standard, and CheatNetwork fallback. AI can solve missing questions when enabled.
- **Separate Question Records** — Repeated wording and image variants keep their own answers. IDs and visible option sets distinguish variants without merging their keys.
- **Unresolved Questions Stop Automation** — If no complete answer is available, the current question is left unsubmitted with an explanation.
- **Dual-mode operation** — Attach to Edge/Chrome (recommended in the interactive menu, preserves logins) or launch a new standalone browser.
- **Human-like behavior** — Dynamic "thinking" delays based on character count (`min 10s + 0.05s/char`), randomized click logic, and jitter ±30%.
- **Intentional errors** — Use `--wrong N` or answer interactively after seeing the question count to avoid a suspicious 100% score.
- **Clean UI** — A fully revamped terminal UI with minimal spam, dynamic animated spinners, and clear testing phases.

### Project Structure

```
src/
├── main.py          # Entry point, CLI, interactive menu
├── config.py        # Constants, selectors, timing, colors, AI settings
├── ai_setup.py      # AI selection and availability checks
├── ai_solver.py     # AI real-time solver (OpenAI SDK / Groq / Qwen, text & vision)
├── answer_db.py     # Separate records for each question and answer key
├── answer_tabs.py   # Existing CheatNetwork tabs and fallback ownership
├── ui.py            # Logging, Spinner, banners
├── browser.py       # Edge/Chrome detection & launch
├── api.py           # Network interception, Wayground API
├── quizit.py        # Optional Quizit Standard browser sign-in/result flow
├── scraper.py       # CheatNetwork parsing (lazy fallback)
├── matching.py      # Exact / substring / fuzzy matching
├── automation.py    # Test automation loop, highlights, results
└── tabs.py          # Tab picker (attach mode)

tests/               # Python regression checks and Node.js gateway tests
cloudflare-worker/   # AI gateway implementation and deployment configuration
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

# 3. Optional: configure personal API keys or a custom gateway
cp .env.example .env
# Edit .env if using your own provider; the bundled gateway needs no personal key
```

### Quick Start

The simplest way is to run the interactive menu — it will guide you through everything:

```powershell
python src/main.py
```

_(Or just run the `.exe` file)_

**What happens:**

1. Select Mode `1` (Attach to Edge/Chrome — recommended), or `2` for a standalone browser.
2. The browser opens or connects; select the Wayground test tab when prompted.
3. Log into your account and navigate to the test waiting room.
4. Go back to the console and press **Enter**.
5. Select Smart Hybrid, Qwen through Groq, GPT-OSS 120B / 20B, a configured personal API, or no AI. Each engine shows **Available / Unavailable** after a test request. Qwen and GPT-OSS can use the bundled gateway without a personal key; a configured Groq key enables direct Groq requests for these presets.
6. The program retrieves target API keys first, then offers fallbacks if needed. Existing CheatNetwork answer tabs can be selected without reloading them. Quizit Standard requires its own account; `--no-bot` disables it.
7. Review the complete question list and choose how many questions to answer wrong (or press Enter for no deliberate mistakes).
8. Automation begins!

### CLI Parameters

You can skip the interactive menu by providing arguments directly:

| Parameter                 | Description                                              | Default                                    |
| ------------------------- | -------------------------------------------------------- | ------------------------------------------ |
| `--ai`                    | Use AI solver exclusively (no database lookups)          | `False`                                    |
| `--ai-provider ENGINE`    | Choose `gateway`, `direct`, `groq-120b`, `groq-20b`, or `off`; enabled engines are checked before starting | Interactive selection |
| `--no-ai`                 | Disable AI solver and auto-fallback completely           | `False`                                    |
| `--ai-key KEY`            | Custom API key for AI solver (OpenAI/Groq compatible)    | From `.env` / `OPENAI_API_KEY`             |
| `--ai-model MODEL`        | Custom model for AI solver                               | `qwen/qwen3.8-27b`                         |
| `--ai-base URL`           | Custom OpenAI API base URL                               | `https://api.groq.com/openai/v1`           |
| `--attach`                | Attach to Edge/Chrome (auto-launch if needed)            | `False`                                    |
| `--wrong N`               | Number of intentionally wrong answers                    | `0` (asks interactively if not set)        |
| `-q, --quiz-input STR`    | Game PIN, room hash, quiz ID, or supported URL for answer lookup | `None`                              |
| `--no-bot`                | Disable optional Quizit Standard/Bot fallback             | `False`                                    |
| `--port PORT`             | Browser debug port for attach mode                       | `9222`                                     |
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

The program resolves the selected game's PIN or room hash and reads explicit keys from the Wayground Game API. When the server hides keys, it searches the public library and verifies a candidate against the game questions before using its answers. A listener on the selected test tab also captures answer keys supplied by normal browser responses. Keys are stored separately for each question, including repeated wording.

If direct lookup fails, existing CheatNetwork answer tabs are offered as a fallback. Optional Quizit Standard may require sign-in to a Quizit account. CheatNetwork download dialogs are waited out without automatic refreshes; login notices pause for manual sign-in. Existing tabs stay open; only a temporary tab created by the program may be closed after successful retrieval.

#### Phase 2: Test Automation

The script reads the screen and matches the prompt.

1. Computes a human-like read time (`min 10s + 0.05s/char`).
2. Highlights the screen elements being processed.
3. Solves Single-Select and Multi-Select (MSQ) questions.
4. Injects deliberate failures if `--wrong` was requested.
5. Tracks the live question number so consecutive identical prompts are treated as separate questions. Missing or ambiguous answers stop automation without submission; a waiting timeout does not report successful completion.

### Running Tests

From the project root with the Python dependencies installed:

```powershell
python -m unittest discover -s tests
```

Gateway tests additionally require Node.js:

```powershell
node --test tests/test_gateway.mjs
```

Commit `tests/` with the source changes. These regression checks are not included in the standalone `.exe`.

---

## 🇷🇺 Русский

### Содержание

- [Что нового в v3.2](#что-нового-в-v32)
- [Что нового в v3.0.1](#что-нового-в-v301)
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
- [Запуск проверок](#запуск-проверок)

### Что нового в v3.2

- **Отдельные ключи повторяющихся вопросов** — Вопросы с одинаковым текстом сохраняют собственные ID, ответы и варианты. Тест из 51 вопроса отображается в 51 строке без группировки формулировок. Сначала используется ID; если его нет на странице, вопрос сопоставляется по набору вариантов, в том числе при их перемешивании.
- **Прямой API игры и проверенные ключи публичных тестов** — Поддерживаются PIN игры, хеш комнаты, ID теста и ссылки. Если сервер скрывает ответы, программа ищет оригинал в публичной библиотеке и проверяет ID, содержимое и варианты вопросов. Для BLANK используются явные связи между пропусками и вариантами, включая несколько полей и допустимые написания.
- **Остановка при отсутствии ответа** — Неоднозначные совпадения, неполные ключи и ошибки ИИ останавливают программу до отправки. Удалены запасные подстановки `yes` / `answer`, повторение одного ответа во всех пропусках и случайный выбор без найденного ключа. Таймаут ожидания не считается завершением теста.
- **Выбор ИИ с проверкой доступности** — Перед тестом доступны Smart Hybrid, Qwen 3.8 27B через Groq, GPT-OSS 120B / 20B, настроенный личный API и отключение ИИ. Доступность проверяется пробным запросом. Qwen может использовать Groq через шлюз без личного ключа; GPT-OSS используют шлюз, если ключ Groq не настроен. Предустановки GPT-OSS работают с текстом.
- **Стабильная работа CheatNetwork** — После неудачи прямого API можно выбрать уже открытую вкладку ответов. Пользовательские вкладки сохраняются. Окно `Downloading answers...` ожидается до пяти минут без перезагрузки; устойчивое `Not logged in` приостанавливает работу для ручного входа. Закрытие вкладки или браузера обрабатывается корректно.
- **Авторизация Quizit и регрессионные проверки** — Дополнительный источник Quizit Standard использует обычный вход через сайт и получает результат его запроса. Результаты без полученных ключей не принимаются за ответы; повторные запросы предотвращены. `--no-bot` отключает этот источник. Папка `tests/` содержит проверки парсинга, повторов, переходов, ошибок ИИ, вкладок и маршрутизации шлюза.

### Что нового в v3.0.1

- **Исправление маршрутизации модели Llama 3.3 70B в Cloudflare Workers AI**: Указан точный идентификатор модели `@cf/meta/llama-3.3-70b-instruct-fp8-fast`, что позволило нейросети решать задачи напрямую на edge-инфраструктуре Cloudflare без ошибок.
- **Приоритет Smart Hybrid Gateway и авто-failover**: Клиент теперь по умолчанию обращается к шлюзу Cloudflare (Llama 3.3 70B), даже если в `.env` прописан локальный ключ, и автоматически переключается на прямой ключ Groq при недоступности шлюза.
- **Прозрачные логи провайдера**: В консоли отображается активный движок (`Smart Hybrid (Llama 3.3 70B)`), а каждый ответ помечается источником (`[Cloudflare Workers AI]` или `[Groq Cloud (Fallback)]`).

### Что нового в v3.0

- **Умный гибридный ИИ-шлюз (Smart Hybrid AI Gateway)** — Полная интеграция с Cloudflare Workers AI и Groq Cloud. Работа «из коробки» для пользователей `.exe` без необходимости регистрироваться на зарубежных сайтах или вводить ключи:
  - **Cloudflare Workers AI (Основной):** Автономное решение тестов с помощью флагманской модели `@cf/meta/llama-3.3-70b-instruct-fp8-fast` (70 млрд параметров) и мультимодальной `@cf/meta/llama-3.2-11b-vision-instruct` для вопросов с картинками, графиками и геометрией.
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

- **Гибридный движок** — Получает явные ключи из API Wayground, проверяет публичные тесты по вопросам игры и поддерживает ответы из сетевых запросов, дополнительный источник Quizit Standard и CheatNetwork. При включённом ИИ он может решить недостающий вопрос.
- **Отдельные записи вопросов** — Повторяющиеся формулировки и вопросы с картинками сохраняют собственные ответы. Варианты различаются по ID и набору ответов на экране без объединения ключей.
- **Остановка при отсутствии ключа** — Если полный ответ не найден, вопрос остаётся неотправленным, а программа сообщает причину.
- **Два режима работы** — Подключение к Edge/Chrome (рекомендуется в интерактивном меню, сохраняет логины) или новый отдельный браузер.
- **Имитация человека** — Динамические задержки на чтение (`минимум 10 сек + 0.05 сек/символ`), хаотичные движения и jitter ±30%.
- **Намеренные ошибки** — Используйте `--wrong N` или ответьте интерактивно после загрузки вопросов, чтобы не вызывать подозрений идеальным 100%.
- **Чистый интерфейс консоли** — Анимированные загрузки, статусы фаз и аккуратный лог.

### Структура проекта

```
src/
├── main.py          # Точка входа, CLI, интерактивное меню
├── config.py        # Константы, селекторы, тайминги, цвета
├── ai_setup.py      # Выбор ИИ и проверка доступности
├── ai_solver.py     # ИИ-решатель для текста и изображений
├── answer_db.py     # Отдельная запись и ключ для каждого вопроса
├── answer_tabs.py   # Выбор и сохранение вкладок CheatNetwork
├── ui.py            # Логирование, Spinner, баннер
├── browser.py       # Обнаружение и запуск Edge/Chrome
├── api.py           # Перехват сети, прямой API Wayground
├── quizit.py        # Вход в Quizit Standard и получение результата через сайт
├── scraper.py       # Парсинг CheatNetwork (ленивый fallback)
├── matching.py      # Exact / substring / fuzzy matching
├── automation.py    # Цикл автоматизации, подсветка, результаты
└── tabs.py          # Выбор вкладок (attach-режим)

tests/               # Проверки Python и тесты шлюза на Node.js
cloudflare-worker/   # Код ИИ-шлюза и настройки публикации
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

# 3. Необязательно: настройте личный API-ключ или собственный шлюз
cp .env.example .env
# Измените .env для своего провайдера; встроенный шлюз не требует личного ключа
```

### Быстрый старт

Самый простой способ — запустить интерактивное меню:

```powershell
python src/main.py
```

_(Или просто откройте файл `.exe`)_

**Что произойдёт:**

1. Выберите режим `1` (Подключение к Edge/Chrome — рекомендуется) или `2` для отдельного браузера.
2. Браузер откроется или подключится; выберите вкладку теста Wayground, когда программа предложит.
3. Авторизуйтесь под своим аккаунтом и перейдите на страницу ожидания теста.
4. Вернитесь в консоль и нажмите **Enter**.
5. Выберите Smart Hybrid, Qwen через Groq, GPT-OSS 120B / 20B, настроенный личный API или отключение ИИ. Программа выполнит пробный запрос и покажет **Available / Unavailable** с причиной. Qwen и GPT-OSS могут использовать встроенный шлюз без личного ключа; настроенный ключ Groq позволяет этим предустановкам обращаться к Groq напрямую.
6. Сначала программа получит ключи текущего теста через API. При неудаче предложит дополнительные источники, включая выбор открытой вкладки CheatNetwork без перезагрузки. Для Quizit Standard нужен отдельный аккаунт; `--no-bot` отключает этот источник.
7. Просмотрите полный список вопросов и укажите количество намеренных ошибок (или нажмите Enter, чтобы их не делать).
8. Автоматизация начнётся!

### Параметры запуска

Можно пропустить интерактивное меню, передав аргументы:

| Параметр                 | Описание                                                | По умолчанию                               |
| ------------------------ | ------------------------------------------------------- | ------------------------------------------ |
| `--ai`                   | Решать тест напрямую через AI Solver (без поиска базы)  | `False`                                    |
| `--ai-provider ENGINE`   | Выбрать `gateway`, `direct`, `groq-120b`, `groq-20b` или `off`; доступность ИИ проверяется перед стартом | Интерактивный выбор |
| `--no-ai`                | Полностью отключить ИИ-солвер и авто-переключение на ИИ | `False`                                    |
| `--ai-key KEY`           | Пользовательский API ключ (Groq / OpenAI)               | Из `.env` / `OPENAI_API_KEY`               |
| `--ai-model MODEL`       | Модель для решения (Groq / OpenAI)                     | `qwen/qwen3.8-27b`                         |
| `--ai-base URL`          | Базовый URL OpenAI-совместимого API                     | `https://api.groq.com/openai/v1`           |
| `--attach`               | Подключиться к Edge/Chrome (автозапуск при нужде)       | `False`                                    |
| `--wrong N`              | Сделать N намеренных ошибок (иначе спросит в меню)      | `0` (запрашивает, если не задано)            |
| `-q, --quiz-input STR`   | PIN игры, хеш комнаты, ID теста или поддерживаемая ссылка | `None`                                  |
| `--no-bot`               | Отключить дополнительный источник Quizit Standard/Bot  | `False`                                    |
| `--port PORT`            | Порт отладки браузера для режима подключения            | `9222`                                     |
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

Программа определяет PIN или хеш комнаты выбранного теста и получает явные ключи через API игры Wayground. Если сервер скрывает ответы, программа ищет исходный тест в публичной библиотеке и проверяет найденный вариант по вопросам игры. Обработчик сетевых ответов выбранной вкладки также получает ключи, которые сервер передаёт браузеру. Каждый вопрос хранится отдельно, даже если формулировки повторяются.

Если прямой поиск не дал результата, можно выбрать открытую вкладку CheatNetwork. Дополнительный источник Quizit Standard может потребовать входа в отдельный аккаунт Quizit. Окна загрузки CheatNetwork ожидаются без автоматической перезагрузки; сообщения об авторизации приостанавливают работу для ручного входа. Существующие вкладки остаются открытыми; после успешного получения ответов программа может закрыть только созданную ею временную вкладку.

#### Решение (Phase 2)

1. Вычисляет время на чтение человеком (`минимум 10 сек + 0.05 сек на символ`).
2. Сопоставляет вопрос по ID или набору вариантов, выбирает правильные кнопки либо заполняет текстовые пропуски.
3. В случае `--wrong` специально кликает на неправильный ответ N раз за весь тест.
4. Учитывает номер вопроса, чтобы последовательные одинаковые формулировки не пропускались. Если ответ отсутствует или неоднозначен, останавливается до отправки. Таймаут ожидания не считается успешным завершением.

### Устранение проблем

<details>
<summary><b>❌ Could not connect on port 9222</b></summary>

**Причина:** Ваш Edge работает в фоне и мешает подключиться к порту отладки.
**Решение:** Нажмите `Ctrl+Shift+Esc` (Диспетчер задач) и завершите все процессы `msedge.exe`. Затем запустите программу снова.

</details>

<details>
<summary><b>❌ Automation stopped at question ...</b></summary>

**Причина:** Нет полного ключа для вопроса, варианты не совпали с найденными ответами либо выбранный ИИ не вернул пригодный результат.
**Решение:** Проверьте выбранную вкладку теста, PIN и источник ответов. При использовании ИИ проверьте его доступность. Загрузите ключи текущего теста и запустите программу снова. Вопрос остаётся неотправленным; случайные ответы не подставляются.

</details>

### Запуск проверок

Из корня проекта с установленными зависимостями Python:

```powershell
python -m unittest discover -s tests
```

Для проверок шлюза дополнительно нужен Node.js:

```powershell
node --test tests/test_gateway.mjs
```

Папку `tests/` следует коммитить вместе с изменениями исходников. В готовый `.exe` эти проверки не включаются.

<p align="center">
  <sub>Built with <a href="https://playwright.dev/python/">Playwright</a> · Python 3.10+</sub>
</p>
