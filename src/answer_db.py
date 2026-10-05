"""Keep question occurrences separate from their optional lookup aliases."""

from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class AnswerQuestion:
    qid: str
    text: str
    answers: list[str]
    images: list[str] = field(default_factory=list)
    options: list[dict] = field(default_factory=list)


class AnswerDatabase(dict[str, list[str]]):
    """Dictionary-compatible keys with one ordered record per question ID/row."""

    def __init__(self):
        super().__init__()
        self.questions: dict[str, AnswerQuestion] = {}

    def __bool__(self):
        return bool(self.questions) or len(self) > 0

    def add_question(self, text, answers, *, qid="", images=None, options=None):
        record = AnswerQuestion(str(qid or ""), text, list(answers),
                                list(images or []), list(options or []))
        key = f"id:{record.qid}" if record.qid else f"row:{len(self.questions)}"
        self.questions[key] = record
        self._rebuild_aliases()

    def _rebuild_aliases(self):
        self.clear()
        ambiguous = set()

        def alias(key, answers):
            if key in ambiguous:
                return
            if key in self and self[key] != answers:
                self.pop(key)
                ambiguous.add(key)
            else:
                self[key] = list(answers)

        for question in self.questions.values():
            if question.text:
                alias(question.text, question.answers)
            for image in question.images:
                filename = urlparse(image).path.rsplit("/", 1)[-1]
                if filename:
                    alias(f"img:{filename}", question.answers)
            if question.qid:
                self[question.qid] = list(question.answers)
                self[f"id:{question.qid}"] = list(question.answers)

    def update(self, other=(), **kwargs):
        if other is self:
            if kwargs:
                super().update(kwargs)
            return
        if isinstance(other, AnswerDatabase):
            for question in other.questions.values():
                self.add_question(question.text, question.answers, qid=question.qid,
                                  images=question.images, options=question.options)
        else:
            super().update(other)
        if kwargs:
            super().update(kwargs)
