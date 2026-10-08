from typing import TypedDict


class RecipeState(TypedDict, total=False):
    ingredients: list[str]
    user_preferences: str
    allergies: list[str]
    substitution_requests: list[str]
    assessment: dict
    reviewed_substitutions: list[str]
    approved_combination: list[str]
    flow_action: str
    recipe: str


def initial_state(
    ingredients, preferences="", allergies=None, substitution_requests=None
):
    return RecipeState(
        ingredients=ingredients,
        user_preferences=preferences,
        allergies=allergies or [],
        substitution_requests=substitution_requests or [],
        reviewed_substitutions=[],
        approved_combination=[],
        recipe="",
        flow_action="continue",
    )
