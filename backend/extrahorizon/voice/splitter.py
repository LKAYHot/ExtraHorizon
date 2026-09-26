"""Streaming splitter: LLM deltas → TTS chunks.

Latency: the first chunk leaves as soon as there is a sentence end, or — once
``first_chars`` are buffered — a clause boundary (comma, semicolon, dash, colon), so the
voice starts after a few words instead of a whole paragraph. Later chunks prefer whole
sentences (natural prosody) up to ``chunk_chars``.

Safety: never cuts inside a ``[cue]`` or an unfinished code fence; markdown/code are
removed (``tags.speakable``); cue-only pieces are glued to the next words (Fish may not
voice an effect without text).

Drama-3 applies a delivery cue only to its own flush chunk, so when a sentence is split,
the continuation is prefixed with the last *delivery* cue (sounds/pauses are not repeated).
"""

from __future__ import annotations

import re

from .tags import is_sound_or_timing, iter_parts, speakable, strip_tags

_SENT_END = re.compile(r"(?<![0-9])([.!?…]+|\.{3})([\"')\]]*)(?=\s)|```[ \t]*\n")
_NEXT_CUE = re.compile(r"\s*\[([^\[\]\n]{1,90})\]")
_CLAUSE = re.compile(r"(,|;|:|\s—|\s–|\s-)\s")


class TtsSplitter:
    def __init__(self, first_chars: int = 36, chunk_chars: int = 140) -> None:
        self.first_chars = first_chars
        self.chunk_chars = chunk_chars
        self.buf = ""
        self.first = True
        self.last_cue: str | None = None
        self._pending = ""  # cue-only text waiting for words

    # ------------------------------------------------------------------ public
    def feed(self, delta: str) -> list[str]:
        self.buf += delta
        return self._drain(final=False)

    def flush(self) -> list[str]:
        out = self._drain(final=True)
        rest = self.buf
        self.buf = ""
        if rest.strip() or self._pending:
            c = self._prepare(rest, final=True)
            if c:
                out.append(c)
        return out

    # ------------------------------------------------------------------ cutting
    def _safe_limit(self) -> int:
        """Index before which a cut is allowed (not inside an open [cue] or ``` fence)."""
        text = self.buf
        limit = len(text)
        fences = [m.start() for m in re.finditer("```", text)]
        if len(fences) % 2 == 1:
            limit = min(limit, fences[-1])
        open_br = text.rfind("[")
        if open_br > text.rfind("]"):
            limit = min(limit, open_br)
        return limit

    def _find_cut(self, final: bool) -> int | None:
        text = self.buf
        limit = self._safe_limit()
        if limit <= 0:
            return None
        min_len = 10 if self.first else 24
        target = self.first_chars if self.first else self.chunk_chars
        size = lambda end: len(strip_tags(text[:end]))  # noqa: E731 — spoken characters up to a cut
        sent = None
        for m in _SENT_END.finditer(text, 0, limit + 1):
            end = m.end()
            if end > limit:
                break
            n = len(strip_tags(text[:end]).strip())
            nxt = _NEXT_CUE.match(text, end)
            new_delivery = nxt is not None and not is_sound_or_timing(nxt.group(1))
            if n >= min_len or (new_delivery and n >= 4) or (final and end > 0):
                sent = end
                break
        window = text[: sent if sent is not None else limit]
        clauses = [m.end() for m in _CLAUSE.finditer(window) if size(m.end()) >= 12]
        if sent is not None:
            # a whole sentence — unless a burst of text made it long: then its first clauses go first
            if size(sent) <= max(target * 1.5, 60) or not clauses:
                return sent
            return self._pick_clause(clauses, size, target)
        if size(limit) >= target:
            if clauses:
                return self._pick_clause(clauses, size, target)
            if size(limit) >= target * 2:
                sp = window.rfind(" ")
                if sp > 0:
                    return sp + 1
        return None

    def _pick_clause(self, clauses: list[int], size, target: int) -> int:
        if self.first:  # the earliest clause long enough (lowest latency), else the longest so far
            after = [c for c in clauses if size(c) >= target]
            return after[0] if after else clauses[-1]
        within = [c for c in clauses if size(c) <= target]  # later chunks: as long as allowed
        return within[-1] if within else clauses[0]

    def _drain(self, final: bool) -> list[str]:
        out: list[str] = []
        while True:
            cut = self._find_cut(final)
            if cut is None:
                break
            piece, self.buf = self.buf[:cut], self.buf[cut:]
            c = self._prepare(piece, final=False)
            if c:
                out.append(c)
        return out

    # ------------------------------------------------------------------ chunk text
    def _prepare(self, piece: str, final: bool) -> str | None:
        text = speakable(self._pending + piece).strip()
        self._pending = ""
        if not text:
            return None
        if not strip_tags(text).strip(" .,!?…-"):
            if final:
                return None  # a trailing cue without words is dropped
            self._pending = text + " "  # glue cue-only pieces to the next words
            return None
        lead = _NEXT_CUE.match(text)
        starts_with_delivery = lead is not None and lead.start() == 0 and not is_sound_or_timing(lead.group(1))
        prefix = self.last_cue if (not starts_with_delivery and self.last_cue and not self.first) else None
        # then remember the latest delivery cue of THIS chunk (not a sound / pause)
        for kind, value in iter_parts(text):
            if kind == "tag" and not is_sound_or_timing(value):
                self.last_cue = value
        if prefix:
            text = f"[{prefix}] {text}"
        self.first = False
        return text
