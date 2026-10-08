from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Substitute(BaseModel):
    ingredient: str = Field(description="Exact ingredient from the supplied list")
    replacement: str
    reason: str
    potential_allergens: list[str]
    required: bool = Field(
        description="True if original conflicts with an allergy or strict diet"
    )


class Assessment(BaseModel):
    summary: str
    unusual: bool
    combination_reason: str
    blocked: bool = Field(
        description="True for dangerous/non-food ingredients or unresolved allergies"
    )
    blocking_reason: str
    substitutions: list[Substitute]


class IngredientsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ingredients: list[str] = Field(min_length=1, max_length=40)
    preferences: str = Field(default="", max_length=2000)
    allergies: list[str] = Field(default_factory=list, max_length=30)
    substitution_requests: list[str] = Field(default_factory=list, max_length=40)

    @field_validator("ingredients", "allergies", "substitution_requests")
    @classmethod
    def clean_list(cls, value):
        cleaned = list(
            dict.fromkeys(item.strip().lower() for item in value if item.strip())
        )
        if any(len(item) > 120 for item in cleaned):
            raise ValueError("Each item must be at most 120 characters.")
        return cleaned

    @field_validator("ingredients")
    @classmethod
    def require_ingredients(cls, value):
        if not value:
            raise ValueError("Please enter at least one ingredient.")
        return value

    @model_validator(mode="after")
    def valid_substitution_requests(self):
        if not set(self.substitution_requests).issubset(self.ingredients):
            raise ValueError("Choose substitutions from your ingredient list.")
        return self


class SubstituteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ingredient: str
    accept: bool
    allergy_confirmed: bool = False


class ReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_id: str
    action: Literal["keep", "edit", "substitutions", "generate"]
    revision: IngredientsRequest | None = None
    decisions: list[SubstituteDecision] = Field(default_factory=list, max_length=40)


def validate_response(answer: ReviewResponse, review: dict):
    if answer.review_id != review["review_id"]:
        raise ValueError("This review has changed. Refresh the session.")
    if answer.action == "edit":
        if answer.revision is None:
            raise ValueError("Revised ingredients are required.")
        return
    expected = {
        "combination": "keep",
        "substitutions": "substitutions",
        "confirmation": "generate",
    }
    if expected.get(review["kind"]) != answer.action:
        raise ValueError("This action is not available at the current step.")
    if review["kind"] == "substitutions":
        proposals = {p["ingredient"]: p for p in review["substitutions"]}
        decisions = {d.ingredient: d for d in answer.decisions}
        if (
            len(decisions) != len(answer.decisions)
            or decisions.keys() != proposals.keys()
        ):
            raise ValueError("Please review every suggested substitute exactly once.")
        for ingredient, decision in decisions.items():
            if decision.accept and not decision.allergy_confirmed:
                raise ValueError(
                    "Confirm allergy suitability for every accepted substitute."
                )
            if not decision.accept and proposals[ingredient]["required"]:
                raise ValueError(
                    "This replacement is required. Edit your ingredients or allergies to continue."
                )
