"""A deterministic, offline client for the review-sentiment demo narrative.

The third sibling of :class:`~mrds.demo.client.DeterministicEmailClient` and
:class:`~mrds.demo.ticket_client.DeterministicTicketRouterClient`, with one
difference: this one serves a *spec-driven* feature, so its output type is
generated at runtime rather than imported. It fills whatever schema the engine
hands it, which is exactly what the Anthropic client does in production.

No network, no Anthropic, no API spend. Every answer is a pure function of the
oracle (the dataset's own labels) and the ``wrong_texts`` set, so a narrative of
runs is reproducible byte for byte.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping, Sequence

from pydantic import BaseModel

from mrds.llm.base import LLMMessage, LLMResult

# The demo mislabels sentiment rather than topic: topic is the segment field, and a
# drifting segment would move cases between buckets instead of failing inside one.
_SENTIMENTS: tuple[str, ...] = ("positive", "neutral", "negative")


def _stable_int(text: str) -> int:
    """A process-stable hash (Python's built-in ``hash`` is salted per process)."""
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def _wrong_sentiment(correct: str) -> str:
    """Return a deterministic sentiment different from ``correct``."""
    index = _SENTIMENTS.index(correct)
    return _SENTIMENTS[(index + 1) % len(_SENTIMENTS)]


class DeterministicReviewClient:
    """Offline structured client whose behaviour is fully determined by its inputs."""

    def __init__(
        self,
        *,
        oracle: Mapping[str, tuple[str, str]],
        wrong_texts: frozenset[str],
        token_scale: float = 1.0,
        latency_ms: float = 0.0,
        jitter_ms: float = 8.0,
        simulate_latency: bool = False,
    ) -> None:
        self._oracle = oracle
        self._wrong_texts = wrong_texts
        self._token_scale = token_scale
        self._latency_ms = latency_ms
        self._jitter_ms = jitter_ms
        self._simulate_latency = simulate_latency

    def parse_structured(
        self,
        *,
        model: str,
        messages: Sequence[LLMMessage],
        schema: type[BaseModel],
    ) -> LLMResult[BaseModel]:
        """Answer from the oracle, filling the schema the engine generated from the spec."""
        content = messages[-1].content
        review_text = self._match(content)
        sentiment, topic = self._oracle.get(review_text, ("neutral", "quality"))
        if review_text in self._wrong_texts:
            sentiment = _wrong_sentiment(sentiment)

        if self._simulate_latency and self._latency_ms > 0:
            jitter = (_stable_int(review_text) % max(int(self._jitter_ms), 1)) / 1000.0
            time.sleep(self._latency_ms / 1000.0 + jitter)

        input_tokens = round((24 + len(review_text) / 4) * self._token_scale)
        output_tokens = round(10 * self._token_scale)
        return LLMResult(
            parsed=schema.model_validate({"sentiment": sentiment, "topic": topic}),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )

    def _match(self, content: str) -> str:
        """Recover the case's review text from the rendered user message.

        The generic feature serializes the input payload into the prompt, so the raw
        text is present but not alone on the line — match on containment rather than
        assuming a wire format that the prompt template is free to change.
        """
        if content in self._oracle:
            return content
        for text in self._oracle:
            if text in content:
                return text
        return content
