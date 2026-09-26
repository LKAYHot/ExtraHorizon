"""What a question points at: finding IDs and project IDs — typed ("F146", "f-146") or SPOKEN.

Speech-to-text writes numbers as words as often as digits: "F сто сорок шесть", "эф сто тридцать пять",
"F one forty-six", "finding one hundred and three", "находка 12". Missing that is how she once told a
learner that F146 was "not in the summary" while the panel showed it. English and Russian cardinal numbers up
to 9,999 are read, including digit-by-digit ("one four six") and colloquial groups ("one forty-six").

Just as important is what is NOT a finding: a force F = 20 N, f(2), an F grade, the F-16, 70 F — an open analysis
must never pull ordinary tutoring into it — and a number that cannot be read completely ("сто сорок шестой",
"forty-sixth", "one and two") gives no ID rather than a different, valid one.
"""

from __future__ import annotations

import re
from typing import Any

_EN = {
    "zero": (0, 1), "oh": (0, 1), "one": (1, 1), "two": (2, 1), "three": (3, 1), "four": (4, 1), "five": (5, 1),
    "six": (6, 1), "seven": (7, 1), "eight": (8, 1), "nine": (9, 1), "ten": (10, 2), "eleven": (11, 2),
    "twelve": (12, 2), "thirteen": (13, 2), "fourteen": (14, 2), "fifteen": (15, 2), "sixteen": (16, 2),
    "seventeen": (17, 2), "eighteen": (18, 2), "nineteen": (19, 2), "twenty": (20, 3), "thirty": (30, 3),
    "forty": (40, 3), "fourty": (40, 3), "fifty": (50, 3), "sixty": (60, 3), "seventy": (70, 3), "eighty": (80, 3),
    "ninety": (90, 3),
}
_RU = {
    "ноль": (0, 1), "нуль": (0, 1), "один": (1, 1), "одна": (1, 1), "одно": (1, 1), "два": (2, 1), "две": (2, 1),
    "три": (3, 1), "четыре": (4, 1), "пять": (5, 1), "шесть": (6, 1), "семь": (7, 1), "восемь": (8, 1),
    "девять": (9, 1), "десять": (10, 2), "одиннадцать": (11, 2), "двенадцать": (12, 2), "тринадцать": (13, 2),
    "четырнадцать": (14, 2), "пятнадцать": (15, 2), "шестнадцать": (16, 2), "семнадцать": (17, 2),
    "восемнадцать": (18, 2), "девятнадцать": (19, 2), "двадцать": (20, 3), "тридцать": (30, 3), "сорок": (40, 3),
    "пятьдесят": (50, 3), "шестьдесят": (60, 3), "семьдесят": (70, 3), "восемьдесят": (80, 3),
    "девяносто": (90, 3), "сто": (100, 4), "двести": (200, 4), "триста": (300, 4), "четыреста": (400, 4),
    "пятьсот": (500, 4), "шестьсот": (600, 4), "семьсот": (700, 4), "восемьсот": (800, 4), "девятьсот": (900, 4),
}
# order: 1 unit · 2 teen · 3 tens · 4 hundreds — a chunk is built from higher to lower order
_WORDS = {**_EN, **_RU}
_HUNDRED = {"hundred"}
_THOUSAND = {"thousand", "тысяча", "тысячи", "тысяч"}
# a word that looks like part of a number but is not one we read (an ordinal, an inflected form): the number
# is incomplete — no ID at all rather than a truncated, different one ("сто сорок шестой" is not F140)
_NUMBERISH = re.compile(
    r"^(?:\w+th|first|second|third|fifth|eighth|ninth|twelfth|hundredth|thousandth|"
    r"нол|нул|одн|дв|тр[еёиоу]|четыр|четв|пят|шест|сем|восем|восьм|девят|десят|двадцат|тридцат|сорок|ст[аоуе]|"
    r"сот|тысяч|перв|втор|трет)", re.I)

_FINDING = {"f", "ф", "эф", "эфф", "ef", "eff", "finding", "находка", "находку", "находке", "находки", "находкой"}
_PROJECT = {"project", "проект", "проекта", "проекту", "проектом", "проекте"}
_NUMBER = {"number", "no", "num", "#", "номер", "номером", "под"}
# after the number: not a finding ("F1 score", "F-16 fighter", "F two times", a force of "20 N")
_NOT_AFTER = {
    "score", "scores", "key", "keys", "racing", "race", "car", "cars", "driver", "drivers", "team", "teams",
    "measure", "fighter", "fighters", "jet", "jets", "falcon", "times", "time", "degrees", "degree", "percent",
    "n", "kn", "newton", "newtons", "kg", "g", "m", "cm", "mm", "km", "s", "ms", "j", "kj", "w", "kw", "hz", "khz",
    "v", "a", "c", "k", "pa", "kpa", "lb", "lbs", "ft", "метрика", "метрики", "мера", "гонка", "гонки", "болид",
    "раз", "раза", "градусов", "градуса", "ньютон", "ньютонов", "кг", "м", "с", "дж", "вт", "гц",
}
_NOT_BEFORE = {"a", "an", "grade", "got", "get", "gets", "an", "оценка", "оценку", "получил", "получила"}
_TOKEN = re.compile(r"[a-zа-яё]+|\d+|#|№", re.I)
_OK_GAP = re.compile(r"^[\s\-#№.:]*$")  # what may stand between "F" / "number" and the number


