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

# ─── Selectors — Test Page (Wayground) ────────────────────────
SEL_CURRENT_QUESTION = "#questionText"
SEL_CURRENT_QUESTION_INNER = ".content-slot p"
SEL_OPTION_BUTTON = "button.option"
SEL_OPTION_TEXT = "#optionText .content-slot p"
SEL_SUBMIT_BUTTON = 'button[data-cy="submit-button"]'

# ─── Selectors — Question Counter (Wayground) ────────────────
SEL_CURRENT_Q_NUM = 'span[data-cy="current-question-number"]'
SEL_TOTAL_Q_NUM = 'span[data-cy="total-question-number"]'

# ─── Selectors — Results Page (Wayground) ─────────────────────
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
