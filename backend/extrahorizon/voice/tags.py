"""Fish Audio voice cues in square brackets.

The tutor writes cues like ``[huffy and flustered] It's not like I…`` or ``[sighing]``
(docs.fish.audio → Emotion control; drama-3 also plays free-form delivery
descriptions). The TTS gets them; people see clean text (the UI shows the cues as
small stage directions); nothing inside a cue is ever spoken.
"""

from __future__ import annotations

import re

MAX_TAG_CHARS = 90
_TAG_RE = re.compile(r"\[([^\[\]\n]{1,%d})\]" % MAX_TAG_CHARS)

# cues that are sounds / timing rather than a delivery description — they are not carried
# over to the next TTS chunk
SOUND_OR_TIMING = {
    "laughing", "laughs", "chuckling", "chuckles", "sobbing", "crying loudly", "sighing", "sighs",
    "groaning", "groans", "panting", "gasping", "gasps", "yawning", "snoring", "clear throat",
    "clears throat", "audience laughing", "background laughter", "crowd laughing", "break",
    "long-break", "emphasis", "giggles", "giggling", "huffs", "scoffs", "sniffs",
}


def is_sound_or_timing(cue: str) -> bool:
    c = cue.strip().lower()
    return c in SOUND_OR_TIMING or c.startswith(("laugh", "sigh", "gasp", "groan", "chuckl", "giggl"))


def iter_parts(text: str):
    """Yield (kind, value) with kind in {"text", "tag"}."""
    pos = 0
    for m in _TAG_RE.finditer(text):
        if m.start() > pos:
            yield "text", text[pos : m.start()]
        yield "tag", m.group(1).strip()
        pos = m.end()
    if pos < len(text):
        yield "text", text[pos:]


def strip_tags(text: str) -> str:
    """Text without cues, whitespace tidied (for captions, echo checks, word counts)."""
    out = _TAG_RE.sub(" ", text)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r" +([,.!?;:])", r"\1", out)
    return out.strip()


_CODE_FENCE_RE = re.compile(r"```.*?(```|$)", re.S)
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_MD_RE = re.compile(r"(\*\*|__|\*|_{1,2}(?=\w)|^#{1,6}\s*|^\s*[-*+]\s+|^\s*\d+[.)]\s+)", re.M)


_BS = "\\"  # a literal backslash (LaTeX commands start with one)
_MATH_WORDS = [
    (re.compile(re.escape(_BS) + r"frac\{([^{}]+)\}\{([^{}]+)\}"), r"\1 over \2"),
    (re.compile(re.escape(_BS) + r"sqrt\{([^{}]+)\}"), r"the square root of \1"),
    (re.compile(r"\^\{?2\}?(?![\w{])"), " squared"),
    (re.compile(r"\^\{?3\}?(?![\w{])"), " cubed"),
    (re.compile(r"\^\{([^{}]+)\}|\^(\w+)"), lambda m: f" to the power of {m.group(1) or m.group(2)}"),
    (re.compile(re.escape(_BS) + r"(?:cdot|times)\b|[×·]"), " times "),
    (re.compile(re.escape(_BS) + r"div\b|÷"), " divided by "),
    (re.compile(re.escape(_BS) + r"leq?\b|≤"), " is at most "),
    (re.compile(re.escape(_BS) + r"geq?\b|≥"), " is at least "),
    (re.compile(re.escape(_BS) + r"neq?\b|≠"), " is not equal to "),
    (re.compile(re.escape(_BS) + r"approx\b|≈"), " is approximately "),
    (re.compile(re.escape(_BS) + r"(?:to|rightarrow)\b|→"), " to "),
    (re.compile(re.escape(_BS) + r"infty\b|∞"), "infinity"),
    (re.compile(re.escape(_BS) + r"pi\b|π"), "pi"),
    (re.compile(r"√"), "the square root of "),
]
# \( \) \[ \] — maths delimiters (a "\[" would otherwise look like a voice cue); $…$ only
# around something that looks like maths ("$5 and $10" stays money)
_MATH_DELIMS = re.compile(re.escape(_BS) + r"[()\[\]]")
_DOLLAR_MATH = re.compile(r"\${1,2}([^$\n]{1,160}?)\${1,2}")
_LATEX_CMD = re.compile(re.escape(_BS) + r"([A-Za-z]+)")
_MATH_HINT = set(_BS + "^$×·÷≤≥≠≈→∞π√")


def speak_math(text: str) -> str:
    """LaTeX/maths the model should not have written, turned into words for the voice."""
    if not _MATH_HINT.intersection(text):
        return text
    t = _MATH_DELIMS.sub(" ", text)
    t = _DOLLAR_MATH.sub(lambda m: m.group(1) if any(c in m.group(1) for c in _BS + "^_={}") else m.group(0), t)
    for rx, rep in _MATH_WORDS:
        t = rx.sub(rep, t)
    t = _LATEX_CMD.sub(r"\1", t)  # any other command → its name
    return t.replace("{", "").replace("}", "")


def speakable(text: str) -> str:
    """What goes to the TTS: cues kept, markdown and code removed (code is shown, not read)."""
    t = _CODE_FENCE_RE.sub(" [break] ", speak_math(text))
    t = _INLINE_CODE_RE.sub(r"\1", t)
    t = _MD_RE.sub("", t)
    t = re.sub(r"https?://\S+", "the link", t)
    out = []
    for kind, value in iter_parts(t):
        if kind == "tag":
            out.append(f"[{value}]")
        else:  # stray brackets outside valid cues would be read aloud
            out.append(value.replace("[", " ").replace("]", " "))
    return re.sub(r"\s+", " ", "".join(out))
