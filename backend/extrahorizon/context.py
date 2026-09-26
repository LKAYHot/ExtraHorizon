"""Context builder: what the LLM actually receives.

Three layers are kept separate on purpose:

1. **signal**   — numbers from the state engine (smoothed proxy, hold time…).
                   They are shown in the UI but NEVER sent to the LLM.
2. **decision** — the engine fired a ``possible_confusion`` event and the learner
                   clicked "Explain differently" → pick a re-explanation strategy.
3. **instruction text** — a short abstract note: possible confusion was observed,
                   the previous explanation may not have helped, use strategy X.
                   No percentages, no images, no landmarks, no camera talk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ADAPTATION_MARKER = "Adaptation note from the ExtraHorizon tutoring app"
EXPLAIN_DIFFERENTLY_USER_TEXT = "Can you explain that differently?"

SUBJECTS = (
    "General",
    "Computer Science",
    "Mathematics",
    "Physics",
    "Chemistry",
    "Biology",
    "History",
    "Economics",
    "Language Learning",
)

BASE_SYSTEM_PROMPT = """You are ExtraHorizon, a friendly adaptive tutor.
Tutor mode subject: {subject}.
- Explain accurately, warmly and concisely: usually under 150 words, unless the learner asks for more depth.
- Use short paragraphs, plain language and Markdown (bullet or numbered lists, `inline code`, fenced code blocks for code).
- Prefer one clear idea at a time; end with at most one short check-for-understanding question when it helps.
- Never claim to know how the learner feels. Never mention cameras, faces, facial expressions, emotion detection or "signals" unless the learner explicitly asks how the app works."""


@dataclass(frozen=True)
class Strategy:
    id: str
    label: str
    description: str
    instruction: str

    def public(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label, "description": self.description}


STRATEGIES: tuple[Strategy, ...] = (
    Strategy(
        id="analogy_example_steps",
        label="Analogy → example → short steps",
        description="One everyday analogy, one small concrete example, then at most three short numbered steps.",
        instruction=(
            "Start with one simple everyday analogy, then give one small concrete example, "
            "then finish with at most three short numbered steps."
        ),
    ),
    Strategy(
        id="worked_trace",
        label="Tiny worked example, traced step by step",
        description="Walk through a very small example one step at a time, then state the core idea in one sentence.",
        instruction=(
            "Walk through one very small example one step at a time, showing what happens at each step "
            "(a short trace or table is fine), then state the core idea in one sentence."
        ),
    ),
    Strategy(
        id="plain_words",
        label="Plain words, no jargon",
        description="Explain as to a curious twelve-year-old: very short sentences, one tiny example, a one-line takeaway.",
        instruction=(
            "Explain it as you would to a curious twelve-year-old: no jargon, very short sentences, "
            "one tiny example, and a one-line takeaway."
        ),
    ),
)
STRATEGY_BY_ID = {s.id: s for s in STRATEGIES}


def pick_strategy(adaptations_in_chain: int) -> Strategy:
    """1st adaptation of an answer → analogy/example/steps, 2nd → trace, 3rd → plain words, …"""
    return STRATEGIES[adaptations_in_chain % len(STRATEGIES)]


def adaptation_instruction(strategy: Strategy) -> str:
    return (
        f"{ADAPTATION_MARKER} (not written by the learner): a possible sign of confusion was observed "
        "after your previous explanation, so that explanation may not have helped. "
        f"Re-explain the same concept in a different way. {strategy.instruction} "
        "Do not repeat sentences, analogies or examples from your previous answer. "
        "Do not claim to know how the learner feels, and do not mention cameras, faces, signals or detection. "
        "Keep it under one hundred fifty words."
    )


def normalize_subject(subject: str | None) -> str:
    if not subject:
        return "General"
    for s in SUBJECTS:
        if s.lower() == subject.strip().lower():
            return s
    return "General"


def build_messages(
    history: list[dict[str, Any]],
    user_text: str,
    *,
    subject: str = "General",
    strategy: Strategy | None = None,
    history_turns: int = 8,
) -> list[dict[str, str]]:
    """Chat Completions ``messages`` for one request.

    ``history`` is the committed conversation (dicts with ``role`` and ``text``);
    only text is used — whatever else a message carries (ids, adaptation metadata,
    signal numbers) is dropped here.
    """
    msgs: list[dict[str, str]] = [
        {"role": "system", "content": BASE_SYSTEM_PROMPT.format(subject=normalize_subject(subject))}
    ]
    turns = [m for m in history if m.get("role") in ("user", "assistant") and m.get("text")]
    if history_turns > 0:
        turns = turns[-2 * history_turns :]
    else:
        turns = []
    for m in turns:
        msgs.append({"role": m["role"], "content": str(m["text"])})
    if strategy is not None:
        msgs.append({"role": "system", "content": adaptation_instruction(strategy)})
    msgs.append({"role": "user", "content": user_text})
    return msgs
