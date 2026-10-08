import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.exceptions import OutputParserException

from recipe_agent import validator
from recipe_agent.schemas import Assessment
from recipe_agent.state import initial_state


def model_assessment(**extra):
    return Assessment(
        summary="Works",
        unusual=False,
        combination_reason="",
        blocked=False,
        blocking_reason="",
        substitutions=extra.get("substitutions", []),
    )


def test_every_combination_uses_model_with_allergies(monkeypatch):
    structured = MagicMock(ainvoke=AsyncMock(return_value=model_assessment()))
    model = MagicMock()
    model.with_structured_output.return_value = structured
    monkeypatch.setattr(validator, "get_llm", lambda: model)
    state = initial_state(["rice", "peas"], "vegan", ["peanuts"])
    result = asyncio.run(validator.validate_ingredients(state))
    assert not result["assessment"]["unusual"]
    prompt = structured.ainvoke.call_args.args[0][-1].content
    assert "peanuts" in prompt and "vegan" in prompt
    schema = model.with_structured_output.call_args.args[0]
    assert (
        schema["$defs"]["Substitute"]["properties"]["ingredient"]["enum"]
        == state["ingredients"]
    )
    assert model.with_structured_output.call_args.kwargs == {
        "method": "json_schema",
        "strict": True,
    }


def test_model_cannot_substitute_an_invented_original(monkeypatch):
    structured = MagicMock(
        ainvoke=AsyncMock(
            return_value=model_assessment(
                substitutions=[
                    {
                        "ingredient": "invented",
                        "replacement": "oats",
                        "reason": "test",
                        "potential_allergens": [],
                        "required": False,
                    }
                ]
            )
        )
    )
    model = MagicMock()
    model.with_structured_output.return_value = structured
    monkeypatch.setattr(validator, "get_llm", lambda: model)
    with pytest.raises(ValueError, match="Invalid substitution"):
        asyncio.run(validator.validate_ingredients(initial_state(["rice"])))
    assert structured.ainvoke.await_count == 2


def test_malformed_response_is_retried_once(monkeypatch):
    structured = MagicMock(
        ainvoke=AsyncMock(
            side_effect=[
                OutputParserException("Invalid assessment"),
                model_assessment(),
            ]
        )
    )
    model = MagicMock()
    model.with_structured_output.return_value = structured
    monkeypatch.setattr(validator, "get_llm", lambda: model)
    result = asyncio.run(validator.validate_ingredients(initial_state(["rice"])))
    assert result["assessment"]["summary"] == "Works"
    assert structured.ainvoke.await_count == 2


def test_malformed_response_retry_is_bounded(monkeypatch):
    structured = MagicMock(
        ainvoke=AsyncMock(side_effect=OutputParserException("Invalid assessment"))
    )
    model = MagicMock()
    model.with_structured_output.return_value = structured
    monkeypatch.setattr(validator, "get_llm", lambda: model)
    with pytest.raises(OutputParserException):
        asyncio.run(validator.validate_ingredients(initial_state(["rice"])))
    assert structured.ainvoke.await_count == 2


def test_reviewed_optional_swap_is_not_repeated(monkeypatch):
    structured = MagicMock(
        ainvoke=AsyncMock(
            return_value=model_assessment(
                substitutions=[
                    {
                        "ingredient": "rice",
                        "replacement": "quinoa",
                        "reason": "Preference",
                        "potential_allergens": [],
                        "required": False,
                    }
                ]
            )
        )
    )
    model = MagicMock()
    model.with_structured_output.return_value = structured
    monkeypatch.setattr(validator, "get_llm", lambda: model)
    state = initial_state(["rice"])
    state["reviewed_substitutions"] = ["rice"]
    result = asyncio.run(validator.validate_ingredients(state))
    assert result["assessment"]["substitutions"] == []


def proposal(ingredient="rice", replacement="quinoa"):
    return {
        "ingredient": ingredient,
        "replacement": replacement,
        "reason": "Useful swap",
        "potential_allergens": [],
        "required": False,
    }


