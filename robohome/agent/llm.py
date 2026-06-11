"""
LLM client adapters for the RoboHome agent.

This module wraps Gemini and Groq behind a single ``LLMClient`` interface
so the rest of the harness does not need to know which provider it is
talking to. The loop just calls ``client.think(observation=..., ...)``
and gets back a typed ``LLMResponse`` with the parsed action, the model's
reasoning text, token usage, and latency.

Design choices worth knowing
----------------------------

1. Sync, not async. The loop is sequential (observe, think, act, repeat)
   so async would only add complexity. Parallel evaluation runs use
   ``concurrent.futures`` at a higher layer, not async here.

2. Non-streaming. The viewer can show the thought after it arrives.
   Streaming would mean two parsing paths to maintain.

3. Gemini uses native function calling; Groq uses JSON mode. The Llama
   models on the Groq free tier do not support function calling
   reliably, so we instruct them to return JSON conforming to the same
   action schema and parse it ourselves.

4. Three retries on parse failure. Each retry feeds the error message
   back to the model as part of the next user turn. After three, the
   client raises ``LLMParseError`` and the loop decides what to do
   (typically substitute ``look_around`` to make progress).

5. Provider selection is environment-driven (``LLM_PROVIDER``), so
   switching providers is a one-line ``.env`` change with no code edit.

6. The SDKs are lazy-imported inside each constructor. Importing this
   module never triggers a network library import, which keeps tests
   fast and avoids hard dependencies for code paths that do not use a
   given provider.
"""

from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from robohome.harness.actions import (
    AnyAction,
    gemini_function_call_to_action,
    parse_action,
    to_gemini_tools,
)
from robohome.harness.observation import Observation, observation_to_llm_text

# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TokenUsage:
    """Token usage for one LLM call.

    Supports addition so the evaluation runner can accumulate totals
    across a whole task without manual bookkeeping.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
        )


@dataclass(frozen=True)
class LLMResponse:
    """Everything the loop needs from one ``think()`` call.

    ``raw_response`` is a best-effort dict view of the SDK's response
    object, kept purely for logs and debugging. The harness does not
    rely on its structure.
    """

    action: AnyAction
    thought: str
    raw_response: dict[str, Any]
    usage: TokenUsage
    latency_ms: int


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LLMError(Exception):
    """Base class for all LLM client errors."""


class LLMParseError(LLMError):
    """The model returned output we could not parse into a valid action."""


class LLMConfigError(LLMError):
    """API key missing, provider unknown, SDK not installed, etc."""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class LLMClient(ABC):
    """Common interface every LLM adapter implements."""

    @abstractmethod
    def think(
        self,
        *,
        observation: Observation,
        recent_history_summaries: Sequence[str] = (),
    ) -> LLMResponse:
        """Send one observation to the model and return its chosen action."""


# ---------------------------------------------------------------------------
# Shared prompt formatting
# ---------------------------------------------------------------------------


def _format_user_message(
    observation: Observation,
    recent_history_summaries: Sequence[str] = (),
) -> str:
    """Build the per-step user message.

    Layout:
      1. Recent history (oldest first), if any
      2. The current observation as JSON
      3. A short closing instruction

    The system prompt is set separately on each client.
    """
    parts: list[str] = []

    if recent_history_summaries:
        parts.append("Recent history (oldest first):")
        for line in recent_history_summaries:
            parts.append(f"  - {line}")
        parts.append("")

    parts.append("Current observation:")
    parts.append(observation_to_llm_text(observation))
    parts.append("")
    parts.append(
        "Think briefly about your next step, then call exactly one action tool."
    )

    return "\n".join(parts)


def _append_retry_hint(user_message: str, error: str) -> str:
    """Append a parse-error hint for the next retry attempt."""
    return (
        user_message
        + f"\n\nYour previous response could not be parsed: {error}\n"
        + "Please call exactly one valid action with correctly-typed arguments."
    )


def _safe_dump(response: Any) -> dict[str, Any]:
    """Best-effort conversion of an SDK response to a dict.

    Different SDKs use different serialisation methods. We try the
    common ones and fall back to ``str()`` so logging never crashes
    just because the response type changed.
    """
    if hasattr(response, "model_dump"):
        try:
            return response.model_dump()  # type: ignore[no-any-return]
        except Exception:
            pass
    if hasattr(response, "to_dict"):
        try:
            return response.to_dict()  # type: ignore[no-any-return]
        except Exception:
            pass
    return {"repr": str(response)}


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------


class GeminiClient(LLMClient):
    """LLM client backed by Google Gemini with native function calling.

    The action schemas from ``actions.to_gemini_tools()`` are registered
    as tools, and ``function_calling_config.mode='ANY'`` forces the
    model to call exactly one of them on every turn. This eliminates a
    whole category of parse failures.
    """

    def __init__(
        self,
        *,
        api_key: str,
        system_prompt: str,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.3,
        max_retries: int = 3,
    ) -> None:
        if not api_key:
            raise LLMConfigError("GEMINI_API_KEY is empty")

        try:
            from google import genai  # type: ignore[import-not-found]
            from google.genai import types as genai_types  # type: ignore[import-not-found]
        except ImportError as e:
            raise LLMConfigError(
                "google-genai not installed. "
                "Run: pip install google-genai"
            ) from e

        self._types = genai_types
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._system_prompt = system_prompt
        self._temperature = temperature
        self._max_retries = max(1, max_retries)
        self._tools = [
            genai_types.Tool(function_declarations=to_gemini_tools())
        ]

    def think(
        self,
        *,
        observation: Observation,
        recent_history_summaries: Sequence[str] = (),
    ) -> LLMResponse:
        user_message = _format_user_message(observation, recent_history_summaries)

        last_error: Optional[Exception] = None
        for _ in range(self._max_retries):
            t0 = time.perf_counter()
            raw = self._client.models.generate_content(
                model=self._model,
                contents=[user_message],
                config=self._types.GenerateContentConfig(
                    system_instruction=self._system_prompt,
                    tools=self._tools,
                    temperature=self._temperature,
                    tool_config=self._types.ToolConfig(
                        function_calling_config=self._types.FunctionCallingConfig(
                            mode="ANY",
                        ),
                    ),
                ),
            )
            latency_ms = int((time.perf_counter() - t0) * 1000)

            try:
                thought, action = _extract_from_gemini_response(raw)
            except LLMParseError as e:
                last_error = e
                user_message = _append_retry_hint(user_message, str(e))
                continue

            usage = _extract_gemini_usage(raw)
            return LLMResponse(
                action=action,
                thought=thought,
                raw_response=_safe_dump(raw),
                usage=usage,
                latency_ms=latency_ms,
            )

        raise LLMParseError(
            f"Gemini returned malformed output after {self._max_retries} "
            f"attempts: {last_error}"
        )


def _extract_from_gemini_response(response: Any) -> tuple[str, AnyAction]:
    """Pull ``(thought, action)`` out of a Gemini response object.

    Raises ``LLMParseError`` if the response is missing the structure
    we expect or contains no usable function call.
    """
    candidates = getattr(response, "candidates", None)
    if not candidates:
        raise LLMParseError("response has no candidates")

    content = getattr(candidates[0], "content", None)
    parts = getattr(content, "parts", None) or []
    if not parts:
        raise LLMParseError("response has no content parts")

    thought_chunks: list[str] = []
    function_call = None
    for part in parts:
        text = getattr(part, "text", None)
        if text:
            thought_chunks.append(text)
        fc = getattr(part, "function_call", None)
        if fc is not None:
            function_call = fc

    if function_call is None:
        raise LLMParseError("response contained no function call")

    name = getattr(function_call, "name", None)
    if not name:
        raise LLMParseError("function call has no name")

    raw_args = getattr(function_call, "args", None) or {}
    # The SDK may return a proto Struct, MapComposite, or dict. Normalise.
    if hasattr(raw_args, "items"):
        args = dict(raw_args)
    else:
        args = {}

    try:
        action = gemini_function_call_to_action(name, args)
    except Exception as e:
        raise LLMParseError(
            f"could not parse function call '{name}' with args {args}: {e}"
        ) from e

    thought = "\n".join(c.strip() for c in thought_chunks if c.strip())
    return thought, action


def _extract_gemini_usage(response: Any) -> TokenUsage:
    """Pull token counts from a Gemini response, defaulting to zero."""
    usage_meta = getattr(response, "usage_metadata", None)
    if usage_meta is None:
        return TokenUsage()
    return TokenUsage(
        prompt_tokens=getattr(usage_meta, "prompt_token_count", 0) or 0,
        completion_tokens=getattr(usage_meta, "candidates_token_count", 0) or 0,
    )


# ---------------------------------------------------------------------------
# Groq
# ---------------------------------------------------------------------------


class GroqClient(LLMClient):
    """LLM client backed by Groq's OpenAI-compatible API.

    Uses ``response_format={'type': 'json_object'}`` and an augmented
    system prompt that describes the action JSON shape. Llama models on
    the Groq free tier do not currently support function calling
    reliably, so we lean on JSON mode plus our own validation.
    """

    def __init__(
        self,
        *,
        api_key: str,
        system_prompt: str,
        model: str = "llama-3.3-70b-versatile",
        temperature: float = 0.3,
        max_retries: int = 3,
    ) -> None:
        if not api_key:
            raise LLMConfigError("GROQ_API_KEY is empty")

        try:
            from groq import Groq  # type: ignore[import-not-found]
        except ImportError as e:
            raise LLMConfigError(
                "groq not installed. Run: pip install groq"
            ) from e

        self._client = Groq(api_key=api_key)
        self._model = model
        self._temperature = temperature
        self._max_retries = max(1, max_retries)
        self._system_prompt = _augment_system_prompt_for_json(system_prompt)

    def think(
        self,
        *,
        observation: Observation,
        recent_history_summaries: Sequence[str] = (),
    ) -> LLMResponse:
        user_message = _format_user_message(observation, recent_history_summaries)

        last_error: Optional[Exception] = None
        for _ in range(self._max_retries):
            t0 = time.perf_counter()
            raw = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": user_message},
                ],
                response_format={"type": "json_object"},
                temperature=self._temperature,
            )
            latency_ms = int((time.perf_counter() - t0) * 1000)

            content = raw.choices[0].message.content or "{}"
            try:
                thought, action = _extract_from_groq_json(content)
            except LLMParseError as e:
                last_error = e
                user_message = _append_retry_hint(user_message, str(e))
                continue

            usage = _extract_groq_usage(raw)
            return LLMResponse(
                action=action,
                thought=thought,
                raw_response=_safe_dump(raw),
                usage=usage,
                latency_ms=latency_ms,
            )

        raise LLMParseError(
            f"Groq returned malformed output after {self._max_retries} "
            f"attempts: {last_error}"
        )


def _augment_system_prompt_for_json(system_prompt: str) -> str:
    """Append the JSON-mode output contract to the system prompt."""
    return (
        system_prompt
        + "\n\nOUTPUT FORMAT (strict):\n"
        + "Reply with a single JSON object and nothing else. It must contain:\n"
        + "  - 'thought': a short reasoning string.\n"
        + "  - 'action': an object with a 'type' field (one of move, turn, "
        + "look_around, pick_up, put_down, open, close, use, note, done) "
        + "plus the relevant arguments.\n"
        + 'Example: {"thought": "I should move north.", '
        + '"action": {"type": "move", "direction": "north"}}'
    )


def _extract_from_groq_json(text: str) -> tuple[str, AnyAction]:
    """Parse Groq's JSON-mode output into ``(thought, action)``."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMParseError(f"output was not valid JSON: {e}") from e

    if not isinstance(data, dict):
        raise LLMParseError("output JSON was not an object")

    thought = str(data.get("thought", "")).strip()
    action_dict = data.get("action")
    if not isinstance(action_dict, dict):
        raise LLMParseError("missing or invalid 'action' field")

    try:
        action = parse_action(action_dict)
    except Exception as e:
        raise LLMParseError(f"could not parse action: {e}") from e

    return thought, action


