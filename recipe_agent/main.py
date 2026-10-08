"""Optional CLI using the same approval workflow as the website."""

import asyncio
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from recipe_agent.graph import build_graph
from recipe_agent.schemas import IngredientsRequest, ReviewResponse, validate_response
from recipe_agent.state import initial_state


def read_ingredients():
    ingredients = input("Ingredients (comma separated): ").split(",")
    return IngredientsRequest(
        ingredients=ingredients,
        preferences=input("Preferences (optional): ").strip(),
        allergies=[
            a
            for a in input("Allergies (optional, comma separated): ").split(",")
            if a.strip()
        ],
        substitution_requests=[
            i
            for i in input(
                "Ingredients to replace (optional; copy their full entries, comma separated): "
            ).split(",")
            if i.strip()
        ],
    )


def read_answer(review):
    print(f"\nChef: {review['message']}")
    print("Ingredients: " + ", ".join(review["ingredients"]))
    if review["kind"] == "blocked" or input("Edit ingredients? (y/N): ").lower() in {
        "yes",
        "y",
    }:
        return ReviewResponse(
            review_id=review["review_id"], action="edit", revision=read_ingredients()
        )
    if review["kind"] == "combination":
        return ReviewResponse(review_id=review["review_id"], action="keep")
    if review["kind"] == "confirmation":
        if input("Generate with these ingredients? (y/N): ").lower() not in {
            "y",
            "yes",
        }:
            return ReviewResponse(
                review_id=review["review_id"],
                action="edit",
                revision=read_ingredients(),
            )
        return ReviewResponse(review_id=review["review_id"], action="generate")
    decisions = []
    for p in review["substitutions"]:
        print(f"{p['ingredient']} → {p['replacement']}: {p['reason']}")
        print(
            "Potential allergens: "
            + (", ".join(p["potential_allergens"]) or "Check labels")
        )
        accept = input("Use this substitute? (y/N): ").lower() in {"y", "yes"}
        safe = accept and input(
            "No known allergy to this substitute, and labels checked? (y/N): "
        ).lower() in {"y", "yes"}
        decisions.append(
            {"ingredient": p["ingredient"], "accept": accept, "allergy_confirmed": safe}
        )
    return ReviewResponse(
        review_id=review["review_id"], action="substitutions", decisions=decisions
    )


async def run():
    print("=== Pantry Recipe Assistant ===")
    data = read_ingredients()
    graph = build_graph(InMemorySaver())
    config = {"configurable": {"thread_id": str(uuid4())}, "recursion_limit": 60}
    value = initial_state(
        data.ingredients, data.preferences, data.allergies, data.substitution_requests
    )
    while True:
        pending = None
        async for mode, event in graph.astream(
            value, config, stream_mode=["custom", "updates"]
        ):
            if mode == "custom":
                if event["type"] == "token":
                    print(event["text"], end="", flush=True)
                elif event["type"] == "status":
                    print("\n" + event["message"])
            elif "__interrupt__" in event:
                paused = event["__interrupt__"][0]
                pending = paused.value | {"review_id": paused.id}
        if pending is None:
            print("\nRecipe complete.")
            return
        while True:
            answer = read_answer(pending)
            try:
                validate_response(answer, pending)
                break
            except ValueError as exc:
                print(exc)
        value = Command(resume=answer.model_dump())


def main():
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, EOFError):
        print("\nGoodbye.")


if __name__ == "__main__":
    main()
