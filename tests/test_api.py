import json
import time

import pytest
from conftest import assessment
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.storage import SESSION_TTL


def events(response):
    assert response.status_code == 200, response.text
    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def start(client, ingredients=None):
    data = events(
        client.post(
            "/api/sessions", json={"ingredients": ingredients or ["rice", "peas"]}
        )
    )
    sid = next(e["session_id"] for e in data if e["type"] == "session")
    review = next(e["review"] for e in data if e["type"] == "review")
    return sid, review, data


def answer(client, sid, review, action, **extra):
    return client.post(
        f"/api/sessions/{sid}/respond",
        json={"review_id": review["review_id"], "action": action, **extra},
    )


def test_normal_flow_waits_for_approval_and_streams(fake_provider):
    calls, _ = fake_provider
    with TestClient(create_app()) as client:
        sid, review, data = start(client)
        assert review["kind"] == "confirmation"
        assert not calls["generation"]
        assert not any(e["type"] == "token" for e in data)
        generated = events(answer(client, sid, review, "generate"))
        assert len([e for e in generated if e["type"] == "token"]) == 2
        assert generated[-1]["type"] == "done"
        assert len(calls["generation"]) == 1
        assert client.get(f"/api/sessions/{sid}").json()["recipe"]
        assert answer(client, sid, review, "generate").status_code == 409


def test_unusual_can_be_kept_but_needs_final_approval(fake_provider):
    calls, outcomes = fake_provider
    outcomes.append(
        assessment(unusual=True, combination_reason="These flavors are unusual.")
    )
    with TestClient(create_app()) as client:
        sid, review, _ = start(client)
        assert review["kind"] == "combination"
        assert answer(client, sid, review, "generate").status_code == 422
        next_review = events(answer(client, sid, review, "keep"))[-1]["review"]
        assert next_review["kind"] == "confirmation"
        assert not calls["generation"]
        assert answer(client, sid, review, "keep").status_code == 422
        events(answer(client, sid, next_review, "generate"))
        assert calls["generation"]


def test_revised_ingredients_are_rechecked(fake_provider):
    calls, outcomes = fake_provider
    outcomes.append(assessment(unusual=True, combination_reason="Unusual"))
    with TestClient(create_app()) as client:
        sid, review, _ = start(client)
        result = events(
            answer(
                client,
                sid,
                review,
                "edit",
                revision={"ingredients": ["tomato", "pasta"], "allergies": ["sesame"]},
            )
        )
        next_review = result[-1]["review"]
        assert next_review["ingredients"] == ["tomato", "pasta"]
        assert next_review["allergies"] == ["sesame"]
        assert len(calls["analysis"]) == 2
        assert not calls["generation"]


def test_allergy_confirmation_and_required_swaps_enforced(fake_provider):
    calls, outcomes = fake_provider
    outcomes.append(
        assessment(
            substitutions=[
                {
                    "ingredient": "milk",
                    "replacement": "oat drink",
                    "reason": "Dairy preference",
                    "potential_allergens": ["oats"],
                    "required": True,
                }
            ]
        )
    )
    with TestClient(create_app()) as client:
        sid, review, _ = start(client, ["milk", "rice"])
        assert review["kind"] == "substitutions"
        for decisions in [
            [],
            [{"ingredient": "milk", "accept": True}],
            [{"ingredient": "milk", "accept": False}],
            [{"ingredient": "milk", "accept": True, "allergy_confirmed": True}] * 2,
        ]:
            assert (
                answer(
                    client, sid, review, "substitutions", decisions=decisions
                ).status_code
                == 422
            )
        data = events(
            answer(
                client,
                sid,
                review,
                "substitutions",
                decisions=[
                    {"ingredient": "milk", "accept": True, "allergy_confirmed": True}
                ],
            )
        )
        final = data[-1]["review"]
        assert final["ingredients"] == ["oat drink", "rice"]
        assert len(calls["analysis"]) == 2
        assert not calls["generation"]
        events(answer(client, sid, final, "generate"))
        assert calls["generation"][0]["ingredients"] == ["oat drink", "rice"]


