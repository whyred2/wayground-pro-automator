"""
Configuration: constants, CSS selectors, timing parameters, and console colors.
"""

# ─── URLs ──────────────────────────────────────────────────────
ANSWERS_URL = "https://cheatnetwork.eu/services/quizizz"
TEST_URL = "https://wayground.com"

# ─── Selectors — Answer Source (CheatNetwork) ─────────────────
SEL_QUESTION_BOX = ".question-box"
SEL_QUESTION_TEXT = "p.font-semibold.text-gray-200"
SEL_ANSWER_TEXT = "ul li span"

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
