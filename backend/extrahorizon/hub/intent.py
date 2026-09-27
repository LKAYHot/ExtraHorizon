"""Which messages are for the hackathon hub — strictly, so ordinary tutoring stays tutoring:

* ``unstuck``: the learner hits an error — a pasted traceback or log, a message that IS the error, or an error with a
  failure ("I get TypeError: …", "the build fails: …", "у меня пишет ошибку CORS") — checked FIRST, so "504 Deadline
  Exceeded" or "Could not resolve './teammates.js'" is a roadblock, not the deadline or a teammate. What an error
  MEANS ("what is a TypeError?", "что значит ошибка CORS?") stays tutoring.
* ``team`` / ``mentors``: looking for a teammate, a person for a role, a mentor.
* ``learn``: where to learn something — resources, tutorials, starters (not "explain X").
* ``ship``: the hackathon deadline, time left, the submission (not "how much time does quicksort take").
"""

from __future__ import annotations

import re
from typing import Any

from .signature import STACK

# error codes and exception names: case-sensitive ("Explain" is not an E-code, "api_key" is not an error)
_ERROR_CODE = re.compile(
    r"\b[A-Z]\w*(?:Error|Exception)\b|\bE[A-Z]{3,}\b|\bERR_[A-Z0-9_]+\b|\b[A-Z]{3,}(?:_[A-Z0-9]{2,})+\b|"
    r"\bnpm (?:ERR!|error)|Traceback \(most recent call last\)")
_ERROR_PHRASE = re.compile(
    r"^\s*(?:fatal|error):|\bfailed to (?:compile|resolve|fetch|load|connect|build|start|install)\b|"
    r"\b(?:cannot|could not|couldn'?t|can'?t|unable to) (?:find|resolve|import|connect|load|open|read|locate)\b|"
    r"\bno module named\b|\bmodule not found\b|\bCORS\b|Access-Control-Allow-Origin|\bsegmentation fault\b|"
    r"\bundefined is not\b|\bis not (?:a function|defined|iterable|a constructor)\b|\bhydration failed\b|"
    r"\bpermission denied\b|\bcommand not found\b|\baddress already in use\b|\bout of memory\b|\bbuild failed\b|"
    r"\bdeploy(?:ment)? failed\b|\bdeadline exceeded\b|\btimed out\b|"
    r"\b(?:40\d|41\d|42\d|5\d\d)\b(?=[^\n]{0,30}\b(?:error|status|response|returns?|returning|got|getting|exceeded|"
    r"timeout|gateway|forbidden|unauthorized|not found|unprocessable|internal|bad request|код|ошибк))",
    re.I | re.M)
# a message that IS an error ("ModuleNotFoundError: …", "npm ERR! …", "504 Deadline Exceeded", "DEADLINE_EXCEEDED")
_STARTS_WITH_ERROR = re.compile(
    r"^\s*(?:(?:[\w.]+\.)?[A-Z]\w*(?:Error|Exception)\b|Error:|Uncaught\b|npm (?:ERR!|error)|fatal:|E[A-Z]{3,}\b|"
    r"[A-Z]{3,}(?:_[A-Z0-9]{2,})+\b|\d{3}\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*[.!]?\s*$)")
_LOG = re.compile(r"Traceback \(most recent call last\)|\bnpm (?:ERR!|error) code\b|^\s+at \S+ \(.+:\d+:\d+\)", re.M)
_FAILS = re.compile(
    r"\b(?:fails?|failed|failing|crash(?:es|ed|ing)?|breaks|broke|throws?|throwing|stuck|blocked|"
    r"won'?t (?:start|build|run|compile|deploy|work|load|connect|install)|"
    r"doesn'?t (?:work|start|build|run|compile|load|connect|install)|(?:is|isn'?t|not) working|"
    r"keeps? (?:failing|crashing|throwing|giving|returning)|how (?:do|can|should) (?:i|we) fix|help me fix|"
    r"fix (?:this|it|that)|returns? (?:an? )?(?:error|\d{3}))\b|"
    r"\b(?:не работает|не запускается|не собирается|не компилируется|не устанавливается|не грузится|не видит|"
    r"не подключается|падает|упал\w*|вылетает|крашится|застрял\w*|сломал\w*|выда[её]т|выбивает|пишет|вылезает|"
    r"получаю|возвращает|помогите|как (?:исправить|починить|пофиксить))",
    re.I)