def test_optional_substitute_can_be_declined(fake_provider):
    calls, outcomes = fake_provider
    outcomes.append(
        assessment(
            substitutions=[
                {
                    "ingredient": "rice",
                    "replacement": "quinoa",
                    "reason": "More protein",
                    "potential_allergens": [],
                    "required": False,
                }
            ]
        )
    )
    with TestClient(create_app()) as client:
        sid, review, _ = start(client)
        final = events(
            answer(
                client,
                sid,
                review,
                "substitutions",
                decisions=[{"ingredient": "rice", "accept": False}],
            )
        )[-1]["review"]
        assert final["ingredients"] == ["rice", "peas"]
        assert not calls["generation"]


def test_replacement_combination_requires_new_review(fake_provider):
    calls, outcomes = fake_provider
    outcomes.extend(
        [
            assessment(
                substitutions=[
                    {
                        "ingredient": "rice",
                        "replacement": "quinoa",
                        "reason": "Useful",
                        "potential_allergens": [],
                        "required": False,
                    }
                ]
            ),
            assessment(unusual=True, combination_reason="New combination"),
        ]
    )
    with TestClient(create_app()) as client:
        sid, review, _ = start(client)
        final = events(
            answer(
                client,
                sid,
                review,
                "substitutions",
                decisions=[
                    {"ingredient": "rice", "accept": True, "allergy_confirmed": True}
                ],
            )
        )[-1]["review"]
        assert final["kind"] == "combination"
        assert not calls["generation"]


def test_blocked_ingredients_cannot_be_approved(fake_provider):
    calls, outcomes = fake_provider
    outcomes.append(assessment(blocked=True, blocking_reason="Not food."))
    with TestClient(create_app()) as client:
        sid, review, _ = start(client)
        assert review["kind"] == "blocked"
        assert answer(client, sid, review, "keep").status_code == 422
        assert answer(client, sid, review, "generate").status_code == 422
        assert not calls["generation"]


@pytest.mark.parametrize("ingredients", [[], ["   "], ["a" * 121], ["rice"] * 41])
def test_input_validation(fake_provider, ingredients):
    with TestClient(create_app()) as client:
        assert (
            client.post("/api/sessions", json={"ingredients": ingredients}).status_code
            == 422
        )


def test_sessions_are_isolated_busy_and_expire(fake_provider):
    app = create_app()
    with TestClient(app) as client:
        first, review, _ = start(client, ["rice"])
        second, _, _ = start(client, ["potatoes"])
        events(answer(client, first, review, "generate"))
        assert client.get(f"/api/sessions/{second}").json()["recipe"] == ""
        app.state.sessions[second].busy = True
        other_review = app.state.sessions[second].pending
        assert answer(client, second, other_review, "generate").status_code == 409
        app.state.sessions[second].touched = time.monotonic() - SESSION_TTL - 1
        assert client.get(f"/api/sessions/{second}").status_code == 404