def _extract_groq_usage(response: Any) -> TokenUsage:
    """Pull token counts from a Groq response, defaulting to zero."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
    )


# ---------------------------------------------------------------------------
# Fake client (for tests and offline development)
# ---------------------------------------------------------------------------


class FakeLLMClient(LLMClient):
    """Deterministic client that returns scripted responses.

    Constructed with a list of ``(thought, action_dict)`` pairs which it
    returns in order on successive ``think()`` calls. Tracks the
    observations it received so tests can assert against them. Raises
    ``LLMError`` when the script runs out.
    """

    def __init__(
        self,
        scripted_responses: Sequence[tuple[str, dict[str, Any]]] = (),
    ) -> None:
        self._scripted: list[tuple[str, dict[str, Any]]] = list(scripted_responses)
        self._calls: list[tuple[Observation, list[str]]] = []

    @property
    def calls(self) -> list[tuple[Observation, list[str]]]:
        """All ``(observation, history)`` pairs passed to ``think()``."""
        return list(self._calls)

    @property
    def remaining(self) -> int:
        return len(self._scripted)

    def think(
        self,
        *,
        observation: Observation,
        recent_history_summaries: Sequence[str] = (),
    ) -> LLMResponse:
        self._calls.append((observation, list(recent_history_summaries)))
        if not self._scripted:
            raise LLMError("FakeLLMClient ran out of scripted responses")
        thought, action_dict = self._scripted.pop(0)
        action = parse_action(action_dict)
        return LLMResponse(
            action=action,
            thought=thought,
            raw_response={"_fake": True, "thought": thought, "action": action_dict},
            usage=TokenUsage(prompt_tokens=0, completion_tokens=0),
            latency_ms=0,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_client(
    *,
    system_prompt: str,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_retries: int = 3,
) -> LLMClient:
    """Construct an LLM client from env vars (with optional overrides).

    Reads from environment:
      * ``LLM_PROVIDER`` (default ``gemini``)
      * ``GEMINI_API_KEY`` / ``GROQ_API_KEY``
      * ``GEMINI_MODEL`` / ``GROQ_MODEL``
      * ``LLM_TEMPERATURE`` (default ``0.3``)

    Any explicit keyword argument overrides the corresponding env value.
    """
    chosen = (provider or os.environ.get("LLM_PROVIDER") or "gemini").lower()

    if temperature is None:
        temperature = float(os.environ.get("LLM_TEMPERATURE", "0.3"))

    if chosen == "gemini":
        return GeminiClient(
            api_key=api_key or os.environ.get("GEMINI_API_KEY", ""),
            system_prompt=system_prompt,
            model=model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
            temperature=temperature,
            max_retries=max_retries,
        )

    if chosen == "groq":
        return GroqClient(
            api_key=api_key or os.environ.get("GROQ_API_KEY", ""),
            system_prompt=system_prompt,
            model=model or os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
            temperature=temperature,
            max_retries=max_retries,
        )

    raise LLMConfigError(
        f"Unknown LLM_PROVIDER: {chosen!r}. Expected 'gemini' or 'groq'."
    )


__all__ = [
    "TokenUsage",
    "LLMResponse",
    "LLMError",
    "LLMParseError",
    "LLMConfigError",
    "LLMClient",
    "GeminiClient",
    "GroqClient",
    "FakeLLMClient",
    "make_client",
]
