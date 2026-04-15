"""
Answer matching: fuzzy and exact matching of questions to answer keys.
"""


def find_answers(question: str, answers_db: dict[str, list[str]]) -> list[str] | None:
    """
    Find the answer(s) for a given question using multiple matching strategies:
    1. Exact match (case-insensitive, stripped)
    2. Substring / contains match
    3. Fuzzy similarity (Levenshtein-based, threshold 80%)

    Returns a list of correct answer strings, or None if not found.
    """
    q_norm = question.strip().lower()

    # Strategy 1: Exact match
    for key, val in answers_db.items():
        if key.strip().lower() == q_norm:
            return val

    # Strategy 2: Substring match
    for key, val in answers_db.items():
        k = key.strip().lower()
        if k in q_norm or q_norm in k:
            return val

    # Strategy 3: Fuzzy match
    for key, val in answers_db.items():
        if _similarity(key.strip().lower(), q_norm) > 0.80:
            return val

    return None


def _similarity(s1: str, s2: str) -> float:
    """Levenshtein-based similarity ratio (0.0 to 1.0)."""
    longer, shorter = (s1, s2) if len(s1) >= len(s2) else (s2, s1)
    if len(longer) == 0:
        return 1.0
    return (len(longer) - _edit_distance(longer, shorter)) / len(longer)


def _edit_distance(a: str, b: str) -> int:
    """Compute Levenshtein edit distance."""
    if len(a) < len(b):
        return _edit_distance(b, a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(
                prev[j + 1] + 1,      # deletion
                curr[j] + 1,           # insertion
                prev[j] + (0 if ca == cb else 1)  # substitution
            ))
        prev = curr
    return prev[-1]
