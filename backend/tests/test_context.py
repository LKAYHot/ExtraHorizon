"""What the LLM receives: persona, voice-cue rules, the expression note, the history."""

from __future__ import annotations

import re

from extrahorizon.context import (
    EMOTION_NOTE_PREFIX,
    REPLY_NOTE_TEXT,
    REPLY_NOTE_VOICE,
    build_messages,
    emotion_note,
    normalize_subject,
    persona_prompt,
)

HAPPY = {"available": True, "dominant": "happiness", "strength": "clearly", "source": "camera",
         "text": "The learner looks clearly happy. Overall mood: positive, moderate energy."}
NONE = {"available": False, "reason": "no_face", "text": "Camera emotion estimate: not available right now."}


def test_persona_is_a_tsundere_expert_who_speaks_english():
    p = persona_prompt("Mathematics", "Rika")
    assert "You are Rika" in p and "tsundere" in p.lower()
    assert "expert" in p.lower() and "Mathematics" in p
    assert "Always reply in natural spoken English" in p and "Russian" in p
    # Fish Audio voice cues: square brackets, delivery descriptions, sounds, pauses
    for cue in ("[huffy and flustered", "[sighing]", "[break]", "[emphasis]", "[laughing]"):
        assert cue in p
    assert "never put anything else in square brackets" in p


def test_persona_is_a_person_on_a_video_call_who_sees_the_learner():
    p = persona_prompt()
    assert "SPOKEN aloud" in p and "forty-five words" in p
    assert "You can see the learner through their webcam" in p and "treat it as your own eyes" in p
    assert "never say you can't see them" in p and "your view is blocked" in p
    assert "Most replies don't mention it" in p
    assert "not what they feel" in p and "believe them" in p  # an expression is not a feeling; corrections win


def test_persona_bans_assistant_phrases():
    p = persona_prompt()
    for phrase in ("How can I help you?", "Tell me what you were asking", "I'll answer directly", "As an AI"):
        assert phrase in p  # listed under "Never say things like"
    assert "never like an AI assistant" in p and "restate the question" in p


def test_subjects_are_normalised():
    assert normalize_subject("computer science") == "Computer Science"
    assert normalize_subject("astrology") == "General"
    assert normalize_subject(None) == "General"


def test_emotion_note_is_her_view_in_words_only():
    note = emotion_note(HAPPY)
    assert note.startswith(f"[{EMOTION_NOTE_PREFIX}]") and "webcam" in note
    assert "clearly happy" in note and not re.search(r"\d", note)
    assert "estimate" not in note and "guess" not in note
    assert emotion_note(NONE) is None and emotion_note(None) is None
    again = emotion_note({**HAPPY, "unchanged": True})
    assert again.endswith("only mention it if it matters.)")
    assert "demo simulation" in emotion_note({**HAPPY, "source": "simulation"})


def test_message_layout_keeps_a_stable_prefix_for_caching():
    history = [
        {"role": "user", "text": "What is a loop?", "id": "m1", "created": 1},
        {"role": "assistant", "text": "[proud] A loop repeats code.", "id": "m2", "emotion_context": HAPPY},
    ]
    msgs = build_messages(history, "And recursion?", subject="Computer Science", emotion_context=HAPPY, voice=True)
    assert msgs[0]["role"] == "system" and msgs[0]["content"] == persona_prompt("Computer Science")
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "system", "system", "user"]
    assert msgs[2]["content"] == "[proud] A loop repeats code."  # cues kept for a consistent voice
    assert msgs[3]["content"] == emotion_note(HAPPY)
    assert msgs[4]["content"] == REPLY_NOTE_VOICE and "said this out loud" in REPLY_NOTE_VOICE
    assert msgs[-1] == {"role": "user", "content": "And recursion?"}
    # only text reaches the model — never ids, timings or stored emotion metadata
    assert all(set(m) == {"role", "content"} for m in msgs)


def test_typed_question_without_a_face_gets_only_the_reply_rules():
    msgs = build_messages([], "hi", emotion_context=NONE)
    assert [m["role"] for m in msgs] == ["system", "system", "user"]
    assert msgs[1]["content"] == REPLY_NOTE_TEXT
    assert "never LaTeX" in REPLY_NOTE_TEXT and "three short sentences" in REPLY_NOTE_TEXT


def test_interrupted_answers_are_marked_for_the_model():
    history = [{"role": "user", "text": "Explain"}, {"role": "assistant", "text": "[calm] So, first", "interrupted": True}]
    msgs = build_messages(history, "wait, what?")
    assert msgs[2]["content"].endswith("(…the learner interrupted me here)")


def test_history_is_limited():
    history = [{"role": r, "text": f"{r} {i}"} for i in range(30) for r in ("user", "assistant")]
    msgs = build_messages(history, "new", history_turns=3)
    assert len(msgs) == 1 + 6 + 2 and msgs[1]["content"] == "user 27"
