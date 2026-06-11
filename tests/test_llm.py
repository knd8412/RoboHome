"""Tests for ``robohome.agent.llm``."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from robohome.agent.llm import (
    FakeLLMClient,
    LLMConfigError,
    LLMError,
    LLMParseError,
    LLMResponse,
    TokenUsage,
    _append_retry_hint,
    _augment_system_prompt_for_json,
    _extract_from_gemini_response,
    _extract_from_groq_json,
    _extract_gemini_usage,
    _extract_groq_usage,
    _format_user_message,
    _safe_dump,
    make_client,
)
from robohome.harness.actions import (
    Done,
    LookAround,
    Move,
    Note,
    PickUp,
)
from robohome.harness.observation import (
    RobotState,
    WorldView,
    build_observation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_obs(**robot_overrides: Any):
    from robohome.harness.actions import Direction

    robot_defaults = dict(
        room="kitchen",
        position=(5, 8),
        facing=Direction.NORTH,
    )
    robot_defaults.update(robot_overrides)
    robot = RobotState(**robot_defaults)
    wv = WorldView(
        current_room="kitchen",
        room_description="You are in the kitchen.",
        visible_objects=[],
        exits=[],
    )
    return build_observation(
        step=0,
        task="make tea",
        world_view=wv,
        robot=robot,
    )


# ---------------------------------------------------------------------------
# TokenUsage
# ---------------------------------------------------------------------------


class TestTokenUsage:
    def test_defaults_to_zero(self):
        u = TokenUsage()
        assert u.prompt_tokens == 0
        assert u.completion_tokens == 0
        assert u.total == 0

    def test_total(self):
        u = TokenUsage(prompt_tokens=100, completion_tokens=20)
        assert u.total == 120

    def test_addition(self):
        a = TokenUsage(prompt_tokens=10, completion_tokens=5)
        b = TokenUsage(prompt_tokens=3, completion_tokens=2)
        c = a + b
        assert c.prompt_tokens == 13
        assert c.completion_tokens == 7

    def test_is_immutable(self):
        u = TokenUsage(prompt_tokens=1)
        with pytest.raises(Exception):
            u.prompt_tokens = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _format_user_message
# ---------------------------------------------------------------------------


class TestFormatUserMessage:
    def test_minimal_no_history(self):
        obs = make_obs()
        msg = _format_user_message(obs)
        assert "Current observation:" in msg
        assert "Recent history" not in msg
        assert "action" in msg.lower()

    def test_with_history(self):
        obs = make_obs()
        msg = _format_user_message(
            obs,
            recent_history_summaries=[
                "step 5 in kitchen, last: move -> success",
                "step 6 in kitchen, holding kettle, last: pick_up -> success",
            ],
        )
        assert "Recent history" in msg
        assert "holding kettle" in msg
        assert msg.index("Recent history") < msg.index("Current observation")

    def test_includes_observation_json(self):
        obs = make_obs()
        msg = _format_user_message(obs)
        assert '"task": "make tea"' in msg
        assert '"room": "kitchen"' in msg


class TestAppendRetryHint:
    def test_appends_error(self):
        out = _append_retry_hint("original prompt", "invalid direction")
        assert "original prompt" in out
        assert "invalid direction" in out
        assert "valid action" in out


# ---------------------------------------------------------------------------
# _safe_dump
# ---------------------------------------------------------------------------


class TestSafeDump:
    def test_with_model_dump(self):
        class Dummy:
            def model_dump(self):
                return {"a": 1}

        assert _safe_dump(Dummy()) == {"a": 1}

    def test_with_to_dict(self):
        class Dummy:
            def to_dict(self):
                return {"b": 2}

        assert _safe_dump(Dummy()) == {"b": 2}

    def test_fallback_to_repr(self):
        class Dummy:
            def __str__(self):
                return "<dummy>"

        out = _safe_dump(Dummy())
        assert out == {"repr": "<dummy>"}

    def test_model_dump_failure_falls_back(self):
        class Dummy:
            def model_dump(self):
                raise RuntimeError("boom")

            def __str__(self):
                return "<dummy>"

        assert _safe_dump(Dummy()) == {"repr": "<dummy>"}


# ---------------------------------------------------------------------------
# Gemini extraction
# ---------------------------------------------------------------------------


def _gemini_response(
    *,
    parts: list[Any],
    prompt_tokens: int = 100,
    completion_tokens: int = 20,
) -> SimpleNamespace:
    """Build a SimpleNamespace shaped like a real Gemini response."""
    return SimpleNamespace(
        candidates=[
            SimpleNamespace(content=SimpleNamespace(parts=parts)),
        ],
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt_tokens,
            candidates_token_count=completion_tokens,
        ),
    )


def _gemini_part(*, text: str | None = None, function_call: Any = None):
    return SimpleNamespace(text=text, function_call=function_call)


class TestExtractFromGeminiResponse:
    def test_parses_move_function_call(self):
        fc = SimpleNamespace(name="move", args={"direction": "north"})
        resp = _gemini_response(
            parts=[
                _gemini_part(text="I should head north.", function_call=None),
                _gemini_part(text=None, function_call=fc),
            ]
        )
        thought, action = _extract_from_gemini_response(resp)
        assert isinstance(action, Move)
        assert "head north" in thought

    def test_parses_no_args_action(self):
        fc = SimpleNamespace(name="look_around", args={})
        resp = _gemini_response(parts=[_gemini_part(function_call=fc)])
        thought, action = _extract_from_gemini_response(resp)
        assert isinstance(action, LookAround)
        assert thought == ""

    def test_parses_done(self):
        fc = SimpleNamespace(name="done", args=None)
        resp = _gemini_response(parts=[_gemini_part(function_call=fc)])
        _, action = _extract_from_gemini_response(resp)
        assert isinstance(action, Done)

    def test_concatenates_multiple_text_chunks(self):
        fc = SimpleNamespace(name="look_around", args={})
        resp = _gemini_response(
            parts=[
                _gemini_part(text="First thought."),
                _gemini_part(text="Second thought."),
                _gemini_part(function_call=fc),
            ]
        )
        thought, _ = _extract_from_gemini_response(resp)
        assert "First thought." in thought
        assert "Second thought." in thought

    def test_no_candidates_raises(self):
        resp = SimpleNamespace(candidates=[])
        with pytest.raises(LLMParseError, match="no candidates"):
            _extract_from_gemini_response(resp)

    def test_no_parts_raises(self):
        resp = SimpleNamespace(
            candidates=[SimpleNamespace(content=SimpleNamespace(parts=[]))]
        )
        with pytest.raises(LLMParseError, match="no content parts"):
            _extract_from_gemini_response(resp)

    def test_no_function_call_raises(self):
        resp = _gemini_response(
            parts=[_gemini_part(text="I am thinking but not calling.")]
        )
        with pytest.raises(LLMParseError, match="no function call"):
            _extract_from_gemini_response(resp)

    def test_bad_function_args_raises(self):
        fc = SimpleNamespace(name="move", args={"direction": "skyward"})
        resp = _gemini_response(parts=[_gemini_part(function_call=fc)])
        with pytest.raises(LLMParseError, match="could not parse"):
            _extract_from_gemini_response(resp)

    def test_unknown_function_name_raises(self):
        fc = SimpleNamespace(name="teleport", args={})
        resp = _gemini_response(parts=[_gemini_part(function_call=fc)])
        with pytest.raises(LLMParseError):
            _extract_from_gemini_response(resp)


class TestExtractGeminiUsage:
    def test_present(self):
        resp = SimpleNamespace(
            usage_metadata=SimpleNamespace(
                prompt_token_count=42,
                candidates_token_count=13,
            )
        )
        u = _extract_gemini_usage(resp)
        assert u.prompt_tokens == 42
        assert u.completion_tokens == 13

    def test_missing_returns_zero(self):
        u = _extract_gemini_usage(SimpleNamespace())
        assert u.total == 0


# ---------------------------------------------------------------------------
# Groq extraction
# ---------------------------------------------------------------------------


class TestExtractFromGroqJson:
    def test_parses_valid_response(self):
        text = json.dumps(
            {
                "thought": "I should head north.",
                "action": {"type": "move", "direction": "north"},
            }
        )
        thought, action = _extract_from_groq_json(text)
        assert isinstance(action, Move)
        assert "head north" in thought

    def test_parses_no_args_action(self):
        text = json.dumps({"thought": "", "action": {"type": "look_around"}})
        _, action = _extract_from_groq_json(text)
        assert isinstance(action, LookAround)

    def test_handles_note_action(self):
        text = json.dumps(
            {
                "thought": "Logging info.",
                "action": {"type": "note", "text": "bedroom is north"},
            }
        )
        _, action = _extract_from_groq_json(text)
        assert isinstance(action, Note)

    def test_handles_pick_up(self):
        text = json.dumps(
            {"thought": "", "action": {"type": "pick_up", "object_id": "kettle_1"}}
        )
        _, action = _extract_from_groq_json(text)
        assert isinstance(action, PickUp)

    def test_invalid_json_raises(self):
        with pytest.raises(LLMParseError, match="not valid JSON"):
            _extract_from_groq_json("not json")

    def test_non_object_json_raises(self):
        with pytest.raises(LLMParseError, match="not an object"):
            _extract_from_groq_json("[1, 2, 3]")

    def test_missing_action_field_raises(self):
        with pytest.raises(LLMParseError, match="missing or invalid 'action'"):
            _extract_from_groq_json(json.dumps({"thought": "x"}))

    def test_action_not_dict_raises(self):
        with pytest.raises(LLMParseError, match="missing or invalid 'action'"):
            _extract_from_groq_json(
                json.dumps({"thought": "x", "action": "move north"})
            )

    def test_invalid_action_payload_raises(self):
        with pytest.raises(LLMParseError, match="could not parse action"):
            _extract_from_groq_json(
                json.dumps(
                    {"thought": "", "action": {"type": "move", "direction": "up"}}
                )
            )

    def test_thought_defaults_to_empty(self):
        text = json.dumps({"action": {"type": "done"}})
        thought, action = _extract_from_groq_json(text)
        assert isinstance(action, Done)
        assert thought == ""


class TestExtractGroqUsage:
    def test_present(self):
        resp = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=80, completion_tokens=15)
        )
        u = _extract_groq_usage(resp)
        assert u.prompt_tokens == 80
        assert u.completion_tokens == 15

    def test_missing(self):
        u = _extract_groq_usage(SimpleNamespace())
        assert u.total == 0


class TestAugmentSystemPromptForJson:
    def test_adds_output_format_section(self):
        out = _augment_system_prompt_for_json("You are a robot.")
        assert "You are a robot." in out
        assert "OUTPUT FORMAT" in out
        assert "thought" in out
        assert "action" in out


# ---------------------------------------------------------------------------
# FakeLLMClient
# ---------------------------------------------------------------------------


class TestFakeLLMClient:
    def test_returns_scripted_action(self):
        client = FakeLLMClient(
            [("Heading north.", {"type": "move", "direction": "north"})]
        )
        obs = make_obs()
        response = client.think(observation=obs)
        assert isinstance(response.action, Move)
        assert response.thought == "Heading north."
        assert response.usage.total == 0
        assert response.latency_ms == 0

    def test_returns_in_order(self):
        client = FakeLLMClient(
            [
                ("a", {"type": "look_around"}),
                ("b", {"type": "done"}),
            ]
        )
        obs = make_obs()
        first = client.think(observation=obs)
        second = client.think(observation=obs)
        assert isinstance(first.action, LookAround)
        assert isinstance(second.action, Done)

    def test_tracks_calls(self):
        client = FakeLLMClient([("x", {"type": "look_around"})])
        obs = make_obs()
        client.think(
            observation=obs,
            recent_history_summaries=["step 0 in kitchen"],
        )
        assert len(client.calls) == 1
        recorded_obs, recorded_history = client.calls[0]
        assert recorded_obs.task == "make tea"
        assert recorded_history == ["step 0 in kitchen"]

    def test_remaining(self):
        client = FakeLLMClient(
            [
                ("a", {"type": "look_around"}),
                ("b", {"type": "done"}),
            ]
        )
        assert client.remaining == 2
        client.think(observation=make_obs())
        assert client.remaining == 1

    def test_raises_when_exhausted(self):
        client = FakeLLMClient([])
        with pytest.raises(LLMError, match="ran out"):
            client.think(observation=make_obs())

    def test_raises_on_invalid_scripted_action(self):
        client = FakeLLMClient(
            [("oops", {"type": "move", "direction": "skyward"})]
        )
        with pytest.raises(Exception):
            client.think(observation=make_obs())


# ---------------------------------------------------------------------------
# make_client (factory)
# ---------------------------------------------------------------------------


class TestMakeClient:
    def test_unknown_provider_raises(self):
        with pytest.raises(LLMConfigError, match="Unknown LLM_PROVIDER"):
            make_client(system_prompt="x", provider="claude")

    def test_gemini_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        with pytest.raises(LLMConfigError, match="GEMINI_API_KEY"):
            make_client(system_prompt="x")

    def test_groq_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        with pytest.raises(LLMConfigError, match="GROQ_API_KEY"):
            make_client(system_prompt="x", provider="groq")

    def test_reads_provider_from_env(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        # Should raise the Groq-specific error, proving Groq was selected.
        with pytest.raises(LLMConfigError, match="GROQ_API_KEY"):
            make_client(system_prompt="x")


# ---------------------------------------------------------------------------
# LLMResponse smoke
# ---------------------------------------------------------------------------


class TestLLMResponse:
    def test_construct(self):
        r = LLMResponse(
            action=Move(direction="north"),  # type: ignore[arg-type]
            thought="t",
            raw_response={},
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
            latency_ms=42,
        )
        assert r.latency_ms == 42
        assert r.usage.total == 2

    def test_is_frozen(self):
        r = LLMResponse(
            action=Move(direction="north"),  # type: ignore[arg-type]
            thought="t",
            raw_response={},
            usage=TokenUsage(),
            latency_ms=1,
        )
        with pytest.raises(Exception):
            r.thought = "new"  # type: ignore[misc]