# "I get / we're seeing / my app has … an error" — the object must be an error, not a question about decorators
_GETTING_ERROR = re.compile(
    r"\b(?:i|we|my|our|i'm|we're)\b[^.?!\n]{0,40}\b(?:get|getting|got|see|seeing|hit|hitting|have|having|run into|"
    r"ran into|keep getting|receive|receiving)\b[^.?!\n]{0,30}(?:error|exception|bug|warning|crash|traceback|failure|"
    r"\b\d{3}\b|\bcors\b)|"
    r"\bу (?:меня|нас)\b[^.?!\n]{0,40}\bошибк\w*|\b(?:получаю|вылезает|выскакивает|появляется)\b[^.?!\n]{0,30}\bошибк",
    re.I)
_CONCEPT = re.compile(r"^\s*(?:what(?:'s| is| are| does)|explain|why do we|what do .* mean|что (?:такое|значит|означает)|"
                      r"объясни|зачем нужн)\b", re.I)
_TEAM = re.compile(
    r"\bteam ?mates?\b|\bteam up\b|\b(?:find|join|looking for|need|search(?:ing)? for)\b[^.?!\n]{0,20}\bteam\b|"
    r"\b(?:need|looking for|find(?: me| us)?|search(?:ing)? for|recruit(?:ing)?)\b[^.?!\n]{0,24}\b(?:an? )?"
    r"(?:frontend|front-end|backend|back-end|full-?stack|ml|ai|mobile|hardware|game)\s*(?:dev|developer|engineer|"
    r"person|people|folks?)\b|"
    r"\b(?:need|looking for|find(?: me| us)?|search(?:ing)? for|recruit(?:ing)?)\b[^.?!\n]{0,24}\b(?:an? )?"
    r"(?:designer|developer|coder|programmer|data scientist|partner|co-?founder)s?\b(?!\s+tools)|"
    r"\bsomeone who (?:knows|can|does)\b[^.?!\n]{0,40}\b(?:for|in|on|join)\b[^.?!\n]{0,20}\b(?:team|project|hackathon)\b|"
    r"тиммейт\w*|напарник\w*|\bв команду\b|\bищу команду\b|найди (?:мне |нам )?(?:команду|людей|напарника)|"
    r"нуж(?:ен|на|ны) (?:в команду |нам )?(?:фронтендер\w*|бэкендер\w*|бекендер\w*|дизайнер\w*|разработчик\w*|"
    r"программист\w*)",
    re.I)
_MENTOR = re.compile(r"\bmentors?\b|\bментор\w*|\bнаставник\w*", re.I)
_LEARN = re.compile(
    r"\bwhere (?:can|should|do|could) (?:i|we) (?:learn|start|read|study)\b|"
    r"\b(?:learning|good|best|any|some|recommended|recommend|free|beginner)\s+(?:resources?|tutorials?|courses?|"
    r"guides?|docs)\b|\b(?:resources?|tutorials?|courses?|guides?)\s+(?:to learn|for learning|for beginners)\b|"
    r"\btutorials?\b|\blearn\b[^.?!\n]{0,40}\b(?:fast|quickly|tonight|for (?:the|a|this) hackathon|"
    r"in (?:a|one) (?:day|night|weekend))\b|\b(?:starter|template|boilerplate|example (?:project|repo|app)s?)\b"
    r"[^.?!\n]{0,30}\b(?:for|with)\b|\bhow (?:do|can) (?:i|we) get started with\b|"
    r"где (?:можно |мне )?(?:изучить|научиться|почитать|выучить)|\bтуториал\w*|\bкурс\w* по\b|с чего начать|"
    r"\bшаблон\w* (?:для|на)\b|пример\w* (?:проекта|проектов|репозитор\w*)",
    re.I)
