# Changelog

[← README](README.md) · [Русский README](README.ru.md)

## Current releases

- [v4.1](docs/releases/v4.1.md) — Personal API settings, API compatibility, answer-explanation navigation and experimental Linux/macOS builds.
- [v4.0](docs/releases/v4.0.md) — Native desktop interface, live controls and session-bound execution.

## Earlier releases — English

These archived notes describe behavior at the time of each release. For current setup and behavior, see the [user guide](docs/usage.md).

### What's New in v3.2.1

- **Search beyond the first results** — When the fast library lookup fails, exact-title search checks additional pages. A matching test beyond the first ten results can now be found automatically; question IDs and content are still verified before keys are accepted.
- **Written responses no longer discard valid keys** — An OPEN question explicitly marked as having no fixed correct answer is retained separately. For example, Technical Writing Quiz now loads 45 verified keys and displays all 46 questions, including one written response.
- **Clear manual-response handling** — The table labels unkeyed written questions, keeps answer-key counts separate from question counts, and stops before filling or submitting them. Enter and submit your own response in the test tab, then run the program again to continue. These questions are not sent to the fill-in-the-blank AI solver.

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

## Предыдущие версии — Русский

Архивные заметки описывают поведение соответствующих версий. Актуальные инструкции доступны в [руководстве пользователя](docs/usage.ru.md).

### Что нового в v3.2.1

- **Поиск за пределами первых результатов** — Если быстрый поиск не дал ключей, программа ищет точное название на дополнительных страницах. Теперь тест за пределами первых десяти результатов может быть найден автоматически; ID и содержимое вопросов по-прежнему проверяются.
- **Письменный вопрос не отменяет найденные ключи** — Вопрос OPEN с явным признаком отсутствия фиксированного правильного ответа сохраняется отдельно. Например, Technical Writing Quiz теперь загружает 45 проверенных ключей и показывает все 46 вопросов, включая один письменный.
- **Понятная остановка для письменного ответа** — Таблица помечает такие вопросы, количество ключей отличается от общего числа вопросов, а программа останавливается до заполнения и отправки. Ответьте самостоятельно во вкладке теста и запустите программу снова для продолжения. Эти вопросы не передаются ИИ-решателю текстовых пропусков.

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