def test_missing_key_is_actionable(fake_provider, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")
    with TestClient(create_app()) as client:
        assert (
            client.post("/api/sessions", json={"ingredients": ["rice"]}).status_code
            == 503
        )


def test_provider_failure_does_not_generate(fake_provider, monkeypatch):
    import recipe_agent.graph as workflow

    async def failing(state):
        raise RuntimeError("private provider diagnostics")

    monkeypatch.setattr(workflow, "validate_ingredients", failing)
    with TestClient(create_app()) as client:
        data = events(client.post("/api/sessions", json={"ingredients": ["rice"]}))
        assert data[-1]["type"] == "error"
        assert "private provider diagnostics" not in data[-1]["message"]
        assert not fake_provider[0]["generation"]


def test_invalid_assessment_has_specific_browser_error(fake_provider, monkeypatch):
    import recipe_agent.graph as workflow
    from recipe_agent.errors import InvalidIngredientAssessment

    async def failing(state):
        raise InvalidIngredientAssessment("private model response")

    monkeypatch.setattr(workflow, "validate_ingredients", failing)
    with TestClient(create_app()) as client:
        data = events(client.post("/api/sessions", json={"ingredients": ["rice"]}))
        assert data[-1]["type"] == "error"
        assert "inconsistent ingredient suggestions" in data[-1]["message"]
        assert "Groq configuration" not in data[-1]["message"]
        sid = data[0]["session_id"]
        assert client.get(f"/api/sessions/{sid}").json()["error"] == data[-1]["message"]
        assert not fake_provider[0]["generation"]


def test_requested_swap_round_trip_requires_review_and_is_consumed(fake_provider):
    calls, outcomes = fake_provider
    outcomes.append(
        assessment(
            substitutions=[
                {
                    "ingredient": "milk",
                    "replacement": "oat drink",
                    "reason": "Requested swap",
                    "potential_allergens": ["oats"],
                    "required": False,
                }
            ]
        )
    )
    with TestClient(create_app()) as client:
        data = events(
            client.post(
                "/api/sessions",
                json={
                    "ingredients": ["milk", "rice"],
                    "substitution_requests": ["Milk"],
                },
            )
        )
        sid = data[0]["session_id"]
        review = data[-1]["review"]
        assert review["kind"] == "substitutions"
        assert review["substitution_requests"] == ["milk"]
        assert client.get(f"/api/sessions/{sid}").json()["substitution_requests"] == [
            "milk"
        ]
        assert calls["analysis"][0]["substitution_requests"] == ["milk"]
        assert not calls["generation"]
        assert (
            answer(
                client,
                sid,
                review,
                "substitutions",
                decisions=[{"ingredient": "milk", "accept": True}],
            ).status_code
            == 422
        )
        final = events(
            answer(
                client,
                sid,
                review,
                "substitutions",
                decisions=[
                    {
                        "ingredient": "milk",
                        "accept": True,
                        "allergy_confirmed": True,
                    }
                ],
            )
        )[-1]["review"]
        assert final["ingredients"] == ["oat drink", "rice"]
        assert final["substitution_requests"] == []
        assert calls["analysis"][-1]["substitution_requests"] == []
        events(answer(client, sid, final, "generate"))
        assert calls["generation"][0]["ingredients"] == ["oat drink", "rice"]


def test_edit_can_request_a_swap_at_final_confirmation(fake_provider):
    calls, outcomes = fake_provider
    with TestClient(create_app()) as client:
        sid, review, _ = start(client, ["milk", "rice"])
        outcomes.append(
            assessment(
                substitutions=[
                    {
                        "ingredient": "milk",
                        "replacement": "oat drink",
                        "reason": "Requested swap",
                        "potential_allergens": ["oats"],
                        "required": False,
                    }
                ]
            )
        )
        revised = events(
            answer(
                client,
                sid,
                review,
                "edit",
                revision={
                    "ingredients": ["milk", "rice"],
                    "substitution_requests": ["milk"],
                },
            )
        )[-1]["review"]
        assert revised["kind"] == "substitutions"
        assert calls["analysis"][-1]["substitution_requests"] == ["milk"]
        assert not calls["generation"]


def test_requested_swap_can_be_declined_without_a_repeat_loop(fake_provider):
    calls, outcomes = fake_provider
    outcomes.append(
        assessment(
            substitutions=[
                {
                    "ingredient": "rice",
                    "replacement": "quinoa",
                    "reason": "Requested swap",
                    "potential_allergens": [],
                    "required": False,
                }
            ]
        )
    )
    with TestClient(create_app()) as client:
        data = events(
            client.post(
                "/api/sessions",
                json={"ingredients": ["rice"], "substitution_requests": ["rice"]},
            )
        )
        sid = data[0]["session_id"]
        review = data[-1]["review"]
        final = events(
            answer(
                client,
                sid,
                review,
                "substitutions",
                decisions=[{"ingredient": "rice", "accept": False}],
            )
        )[-1]["review"]
        assert final["kind"] == "confirmation"
        assert final["ingredients"] == ["rice"]
        assert final["substitution_requests"] == []
        assert not calls["generation"]


def test_unknown_substitution_target_is_rejected(fake_provider):
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/sessions",
            json={"ingredients": ["rice"], "substitution_requests": ["milk"]},
        )
        assert response.status_code == 422
        assert not fake_provider[0]["analysis"]
