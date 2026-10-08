import pytest

import recipe_agent.graph as workflow


def assessment(**changes):
    return {
        "summary": "These ingredients work together.",
        "unusual": False,
        "combination_reason": "",
        "blocked": False,
        "blocking_reason": "",
        "substitutions": [],
        **changes,
    }


@pytest.fixture
def fake_provider(monkeypatch):
    calls = {"analysis": [], "generation": []}
    outcomes = []

    async def analyze(state):
        calls["analysis"].append(dict(state))
        return {
            "assessment": outcomes.pop(0) if outcomes else assessment(),
            "flow_action": "continue",
        }

    async def generate(state):
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        calls["generation"].append(dict(state))
        for text in ["# A good meal\n", "Cook the approved ingredients."]:
            writer({"type": "token", "text": text})
        return {"recipe": "# A good meal\nCook the approved ingredients."}

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(workflow, "validate_ingredients", analyze)
    monkeypatch.setattr(workflow, "generate_recipe", generate)
    return calls, outcomes
