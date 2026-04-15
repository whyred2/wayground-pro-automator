<p align="center">
  <img src="assets/logo.png" alt="Wayground Pro Automator Logo" width="100" height="100">
</p>

<p align="center">
  <h1 align="center">🚀 Wayground Pro Automator v2.1</h1>
  <p align="center">
    Automated test-taking on <b>wayground.com</b> with Direct API Interception & Lazy CheatNetwork Fallback
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

- [What's New in v2.1](#whats-new-in-v21)
- [Features](#features)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Parameters](#cli-parameters)
- [How It Works](#how-it-works)

### What's New in v2.1

- **Lazy CheatNetwork Fallback** — The CheatNetwork tab is no longer opened at startup. It only opens on-demand if the Direct API fails, and closes automatically after scraping.
- **Smart Wrong-Answer Prompt** — The `--wrong N` setting is now asked _after_ answers are loaded, so you can see the total number of questions before deciding.
- **Modular Codebase** — The monolithic `main.py` (~1400 lines) has been split into 9 focused modules for better maintainability and readability.
- **New Default Mode** — "New standalone browser" is now the recommended default (Option 1). Attach mode is still available as Option 2.

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
├── config.py        # Constants, selectors, timing, colors
├── ui.py            # Logging, Spinner, banners
├── browser.py       # Edge/Chrome detection & launch
├── api.py           # Network interception, Wayground API
├── scraper.py       # CheatNetwork parsing (lazy fallback)
├── matching.py      # Exact / substring / fuzzy matching
├── automation.py    # Test automation loop, highlights, results
└── tabs.py          # Tab picker (attach mode)
```

### Installation

#### Option 1: Using the Standalone `.exe` (Easy)

If you have the compiled `WaygroundAutomator.exe`, no installation is required! Just double click it or run it from CMD.

#### Option 2: Running from Python Source

**Prerequisites:** Python 3.10+, pip

```powershell
# 1. Install dependencies
pip install -r requirements.txt

# 2. Install Chromium browser for Playwright
python -m playwright install chromium
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

| Parameter           | Description                                   | Default                                    |
| ------------------- | --------------------------------------------- | ------------------------------------------ |
| `--attach`          | Attach to Edge/Chrome (auto-launch if needed) | `False`                                    |
| `--wrong N`         | Number of intentionally wrong answers         | `0` (asks interactively if not set)        |
| `--test-url URL`    | URL of the test page (for normal mode)        | `https://wayground.com`                    |
| `--answers-url URL` | URL of the answer key page (for fallback)     | `https://cheatnetwork.eu/services/quizizz` |

**Examples:**

```powershell
# Interactive menu (recommended)
python src/main.py

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

- [Что нового в v2.1](#что-нового-в-v21)
- [Возможности](#возможности)
- [Структура проекта](#структура-проекта)
- [Установка](#установка)
- [Быстрый старт](#быстрый-старт)
- [Параметры запуска](#параметры-запуска)
- [Как это работает](#как-это-работает)
- [Устранение проблем](#устранение-проблем)

### Что нового в v2.1

- **Ленивый CheatNetwork** — Вкладка CheatNetwork больше не открывается при запуске. Она создаётся только если прямой API не вернул ответы, и автоматически закрывается после парсинга.
- **Умный выбор ошибок** — Количество неправильных ответов (`--wrong`) теперь запрашивается _после_ загрузки ответов, когда вы уже видите общее число вопросов.
- **Модульная архитектура** — Монолитный `main.py` (~1400 строк) разбит на 9 модулей для удобства поддержки и чтения кода.
- **Новый режим по умолчанию** — «Новый браузер» теперь рекомендуемый режим (Опция 1). Attach-режим доступен как Опция 2.

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

#### Способ 1: Использование `.exe` (Самый простой)

Если у вас есть скомпилированный `WaygroundAutomator.exe`, установка не требуется! Просто запустите его.

#### Способ 2: Запуск из исходников Python

**Требования:** Python 3.10+, pip

```powershell
# 1. Загрузите библиотеки
pip install -r requirements.txt

# 2. Установите браузер Chromium для Playwright
python -m playwright install chromium
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

| Параметр    | Описание                                              |
| ----------- | ----------------------------------------------------- |
| `--attach`  | Подключиться к Edge/Chrome напрямую                   |
| `--wrong N` | Сделать N специальных ошибок (иначе спросит в конце)  |

**Примеры:**

```powershell
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
