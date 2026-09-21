"""
Configuration: constants, CSS selectors, timing parameters, and console colors.
"""

import os


def _load_dotenv():
    """Lightweight loader for .env file in project root, avoiding mandatory external dependencies."""
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_file = os.path.join(root_dir, ".env")
    if os.path.isfile(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except Exception:
            pass


_load_dotenv()

# ─── AI Solver (OpenAI / Groq / Qwen / Cloudflare Gateway) ───
AI_API_BASE = os.getenv("OPENAI_API_BASE", os.getenv("AI_API_BASE", "https://api.groq.com/openai/v1"))
AI_API_KEY = os.getenv("OPENAI_API_KEY", os.getenv("AI_API_KEY", os.getenv("GROQ_API_KEY", "")))
AI_MODEL = os.getenv("AI_MODEL", "qwen/qwen3.8-27b")
AI_GATEWAY_URL = os.getenv("AI_GATEWAY_URL", "https://wayground-ai-gateway.dima74181.workers.dev").rstrip("/")
AI_SOLVER_DEFAULT = True

# Legacy Mistral fallback settings
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "ministral-14b-latest")
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

# ─── URLs ──────────────────────────────────────────────────────
ANSWERS_URL = "https://cheatnetwork.eu/services/quizizz"
TEST_URL = "https://wayground.com"

# ─── Selectors — Answer Source (CheatNetwork) ─────────────────
SEL_QUESTION_BOX = ".question-box, [class*='question-box']"
SEL_QUESTION_TEXT = "p.font-semibold, p[class*='font-semibold'], p.break-words, p"
SEL_ANSWER_TEXT = "ul li, ul span, li span"

# ─── Selectors — CheatNetwork Form ────────────────────────────
SEL_CN_INPUT = 'input[placeholder="Enter game pin or link"]'
SEL_CN_SUBMIT = 'button[type="submit"]'

# ─── Selectors — Test Page (Wayground) ────────────────────────
# Comprehensive question container selectors (supporting text, images, media layouts, modern assessment)
SEL_CURRENT_QUESTION = (
    '[data-quesid], [data-testid="quiz-container"], [data-testid="question-container"], '
    '[data-testid="question-scroll-container"], [data-highlight-block="stem"], '
    '#questionText, [data-cy="question-text"], .question-text-color, .screen-question'
)
SEL_QUESTION_MEDIA = '.question-media, .media-container, [data-testid="question-media"], img.resizeable-image'
SEL_CURRENT_QUESTION_INNER = '[data-highlight-block="stem"], .content-slot p, .content-slot, .question-text, p'

# Option button selectors (supporting classic game cards and modern assessment radio/check triggers)
SEL_OPTION_BUTTON = (
    'button.option, .option.is-selectable, [data-cy^="option-"], .option-container button, '
    'button[data-testid^="option-trigger-"], [data-testid^="option-trigger-"], '
    'div[role="radiogroup"] button, div[role="group"] button'
)
SEL_OPTION_TEXT = (
    '[data-highlight-block^="option"], .min-w-0 [data-testid="text-renderer"], '
    '.option-text-inner, .text-container, #optionText .content-slot p, .content-slot, p'
)

# Fill-in-the-blank & open-ended input selectors
SEL_FIB_INPUT = (
    'input[data-testid^="fib-text-input-"], [data-testid^="fib-text-blank-"] input, '
    '[data-testid="fib-segments"] input, input.quizizz-ui-text-input, '
    'input[data-cy="typeahead-input"], input[data-testid="typeahead-input"], '
    'input.text-input, textarea.text-input, input[data-cy="text-input"], '
    'textarea[data-testid="open-ended-input"], [data-testid="open-ended-input"], '
    'input[data-testid="open-ended-input"]'
)
SEL_SUBMIT_BUTTON = (
    'button[data-cy="submit-button"], button[data-testid="submit-button"], '
    'button[data-cy="next-button"], button[data-testid="next-button"], '
    'button[data-testid="navigation-next-button"], button.submit-btn, .submit-button-wrapper button, '
    'button.next-button'
)

# Intermission & action selectors (click if blocking)
SEL_CONTINUE_BUTTON = (
    'button[data-cy="next-button"], button:has-text("Next"), button:has-text("Continue"), '
    'button:has-text("Продолжить"), button:has-text("Далее"), button:has-text("Skip"), '
    'button[data-testid="powerup-button"], button:has-text("Activate")'
)

SEL_REDEMPTION_BUTTON = (
    '.screen-redemption-question-selector button.selector, '
    '.selectors-container button.selector-item, '
    'button[aria-label^="Selector"], .screen-redemption-question-selector button'
)

# ─── Selectors — Question Counter (Wayground) ────────────────
SEL_CURRENT_Q_NUM = 'span[data-cy="current-question-number"]'
SEL_TOTAL_Q_NUM = 'span[data-cy="total-question-number"]'

# ─── Selectors — Results Page (Wayground) ─────────────────────
SEL_RESULTS_CONTAINER = (
    '[data-cy="screen-summary"], .screen-summary, .assessment-mode-summary, '
    'div[data-cy="stat-correct-container"], div[data-cy="game-summary"], '
    'div[data-testid="game-summary"], div[data-testid="summary-container"], div[data-testid="report-summary"], '
    '.game-summary-container, .game-summary, .accuracy-chart-wrapper'
)
SEL_STAT_CORRECT = 'div[data-cy="stat-correct-container"] span'
SEL_STAT_INCORRECT = 'div[data-cy="stat-incorrect-container"] span'
SEL_STAT_AVG_TIME = 'div[data-cy="stat-avg-time-container"] span'
SEL_STAT_STREAK = 'div[data-cy="stat-streak-container"] span'
SEL_ACCURACY_TOOLTIP = '.accuracy-chart-wrapper .show-tooltip .content span'

# ─── Timing ───────────────────────────────────────────────────
MIN_THINK_SECONDS = 10.0    # Minimum "thinking" time before answering
THINK_PER_CHAR = 0.05       # Extra seconds per character of question text
THINK_JITTER = 0.30         # ±30% random variation
CLICK_DELAY_MS = 300

# ─── Console Colors ──────────────────────────────────────────
C_RESET = "\033[0m"
C_GREEN = "\033[92m"
C_RED = "\033[91m"
C_YELLOW = "\033[93m"
C_CYAN = "\033[96m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
