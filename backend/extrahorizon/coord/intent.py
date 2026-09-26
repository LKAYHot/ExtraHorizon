"""Is a chat message about the utility-coordination analysis? (English and Russian.)

Strict on purpose: running the analysis reads the county's data and turns her answer into a report,
so ordinary tutoring questions — "compare the construction of a heap with sorting", "a utility
function in economics", "infrastructure as code" — must never start it. A request names the
utilities (their networks, agencies or the county) AND asks where they overlap, or asks to
compare / find / flag their plans.
"""

from __future__ import annotations

import re
from typing import Any

_UTIL = re.compile(
    r"\b(utilities|utility\s+(?:compan|project|plan|work|construction|network|line|coordination|provider|agenc|"
    r"conflict)\w*|public\s+works|water\s+mains?|sewer\w*|stormwater|storm\s+drains?|gas\s+(?:lines?|mains?)|"
    r"power\s+lines?|road\s?works?|roadway\w*|repaving|paving\s+(?:projects?|work|plans?)|wasd|fdot|dtpw|"
    r"miami[-\s]?dade|коммунальн\w*|водопровод\w*|канализац\w*|ливн[её]в\w*|газопровод\w*|"
    r"дорожн\w*\s+работ\w*|майами)",
    re.I,
)
_WORK = re.compile(
    r"\b(construction|projects?|plans?|planned|capital|excavat\w*|digging|schedul\w*|строительств\w*|стройк\w*|"
    r"проект\w*|план\w*|раскоп\w*|график\w*)",
    re.I,
)
_ASK = re.compile(
    r"\b(compar\w*|flag\w*|find|show|where|which|analy[sz]\w*|check|list|сравн\w*|найд\w*|найти|покаж\w*|где|"
    r"проанализ\w*|анализ\w*|провер\w*)",
    re.I,
)
_STRONG = re.compile(
    r"\b(overlap\w*|conflict\w*|coordinat\w*|clash\w*|intersect\w*|пересе\w*|конфликт\w*|координ\w*)", re.I)
# follow-ups about the analysis on screen: its findings (not the "F1 score" of machine learning), its map…
_FID = re.compile(r"\b[Ff]\d{1,6}\b(?!\s*-?\s*(?:score|key|racing|car|driver|team)s?\b)")
_ABOUT = re.compile(r"\b(findings?|the map|county|crews?|excavation|trench\w*|right[- ]of[- ]way|находк\w*|"
                    r"карт[аеуы]\b|округ\w*)", re.I)
_RERUN = re.compile(r"\b(again|re-?run|redo|refresh|reload|update|fresh|once more|заново|ещ[её]\s+раз|снова|"
                    r"повтор\w*|обнов\w*|перезапусти\w*)\b", re.I)
_REFRESH = re.compile(r"\b(refresh|reload|update the data|fresh data|обнов\w*|перезагрузи\w*)\b", re.I)


def wants_analysis(text: str) -> bool:
    """A request to run the analysis (when none is on screen)."""
    t = text or ""
    return bool(_UTIL.search(t) and (_STRONG.search(t) or (_WORK.search(t) and _ASK.search(t))))


def wants_rerun(text: str) -> bool:
    """With an analysis on screen: run it again ("compare them again", "обнови анализ")."""
    return bool(_RERUN.search(text or ""))


def wants_refresh(text: str) -> bool:
    """Read the county's data again instead of the cached copy."""
    return bool(_REFRESH.search(text or ""))


def about_analysis(text: str, report: dict[str, Any] | None = None) -> bool:
    """With an analysis on screen: is this message about it? (Otherwise she simply tutors.)"""
    from .refs import finding_ids

    t = text or ""
    if _FID.search(t) or _UTIL.search(t) or _STRONG.search(t) or _ABOUT.search(t) or finding_ids(t):
        return True  # (finding_ids: also spoken — "что на F сто сорок шесть?")
    if report:
        words = set(re.findall(r"[\w.-]{4,}", t))
        return any(p.get("project_id") in words for p in report.get("projects_index", ()))
    return False
