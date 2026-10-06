"""Cooperative desktop controls shared with the existing async automation loop."""

import asyncio
from contextvars import ContextVar
import random
import time
import threading

from config import MIN_THINK_SECONDS, THINK_PER_CHAR, THINK_JITTER


ACTIVE_CONTROL = ContextVar("wayground_runtime_control", default=None)
ACTIVE_CANCELLATION = ContextVar("wayground_network_cancellation", default=None)


class RunStopped(asyncio.CancelledError):
    """Cancellation which cannot be swallowed by legacy browser exception handlers."""


class SessionChanged(RunStopped):
    pass


def network_checkpoint():
    event = ACTIVE_CANCELLATION.get()
    if event is not None and event.is_set():
        raise RunStopped("The operation was cancelled before the next network request.")


def question_delay_seconds(question_text, minimum=MIN_THINK_SECONDS, *, jitter=None):
    """Use the original question-length timing with a configurable lower bound."""
    minimum = max(0.0, float(minimum))
    length = len(question_text) if question_text else 25
    base = minimum + length * THINK_PER_CHAR
    variation = random.uniform(-THINK_JITTER, THINK_JITTER) if jitter is None else jitter
    return max(minimum, round(base * (1.0 + variation), 1))


class RuntimeControl:
    """All methods run on the browser worker's event loop, never on the Qt thread."""

    def __init__(self, emit, *, guard=None, delay=MIN_THINK_SECONDS, wrong_limit=0,
                 highlight=True, apply_engine=None):
        self.emit_callback = emit
        self.guard = guard
        self.apply_engine = apply_engine
        self.delay = max(0.0, float(delay))
        self.wrong_limit = max(0, int(wrong_limit))
        self.highlight = bool(highlight)
        self.paused = False
        self.stopped = False
        self.cancellation = threading.Event()
        self.wrong_used = 0
        self.phase = "reading"
        self.question = {}
        self.question_guard = None
        self.correct_answers = []
        self.wrong_answers = []
        self.can_wrong = False
        self.verified = False
        self.deliberate = False
        self._step_requested = False
        self._step_transaction = False
        self._guard_at = 0.0
        self._last_submitted_key = ""
        self._engine_pending = None
        self._question_jitter = 0.0

    @property
    def question_delay(self):
        # Zero is the explicit no-wait setting; Answer now also bypasses waiting.
        if self.delay <= 0:
            return 0.0
        return question_delay_seconds(self.question.get("text", ""), self.delay,
                                      jitter=self._question_jitter)

    def emit(self, kind, **data):
        self.emit_callback({"type": kind, **data})

    def pause(self, paused):
        self.paused = bool(paused)
        self.emit("paused", paused=self.paused)

    def stop(self):
        self.stopped = True
        self.cancellation.set()

    def answer_now(self):
        if self.phase in ("waiting", "submitting"):
            self._step_requested = True

    def toggle_wrong(self):
        if self.phase != "waiting" or not self.can_wrong or self.wrong_used >= self.wrong_limit:
            return False
        self.deliberate = not self.deliberate
        self._publish_answer()
        return True

    def set_wrong_limit(self, value):
        self.wrong_limit = max(0, int(value))
        if self.wrong_used >= self.wrong_limit and self.phase != "submitting":
            self.deliberate = False
        self.emit("settings", wrong_limit=self.wrong_limit, wrong_used=self.wrong_used)
        if self.phase == "waiting":
            self._publish_answer()

    def queue_engine(self, settings):
        self._engine_pending = settings

    def use_pending_engine(self):
        if self._engine_pending is not None and self.apply_engine:
            settings, self._engine_pending = self._engine_pending, None
            self.apply_engine(settings)

    async def checkpoint(self, *, action=False):
        while self.paused and not self._step_requested and not self._step_transaction:
            await self._check_guard()
            await asyncio.sleep(0.05)
        await self._check_guard(force=action)
        if action:
            if self._step_requested:
                self._step_requested = False
                self._step_transaction = True
            if self.question_guard and not await self.question_guard():
                self.emit("status", message="The question changed. Reading the current question.")
                return False
        return True

    async def _check_guard(self, *, force=False):
        if self.stopped:
            raise RunStopped("Automation stopped before the next browser action.")
        now = time.monotonic()
        if self.guard and (force or now - self._guard_at >= 0.5):
            await self.guard()
            self._guard_at = now

    def begin_question(self, *, key, number, total, text, question_guard=None):
        self.question = {"key": key, "number": number, "total": total, "text": text}
        self._question_jitter = random.uniform(-THINK_JITTER, THINK_JITTER)
        self.question_guard = question_guard
        self.phase = "reading"
        self._step_requested = False
        self._step_transaction = False
        self.deliberate = False
        self.can_wrong = False
        self.verified = False
        self.emit("question", **self.question, submitted=max(0, number - 1),
                  wrong_used=self.wrong_used, wrong_limit=self.wrong_limit)

    def _publish_answer(self):
        preview = self.wrong_answers if self.deliberate else self.correct_answers
        self.emit("answer", answers=preview, correct_answers=self.correct_answers,
                  can_wrong=self.can_wrong and self.wrong_used < self.wrong_limit,
                  deliberate=self.deliberate, phase=self.phase)

    async def before_submit(self, correct_answers, *, source, verified,
                            wrong_answers=None, latency=None):
        self.phase = "waiting"
        self.correct_answers = list(correct_answers)
        self.verified = bool(verified)
        self.wrong_answers = list(wrong_answers or [])
        self.can_wrong = bool(verified and self.wrong_answers)
        remaining = max(1, self.question.get("total", 0) - self.question.get("number", 1) + 1)
        needed = max(0, self.wrong_limit - self.wrong_used)
        self.deliberate = self.can_wrong and needed > 0 and random.random() < min(1, needed / remaining)
        self.emit("resolved", source=source, verified=verified, latency=latency)
        self._publish_answer()
        elapsed = 0.0
        while elapsed < self.question_delay or self.paused:
            await self._check_guard()
            if self._step_requested:
                self._step_requested = False
                self._step_transaction = True
                break
            if not self.paused:
                self.emit("countdown", remaining=round(max(0.0, self.question_delay - elapsed), 1))
            start = time.monotonic()
            await asyncio.sleep(0.05)
            if not self.paused:
                elapsed += time.monotonic() - start
        if not await self.checkpoint(action=True):
            return None
        self.phase = "submitting"
        self.deliberate = self.deliberate and self.can_wrong and self.wrong_used < self.wrong_limit
        self.emit("submitting", deliberate=self.deliberate)
        return self.deliberate

    def submitted(self):
        key = self.question.get("key", "")
        if key and key == self._last_submitted_key:
            return
        self._last_submitted_key = key
        if self.deliberate:
            self.wrong_used += 1
        self.phase = "transition"
        self.question_guard = None
        self.emit("submitted", number=self.question.get("number", 0),
                  total=self.question.get("total", 0), wrong_used=self.wrong_used,
                  wrong_limit=self.wrong_limit)
        self._step_transaction = False
        self._step_requested = False

    def manual_required(self):
        self.phase = "manual"
        self.can_wrong = False
        self.emit("manual", **self.question,
                  message="Enter and submit your own written response in the test tab.")


async def checkpoint(*, action=False):
    control = ACTIVE_CONTROL.get()
    return await control.checkpoint(action=action) if control else True
