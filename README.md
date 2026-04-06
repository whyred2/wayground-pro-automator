<p align="center">
  <h1 align="center">🚀 Wayground Pro Automator v2.0</h1>
  <p align="center">
    Automated test-taking on <b>wayground.com</b> with Direct API Interception & CheatNetwork Fallback
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
- [CLI Parameters](#cli-parameters)
- [How It Works](#how-it-works)
- [Configuration](#configuration)

### Features

- **Hybrid Answer Engine (v2.0)** — Intercepts the Wayground API in the background for 100% accurate answers instantly. If that fails, auto-falls back to scraping `cheatnetwork.eu`.
- **Smart Image-Variant Handling** — Automatically groups answers for graphically distinct questions with identical text to maximize accuracy. 
- **Graceful Fallbacks** — If a question's options change entirely, the script intelligently selects a random choice instead of crashing.
- **Dual-mode operation** — Launch a new browser or attach to your existing Edge/Chrome session (preserves logins).
- **Human-like behavior** — Dynamic "thinking" delays based on character count, randomized click logic, and jitter ±30%.
- **Intentional errors** — Pass `--wrong N` to answer incorrectly on purpose and avoid a suspicious 100% score.
- **Clean UI** — A fully revamped terminal UI with minimal spam, dynamic animated spinners, and clear testing phases.

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

The most convenient way to use the tool is interactive `--attach` mode (Option 1 when run). This connects to your everyday Edge browser, keeping your accounts logged in.

```powershell
# Close ALL Edge windows first (required on first run only), then:
python main.py
```
*(Or just run the `.exe` file)*

**What happens:**
1. Select Mode `1` (Attach).
2. The script auto-detects `msedge.exe` and launches it with a debug port.
3. It opens Wayground.
4. Log into your account and navigate to the test waiting room.
5. Go back to the console and press **Enter**.
6. The script will intercept the test API as it loads. Automation begins automatically!

### CLI Parameters

You can skip the interactive menu by providing arguments directly:

| Parameter           | Description                                   | Default                                    |
| ------------------- | --------------------------------------------- | ------------------------------------------ |
| `--attach`          | Attach to Edge/Chrome (auto-launch if needed) | `False`                                    |
| `--wrong N`         | Number of intentionally wrong answers         | `0`                                        |
| `--test-url URL`    | URL of the test page (for normal mode)        | `https://wayground.com`                    |
| `--answers-url URL` | URL of the answer key page (for fallback)     | `https://cheatnetwork.eu/services/quizizz` |

**Examples:**
```powershell
# Interactive menu
python main.py

# Auto-start attach mode with 5 intentionally wrong answers
python main.py --attach --wrong 5
```

### How It Works

#### Phase 1: Retrieving Answer Keys
The script attaches a stealth listener to the browser's network layer. When you join the test, it instantly extracts the secret `quiz_id` from the hidden `/join` payload. It then queries the direct Wayground REST API for a 100% exact copy of the correct answers. 
*If you refresh the page or network interception fails, it gracefully falls back to scraping CheatNetwork visually.*

#### Phase 2: Test Automation
The script reads the screen and matches the prompt.
1. Computes a human-like read time (`min 8s + 0.05s/char`).
2. Highlights the screen elements being processed.
3. Solves Single-Select and Multi-Select (MSQ) questions.
4. Injects deliberate failures if `--wrong` was requested.

---

## 🇷🇺 Русский

### Содержание

- [Возможности](#возможности)
- [Установка](#установка)
- [Быстрый старт](#быстрый-старт)
- [Параметры запуска](#параметры-запуска)
- [Как это работает](#как-это-работает)
- [Устранение проблем](#устранение-проблем)

### Возможности

- **Гибридный движок (v2.0)** — Скрипт перехватывает сетевой трафик (Wayground API) в фоне и достаёт 100% точные ответы за долю секунды. При неудаче (например, рефреш страницы) автоматически переключается на веб-парсинг CheatNetwork.
- **Умная обработка картинок** — Аккумулирует и группирует варианты ответов для вопросов с одинаковым текстом, но разными картинками.
- **Не падает при ошибках (Graceful Fallback)** — Если варианты ответов в тесте мутировали до неузнаваемости, скрипт не крашится, а делает "умную" случайную догадку и идёт дальше.
- **Режим `--attach`** — Подключается к вашему текущему браузеру Edge/Chrome (ваши логины и пароли сохраняются).
- **Имитация человека** — Динамические задержки на чтение (в зависимости от длины текста), хаотичные движения и jitter.
- **Намеренные ошибки** — Параметр `--wrong N` позволяет сделать ровно N ошибок, чтобы не вызывать подозрений идеальным 100% результатом.
- **Чистый интерфейс консоли** — Анимированные загрузки, статусы фаз и аккуратный лог.

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

Самый удобный режим — интерактивный `Attach`.

```powershell
# Закройте ВСЕ окна Edge (обязательно при первом запуске), затем запустите:
python main.py
```
*(Или просто откройте файл `.exe`)*

**Что произойдёт:**
1. Выберите режим `1` (Attach).
2. Скрипт найдёт ваш `msedge.exe` и запустит его с портом для автотестирования.
3. В браузере откроется Wayground.
4. Авторизуйтесь под своим аккаунтом и перейдите на страницу ожидания теста.
5. Вернитесь в консоль и нажмите **Enter**.
6. Как только вы начнете тест, скрипт перехватит API и начнёт решать его сам!

### Параметры запуска

Можно пропустить интерактивное меню, передав аргументы:

| Параметр            | Описание                                          |
| ------------------- | ------------------------------------------------- |
| `--attach`          | Подключиться к Edge/Chrome напрямую               |
| `--wrong N`         | Сделать N специальных ошибок                      |

**Примеры:**
```powershell
# Запуск с 6 специальными ошибками, чтобы результат был ~94% (при 100 вопросах)
python main.py --attach --wrong 6
```

### Как это работает

#### Выгрузка правильных ответов (Phase 1)
Скрипт мониторит вкладку "Network" (Сеть) вашего браузера через протокол отладки. Во время входа в тест ловится скрытый запрос `/join`, из которого достаётся ID теста. Затем напрямую из закрытого API вытаскиваются все правильные ответы. Если запрос упущен, скрипт автоматически откроет вкладку CheatNetwork и спарсит ответы оттуда.

#### Решение (Phase 2)
1. Вычисляет время на чтение человеком (`минимум 8 сек + 0.05 сек на символ`).
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
