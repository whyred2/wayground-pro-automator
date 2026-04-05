<p align="center">
  <h1 align="center">🚀 Wayground Pro Automator</h1>
  <p align="center">
    Automated test-taking on <b>wayground.com</b> powered by answer keys from <b>cheatnetwork.eu</b>
    <br />
    <a href="#-english">English</a> · <a href="#-русский">Русский</a>
  </p>
</p>

---

## ⚠️ Disclaimer / Отказ от ответственности

> **EN:** This tool is for educational and research purposes only. The developers are not responsible for any misuse or violations of terms of service of the target platforms.

> **RU:** Данный инструмент создан исключительно в образовательных и ознакомительных целях. Разработчики не несут ответственности за любое нарушение правил использования сторонних платформ.

---

## 🇬🇧 English

### Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Operating Modes](#operating-modes)
- [CLI Parameters](#cli-parameters)
- [How It Works](#how-it-works)
- [Question Types](#question-types)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)

### Features

- **Dual-mode operation** — launch a new browser or attach to an existing Edge/Chrome session
- **Session persistence** — in `--attach` mode, your logins and cookies are preserved across runs
- **Multi-select (MSQ) support** — handles questions with multiple correct answers
- **Human-like behavior** — dynamic delays based on question length (min 8 sec), random jitter ±30%
- **Intentional errors** — configurable `--wrong N` to avoid a perfect 100% score
- **Fuzzy matching** — Levenshtein-based answer matching (80% threshold) for minor text differences
- **Visual feedback** — highlighted questions (yellow) and answers (green) for real-time monitoring
- **Tab picker with confirmation** — select tabs from a list, confirm or re-pick if needed

### Installation

**Prerequisites:** Python 3.10+, pip

```powershell
# 1. Install dependencies
pip install -r requirements.txt

# 2. Install Chromium browser for Playwright
python -m playwright install chromium
```

### Quick Start

#### Recommended: `--attach` mode

The most convenient way to use the tool. Connects to your Edge browser, preserving all sessions.

```powershell
# Close ALL Edge windows first (required on first run only), then:
python main.py --attach
```

**What happens:**

1. The script auto-detects `msedge.exe` on your system
2. Launches Edge with a debug port using **your existing profile** (logins preserved)
3. Opens the answer key page and Wayground
4. Prompts you to log in and navigate to the test page
5. After pressing Enter — automation begins

#### Subsequent runs (Edge already open)

```powershell
python main.py --attach
```

The script detects that Edge is already running → shows a list of open tabs → you pick the right ones → automation starts immediately.

### Operating Modes

#### 1. `--attach` (recommended) ⭐

Connects to your Edge/Chrome instance. Logins and cookies persist between runs.

```powershell
python main.py --attach
```

| Advantage                                        |
| ------------------------------------------------ |
| ✅ Preserves logins — no need to re-authenticate |
| ✅ Browser stays open after completion           |
| ✅ Script can be re-run multiple times           |
| ✅ Auto-detects Edge/Chrome executable           |
| ✅ Interactive tab selection with confirmation   |

> **First run:** Close all Edge windows. The script will relaunch Edge with the debug port. You may need to log in once.
>
> **Subsequent runs:** Edge is already running — the script connects instantly.

#### 2. Normal mode (without `--attach`)

Launches a standalone Playwright browser. Requires login every time.

```powershell
python main.py --test-url "https://wayground.com/join?gc=XXXXXX"
```

- Separate browser (does not share cookies with Edge)
- Login required each session
- Browser closes after completion

### CLI Parameters

| Parameter           | Description                                   | Default                                    |
| ------------------- | --------------------------------------------- | ------------------------------------------ |
| `--attach`          | Attach to Edge/Chrome (auto-launch if needed) | `False`                                    |
| `--wrong N`         | Number of intentionally wrong answers         | `0`                                        |
| `--test-url URL`    | URL of the test page                          | `https://wayground.com`                    |
| `--answers-url URL` | URL of the answer key page                    | `https://cheatnetwork.eu/services/quizizz` |
| `--port N`          | CDP port for `--attach` mode                  | `9222`                                     |

#### Examples

```powershell
# All correct
python main.py --attach

# 6 wrong answers (~94% on 100 questions)
python main.py --attach --wrong 6

# 12 wrong answers (~87%)
python main.py --attach --wrong 12

# Specific test URL (normal mode)
python main.py --test-url "https://wayground.com/join?gc=XXXXXX"

# Custom CDP port
python main.py --attach --port 9333
```

### How It Works

#### Phase 1: Answer Scraping

1. Opens `cheatnetwork.eu/services/quizizz`
2. Waits for `.question-box` elements to load
3. Scrolls down to trigger lazy-loading of all questions
4. Extracts **Question → Answer(s)** pairs
5. Prints a summary table in the console

#### Phase 2: Test Automation

1. Detects the current question (`#questionText`)
2. Matches it against the answer database:
   - **Exact** match (case-insensitive)
   - **Substring** match
   - **Fuzzy** match (Levenshtein, 80% threshold)
3. Simulates "thinking" — delay based on question length:
   - Minimum **8 seconds**
   - +0.05 sec per character
   - ±30% random jitter
4. Highlights question (yellow border) and answer (green border)
5. Clicks the answer and moves to the next question

#### Thinking Time Reference

| Question Length    | Approximate Delay |
| ------------------ | ----------------- |
| Short (~30 chars)  | 8–10 sec          |
| Medium (~80 chars) | 9–15 sec          |
| Long (~200 chars)  | 13–24 sec         |

### Question Types

| Type                   | Behavior                                                                         |
| ---------------------- | -------------------------------------------------------------------------------- |
| **Single choice**      | Clicks one correct answer → auto-advances                                        |
| **Multi-select (MSQ)** | Clicks all correct answers with delays → clicks **Submit** button                |
| **Intentional wrong**  | `--wrong N` randomly distributes N wrong answers; for MSQ — picks a wrong option |

### Configuration

Adjustable constants at the top of `main.py`:

```python
MIN_THINK_SECONDS = 8.0     # Minimum delay (seconds)
THINK_PER_CHAR = 0.05       # Additional seconds per character
THINK_JITTER = 0.30         # ±30% random variation
CLICK_DELAY_MS = 300        # Post-click delay (ms)
```

### Troubleshooting

<details>
<summary><b>❌ No .question-box elements found</b></summary>

**Cause:** CheatNetwork page didn't load or its structure changed.

**Solution:**

- Ensure the answer tab is open and fully loaded
- Verify the URL: `https://cheatnetwork.eu/services/quizizz`
- If the page requires input (quiz ID), do it manually before pressing Enter
</details>

<details>
<summary><b>❌ Could not connect on port 9222</b></summary>

**Cause:** Edge is not running or is running without the debug port.

**Solution:**

1. Close **all** Edge windows (check via `Ctrl+Shift+Esc`)
2. Re-run: `python main.py --attach`
</details>

<details>
<summary><b>❌ Target page has been closed</b></summary>

**Cause:** A tab was closed while the script was running.

**Solution:** Do not close tabs during automation. Restart the script.

</details>

<details>
<summary><b>❌ Match not found for Q: "..."</b></summary>

**Cause:** The question on the test was not found in the answer database.

**Solution:**

- Ensure the correct quiz is loaded on CheatNetwork
- Check the screenshot: `error_debug.png`
- The question text may differ slightly — consider lowering the fuzzy threshold in the code
</details>

---

## 🇷🇺 Русский

### Содержание

- [Возможности](#возможности)
- [Установка](#установка)
- [Быстрый старт](#быстрый-старт)
- [Режимы работы](#режимы-работы)
- [Параметры запуска](#параметры-запуска)
- [Как это работает](#как-это-работает)
- [Типы вопросов](#типы-вопросов)
- [Настройка](#настройка)
- [Устранение проблем](#устранение-проблем)

### Возможности

- **Два режима работы** — запуск нового браузера или подключение к уже открытому Edge/Chrome
- **Сохранение сессий** — в режиме `--attach` ваши логины и куки сохраняются между запусками
- **Поддержка MSQ** — корректная обработка вопросов с множественным выбором
- **Имитация человека** — динамические задержки на основе длины вопроса (мин. 8 сек), jitter ±30%
- **Намеренные ошибки** — параметр `--wrong N` для получения результата ниже 100%
- **Нечёткий поиск** — сопоставление ответов по алгоритму Левенштейна (порог 80%)
- **Визуальная обратная связь** — подсветка вопросов (жёлтая рамка) и ответов (зелёная рамка)
- **Выбор вкладок с подтверждением** — возможность перевыбрать вкладки, если допущена ошибка

### Установка

**Требования:** Python 3.10+, pip

```powershell
# 1. Установите зависимости
pip install -r requirements.txt

# 2. Установите браузер Chromium для Playwright
python -m playwright install chromium
```

> **Примечание:** Используйте `python -m playwright install`, а не `playwright install` — на Windows команда может не добавиться в PATH.

### Быстрый старт

#### Рекомендуемый способ: режим `--attach`

Наиболее удобный режим — подключение к вашему браузеру Edge. Все логины и куки сохраняются.

```powershell
# Закройте ВСЕ окна Edge (обязательно при первом запуске), затем:
python main.py --attach
```

**Что произойдёт:**

1. Скрипт автоматически найдёт `msedge.exe` на вашем диске
2. Запустит Edge с debug-портом, используя **ваш профиль** (логины сохранены)
3. Откроет страницу с ответами и Wayground
4. Предложит вам войти в аккаунт и перейти на страницу теста
5. После нажатия Enter — начнётся автоматизация

#### Повторный запуск (Edge уже открыт)

```powershell
python main.py --attach
```

Скрипт обнаружит, что Edge уже запущен → покажет список открытых вкладок → вы выберете нужные → автоматизация начнётся.

### Режимы работы

#### 1. `--attach` (рекомендуется) ⭐

Подключается к вашему Edge/Chrome. Логины и куки сохраняются между запусками.

```powershell
python main.py --attach
```

| Преимущество                                      |
| ------------------------------------------------- |
| ✅ Сохраняет логины — не нужно входить каждый раз |
| ✅ Браузер не закрывается после завершения        |
| ✅ Можно перезапускать скрипт многократно         |
| ✅ Автоматически находит Edge/Chrome на диске     |
| ✅ Интерактивный выбор вкладок с подтверждением   |

> **Первый запуск:** Закройте все окна Edge. Скрипт перезапустит Edge с debug-портом. Возможно, потребуется войти в аккаунт один раз.
>
> **Повторный запуск:** Edge уже открыт — скрипт подключается моментально.

#### 2. Обычный режим (без `--attach`)

Открывает новый браузер Playwright. Требуется вход в аккаунт при каждом запуске.

```powershell
python main.py --test-url "https://wayground.com/join?gc=XXXXXX"
```

- Отдельный браузер (не использует куки Edge)
- Каждый раз — новый вход в аккаунт
- Браузер закрывается после завершения

### Параметры запуска

| Параметр            | Описание                                            | По умолчанию                               |
| ------------------- | --------------------------------------------------- | ------------------------------------------ |
| `--attach`          | Подключиться к Edge/Chrome (авто-запуск при необх.) | `False`                                    |
| `--wrong N`         | Количество намеренно неправильных ответов           | `0`                                        |
| `--test-url URL`    | URL страницы теста                                  | `https://wayground.com`                    |
| `--answers-url URL` | URL страницы с ответами                             | `https://cheatnetwork.eu/services/quizizz` |
| `--port N`          | CDP-порт для режима `--attach`                      | `9222`                                     |

#### Примеры

```powershell
# Все ответы правильные
python main.py --attach

# 6 неправильных ответов (~94% на 100 вопросов)
python main.py --attach --wrong 6

# 12 неправильных (~87%)
python main.py --attach --wrong 12

# С конкретным URL теста (обычный режим)
python main.py --test-url "https://wayground.com/join?gc=XXXXXX"

# Нестандартный порт
python main.py --attach --port 9333
```

### Как это работает

#### Фаза 1: Парсинг ответов

1. Открывает `cheatnetwork.eu/services/quizizz`
2. Ожидает загрузки элементов `.question-box`
3. Прокручивает страницу для подгрузки всех вопросов (lazy-loading)
4. Извлекает пары **Вопрос → Ответ(ы)**
5. Выводит сводную таблицу в консоль

#### Фаза 2: Автоматизация теста

1. Определяет текущий вопрос (`#questionText`)
2. Ищет совпадение в базе ответов:
   - **Точное** совпадение (без учёта регистра)
   - **Частичное** совпадение (подстрока)
   - **Нечёткое** совпадение (алгоритм Левенштейна, порог 80%)
3. Имитирует «раздумье» — задержка зависит от длины вопроса:
   - Минимум **8 секунд**
   - +0,05 сек за каждый символ
   - ±30% случайное отклонение
4. Подсвечивает вопрос (жёлтая рамка) и ответ (зелёная рамка)
5. Кликает на ответ и переходит к следующему вопросу

#### Время «раздумий»

| Длина вопроса           | Примерное время |
| ----------------------- | --------------- |
| Короткий (~30 символов) | 8–10 сек        |
| Средний (~80 символов)  | 9–15 сек        |
| Длинный (~200 символов) | 13–24 сек       |

### Типы вопросов

| Тип                           | Поведение                                                                           |
| ----------------------------- | ----------------------------------------------------------------------------------- |
| **Одиночный выбор**           | Кликает один правильный вариант → автопереход                                       |
| **Множественный выбор (MSQ)** | Кликает все правильные варианты с паузами → нажимает кнопку **«Отправить»**         |
| **Намеренные ошибки**         | `--wrong N` случайно распределяет N ошибок; для MSQ — выбирает неправильный вариант |

### Настройка

Настраиваемые константы в начале файла `main.py`:

```python
MIN_THINK_SECONDS = 8.0     # Минимальная задержка (секунды)
THINK_PER_CHAR = 0.05       # Дополнительные секунды за символ
THINK_JITTER = 0.30         # ±30% случайное отклонение
CLICK_DELAY_MS = 300        # Задержка после клика (мс)
```

### Устранение проблем

<details>
<summary><b>❌ No .question-box elements found</b></summary>

**Причина:** Страница CheatNetwork не загрузилась или изменила структуру.

**Решение:**

- Убедитесь, что вкладка с ответами открыта и полностью загружена
- Проверьте URL: `https://cheatnetwork.eu/services/quizizz`
- Если страница требует ввода данных (ID квиза) — сделайте это вручную до нажатия Enter
</details>

<details>
<summary><b>❌ Could not connect on port 9222</b></summary>

**Причина:** Edge не запущен или работает без debug-порта.

**Решение:**

1. Закройте **все** окна Edge (проверьте через `Ctrl+Shift+Esc`)
2. Перезапустите скрипт: `python main.py --attach`
</details>

<details>
<summary><b>❌ Target page has been closed</b></summary>

**Причина:** Вкладка была закрыта во время работы скрипта.

**Решение:** Не закрывайте вкладки во время автоматизации. Перезапустите скрипт.

</details>

<details>
<summary><b>❌ Match not found for Q: "..."</b></summary>

**Причина:** Вопрос теста не найден в базе ответов.

**Решение:**

- Убедитесь, что открыт правильный тест на CheatNetwork
- Проверьте скриншот `error_debug.png`
- Текст вопроса может немного отличаться — попробуйте снизить порог нечёткого поиска в коде
</details>

<details>
<summary><b>❌ Submit button not found</b></summary>

**Причина:** MSQ-вопрос, но кнопка «Отправить» не обнаружена.

**Решение:** Проверьте селектор `SEL_SUBMIT_BUTTON` — структура страницы могла измениться.

</details>

---

## 📁 Project Structure / Структура проекта

```
quizizz/
├── main.py              # Core automation script / Основной скрипт
├── requirements.txt     # Python dependencies / Зависимости
├── README.md            # Documentation / Документация
└── error_debug.png      # Auto-generated debug screenshot / Скриншот при ошибке
```

---

<p align="center">
  <sub>Built with <a href="https://playwright.dev/python/">Playwright</a> · Python 3.10+</sub>
</p>