_SHIP = re.compile(
    r"\bdeadline\b(?![\s_-]*exceeded)|\btime (?:is )?left\b|\bhow much time (?:do we have|do i have|is left|we have|"
    r"i have|left)\b|\bhow many hours (?:do we have|are left|left)\b|\bon track\b|\bbehind schedule\b|\bdevpost\b|"
    r"\bdemo video\b|\bcut (?:the )?scope\b|\bwhat should we cut\b|\bsubmit (?:it|our project|the project|on devpost)\b|"
    r"\b(?:our|the) submission (?:is due|due|deadline)\b|\bhackathon ends\b|\bdeadline\b|"
    r"\bдедлайн\w*|сколько (?:у нас |мне )?(?:осталось|времени осталось|часов осталось)|\bуспеем\b|\bсабмит\w*|"
    r"сдать проект|девпост|видео для демо|что (?:вырезать|выкинуть)",
    re.I)
_HUB_REF = re.compile(r"\b[SLPMK](\d{1,2})\b")
_REF_WORDS = re.compile(r"\b(?:that|this|the first|the second|the top|the best|the last|другой|этот|первый|второй)\s+"
                        r"(?:answer|link|source|fix|issue|article|repo|mentor|person|match|teammate|card|ответ|"
                        r"ссылк\w*|источник|ментор\w*|человек)\b|\bwho else\b|\bany(?:one)? else\b|\bкто ещё\b",
                        re.I)
# names that look like result IDs but are products ("Amazon S3", "an M2 Mac", "L2 cache")
_BRANDED = re.compile(r"(?:amazon|aws|apple|macbook|mac)\s+[SLPMK]\d{1,2}\b|\b[SLPMK]\d{1,2}\s+(?:bucket|buckets|chip|"
                      r"chips|cache|mac|macbook|pro|max|ultra|air|object|storage)\b|\bs3\b[^.?!\n]{0,30}\bboto3?\b|"
                      r"\bboto3?\b[^.?!\n]{0,30}\bs3\b|\b(?:upload|download|bucket)\b[^.?!\n]{0,15}\bs3\b", re.I)


def _has_tech(text: str) -> bool:
    low = text.lower()
    toks = set(re.findall(r"[a-z][\w.+#-]*", low))
    return any(w in toks for w in STACK) or bool(re.search(r"\.(?:py|js|ts|jsx|tsx|svelte|vue)\b", low))


def is_error(text: str) -> bool:
    return bool(_ERROR_CODE.search(text) or _ERROR_PHRASE.search(text))


def hub_intent(text: str) -> str | None:
    t = (text or "").strip()
    if not t:
        return None
    err = is_error(t)
    fails = bool(_FAILS.search(t))
    getting = bool(_GETTING_ERROR.search(t))
    pasted = bool(_LOG.search(t)) or bool(_STARTS_WITH_ERROR.match(t)) or ("\n" in t and err)
    concept = bool(_CONCEPT.search(t))
    # a roadblock first: its words must not become the deadline or a teammate
    if pasted or (err and (fails or getting)) or (getting and _has_tech(t)) or (fails and _has_tech(t) and not concept):
        return "unstuck"
    if _SHIP.search(t):
        return "ship"
    if _MENTOR.search(t):
        return "mentors"
    if _TEAM.search(t):
        return "team"
    if _LEARN.search(t):
        return "learn"
    return None


def hub_refs(text: str, report: dict[str, Any] | None) -> list[str]:
    """IDs of the report on screen the message names ("what does S2 say?", "tell me about P1") — not products that
    look like IDs ("upload to S3 with boto3", "an M2 Mac")."""
    if not report:
        return []
    from .service import refs_of

    have = set(refs_of(report))
    cleaned = _BRANDED.sub(" ", text or "")
    return [m.group(0).upper() for m in _HUB_REF.finditer(cleaned) if m.group(0).upper() in have]


def about_hub(text: str, report: dict[str, Any] | None) -> bool:
    return bool(report) and (bool(hub_refs(text, report)) or bool(_REF_WORDS.search(text or "")))