def _tokens(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0).lower(), m.start(), m.end()) for m in _TOKEN.finditer(text or "")]


def _number(tokens: list[tuple[str, int, int]], i: int, text: str) -> tuple[int | None, int]:
    """A number starting at ``tokens[i]`` (digits or words) → (value, tokens used); (None, 0) if there is none or it
    cannot be read completely."""
    if i >= len(tokens):
        return None, 0
    if tokens[i][0].isdigit():
        return int(tokens[i][0]), 1
    chunks: list[int] = []  # consecutive chunks ("one" "forty six" → 1, 46 → "146")
    cur, order, used, thousands = 0, 9, 0, 0
    j = i
    while j < len(tokens):
        w = tokens[j][0]
        if j > i and not _OK_GAP.match(text[tokens[j - 1][2]:tokens[j][1]] or " "):
            break  # "one, two" / "one (two)": not one number
        if w == "and" and used and order == 4:
            j += 1  # "one hundred and three" — but "one and two" is two numbers
            continue
        if w in _HUNDRED and used:
            cur, order = max(cur, 1) * 100, 4
        elif w in _THOUSAND and used:
            if chunks:
                return None, 0
            thousands += max(cur, 1) * 1000
            cur, order = 0, 9
        elif w in _WORDS:
            val, o = _WORDS[w]
            if used and (o >= order or (o == 1 and order == 2)):
                chunks.append(cur)  # the same or a higher order again: a new chunk ("one" "four")
                cur = 0
            cur += val
            order = o
        else:
            break
        used += 1
        j += 1
    if not used:
        return None, 0
    if j < len(tokens) and _NUMBERISH.match(tokens[j][0]) and tokens[j][0] not in _WORDS and \
            _OK_GAP.match(text[tokens[j - 1][2]:tokens[j][1]] or " "):
        return None, 0  # "сто сорок шестой", "forty-sixth": we do not guess
    chunks.append(cur)
    if thousands:
        return thousands + sum(chunks), j - i
    if len(chunks) > 1:
        # digit by digit ("one four six", "one oh five") or a digit and a group ("one forty-six") — not "ten five"
        if chunks[0] > 9 or any(c > 99 for c in chunks[1:]):
            return None, 0
        return int("".join(str(c) for c in chunks)), j - i
    return chunks[0], j - i


def finding_ids(text: str) -> list[str]:
    """Finding IDs in a question, in order: "F146", "f-146", "F 146", "F сто сорок шесть", "finding one forty-six"."""
    t = text or ""
    tokens = _tokens(t)
    out: list[str] = []
    for i, (w, s, e) in enumerate(tokens):
        if w not in _FINDING:
            continue
        prev = tokens[i - 1] if i else None
        if prev and (prev[0] in _NOT_BEFORE or (prev[0].isdigit() and re.fullmatch(r"\s*°?\s*", t[prev[2]:s]))):
            continue  # "an F", "got an F", "70 F" / "70°F" (but "F 146, F 12" is two findings)
        j = i + 1
        while j < len(tokens) and tokens[j][0] in _NUMBER:
            j += 1
        if j >= len(tokens) or not _OK_GAP.match(t[e:tokens[j][1]] if j == i + 1 else t[tokens[j - 1][2]:tokens[j][1]]):
            continue  # "F = 20", "f(2)", "F's"
        n, used = _number(tokens, j, t)
        if not used or n is None or not 0 < n < 1_000_000:
            continue
        nxt = tokens[j + used][0] if j + used < len(tokens) else ""
        if nxt in _NOT_AFTER:
            continue
        fid = f"F{n}"
        if fid not in out:
            out.append(fid)
    return out


def project_refs(text: str, report: dict[str, Any] | None) -> list[str]:
    """Project IDs of the analysis named in a question (as written, or a number after "project" / "проект")."""
    if not report:
        return []
    ids = {str(p.get("project_id")) for p in report.get("projects_index", ()) if p.get("project_id")}
    t = text or ""
    found = [w for w in re.findall(r"[\w.-]{4,}", t) if w in ids]
    tokens = _tokens(t)
    for i, (w, _s, _e) in enumerate(tokens):
        if w in _PROJECT:
            j = i + 1
            while j < len(tokens) and tokens[j][0] in _NUMBER:
                j += 1
            n, used = _number(tokens, j, t)
            if used and n is not None and str(n) in ids:
                found.append(str(n))
    return list(dict.fromkeys(found))


def with_ids(text: str) -> str:
    """The question with spoken finding numbers also written as IDs (for the model and the fact sheet)."""
    ids = finding_ids(text)
    typed = set(re.findall(r"\bF\d{1,6}\b", text or ""))
    extra = [i for i in ids if i not in typed]
    return f"{text} [{', '.join(extra)}]" if extra else text