@pytest.mark.parametrize(
    "bad_proposals",
    [
        [proposal("invented")],
        [proposal(), proposal(replacement="barley")],
        [proposal(replacement=" ")],
        [proposal(replacement="rice")],
    ],
)
def test_semantically_invalid_substitutions_are_corrected_before_review(
    monkeypatch, bad_proposals
):
    structured = MagicMock(
        ainvoke=AsyncMock(
            side_effect=[
                model_assessment(substitutions=bad_proposals),
                model_assessment(substitutions=[proposal()]),
            ]
        )
    )
    model = MagicMock()
    model.with_structured_output.return_value = structured
    monkeypatch.setattr(validator, "get_llm", lambda: model)
    result = asyncio.run(validator.validate_ingredients(initial_state(["rice"])))
    assert result["assessment"]["substitutions"][0]["replacement"] == "quinoa"
    assert structured.ainvoke.await_count == 2
    assert "Problem:" in structured.ainvoke.call_args.args[0][-1].content


def test_quantified_original_is_not_shortened_to_generic_name(monkeypatch):
    original = "a jar of peanut butter"
    structured = MagicMock(
        ainvoke=AsyncMock(
            side_effect=[
                model_assessment(
                    substitutions=[proposal("peanut butter", "sunflower seed butter")]
                ),
                model_assessment(
                    substitutions=[proposal(original, "a jar of sunflower seed butter")]
                ),
            ]
        )
    )
    model = MagicMock()
    model.with_structured_output.return_value = structured
    monkeypatch.setattr(validator, "get_llm", lambda: model)
    state = initial_state([original, "2 chicken breasts"], allergies=["peanuts"])
    result = asyncio.run(validator.validate_ingredients(state))
    assert result["assessment"]["substitutions"][0]["ingredient"] == original
    schema = model.with_structured_output.call_args.args[0]
    assert (
        schema["$defs"]["Substitute"]["properties"]["ingredient"]["enum"]
        == state["ingredients"]
    )


def test_dictionary_response_from_dynamic_schema_is_validated(monkeypatch):
    structured = MagicMock(
        ainvoke=AsyncMock(return_value=model_assessment().model_dump())
    )
    model = MagicMock()
    model.with_structured_output.return_value = structured
    monkeypatch.setattr(validator, "get_llm", lambda: model)
    assert (
        asyncio.run(validator.validate_ingredients(initial_state(["rice"])))[
            "assessment"
        ]["summary"]
        == "Works"
    )


def test_explicit_swap_is_passed_to_model_and_cannot_be_silently_omitted(monkeypatch):
    structured = MagicMock(
        ainvoke=AsyncMock(
            side_effect=[
                model_assessment(),
                model_assessment(substitutions=[proposal()]),
            ]
        )
    )
    model = MagicMock()
    model.with_structured_output.return_value = structured
    monkeypatch.setattr(validator, "get_llm", lambda: model)
    state = initial_state(["rice"], substitution_requests=["rice"])
    result = asyncio.run(validator.validate_ingredients(state))
    assert result["assessment"]["substitutions"][0]["ingredient"] == "rice"
    assert structured.ainvoke.await_count == 2
    assert (
        '"substitution_requests": ["rice"]'
        in structured.ainvoke.call_args.args[0][1].content
    )


def test_no_viable_requested_substitute_can_require_editing(monkeypatch):
    blocked = model_assessment()
    blocked.blocked = True
    blocked.blocking_reason = "No suitable substitute for the requested role."
    structured = MagicMock(ainvoke=AsyncMock(return_value=blocked))
    model = MagicMock()
    model.with_structured_output.return_value = structured
    monkeypatch.setattr(validator, "get_llm", lambda: model)
    result = asyncio.run(
        validator.validate_ingredients(
            initial_state(["rice"], substitution_requests=["rice"])
        )
    )
    assert result["assessment"]["blocked"]
    assert structured.ainvoke.await_count == 1
