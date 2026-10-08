from unittest.mock import MagicMock

from recipe_agent import tools


def test_previously_hardcoded_ingredient_calls_llm(monkeypatch):
    model = MagicMock()
    model.invoke.return_value.content = (
        "Suggested alternatives, with potential allergens."
    )
    monkeypatch.setattr(tools, "get_llm", lambda: model)
    result = tools.find_ingredient_substitutions.invoke({"ingredient": "peanut butter"})
    assert "Suggested alternatives" in result
    model.invoke.assert_called_once()
