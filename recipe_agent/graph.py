from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from recipe_agent.chef import generate_recipe
from recipe_agent.state import RecipeState, initial_state
from recipe_agent.validator import validate_ingredients


async def analyze(state):
    get_stream_writer()(
        {
            "type": "status",
            "message": "Checking pairings, preferences and possible substitutions…",
        }
    )
    return await validate_ingredients(state)


def revision(answer):
    data = answer["revision"]
    return initial_state(
        data["ingredients"],
        data["preferences"],
        data["allergies"],
        data.get("substitution_requests", []),
    ) | {"flow_action": "recheck"}


def review_payload(state, kind, **extra):
    return {
        "kind": kind,
        "ingredients": state["ingredients"],
        "preferences": state["user_preferences"],
        "allergies": state["allergies"],
        "substitution_requests": state.get("substitution_requests", []),
        **extra,
    }


def review_combination(state):
    assessment = state["assessment"]
    if assessment["blocked"]:
        answer = interrupt(
            review_payload(state, "blocked", message=assessment["blocking_reason"])
        )
        return revision(answer)
    if assessment["unusual"] and state["approved_combination"] != state["ingredients"]:
        answer = interrupt(
            review_payload(
                state, "combination", message=assessment["combination_reason"]
            )
        )
        if answer["action"] == "edit":
            return revision(answer)
        return {"approved_combination": state["ingredients"], "flow_action": "continue"}
    return {"flow_action": "continue"}


def review_substitutions(state):
    proposals = state["assessment"]["substitutions"]
    if not proposals:
        return {"flow_action": "continue"}
    answer = interrupt(
        review_payload(
            state,
            "substitutions",
            substitutions=proposals,
            message="Review each substitute and confirm whether you can eat it.",
        )
    )
    if answer["action"] == "edit":
        return revision(answer)
    decisions = {d["ingredient"]: d for d in answer["decisions"]}
    replacements = {
        p["ingredient"]: p["replacement"]
        for p in proposals
        if decisions[p["ingredient"]]["accept"]
    }
    ingredients = list(
        dict.fromkeys(replacements.get(i, i) for i in state["ingredients"])
    )
    reviewed = list(
        dict.fromkeys(
            state["reviewed_substitutions"]
            + list(decisions)
            + list(replacements.values())
        )
    )
    return {
        "ingredients": ingredients,
        "reviewed_substitutions": reviewed,
        "substitution_requests": [
            i for i in state.get("substitution_requests", []) if i not in decisions
        ],
        "flow_action": "recheck" if replacements else "continue",
    }


def confirm(state):
    answer = interrupt(
        review_payload(state, "confirmation", message=state["assessment"]["summary"])
    )
    if answer["action"] == "edit":
        return revision(answer)
    return {"flow_action": "continue"}


def build_graph(checkpointer):
    builder = StateGraph(RecipeState)
    builder.add_node("analyze", analyze)
    builder.add_node("combination", review_combination)
    builder.add_node("substitutions", review_substitutions)
    builder.add_node("confirmation", confirm)
    builder.add_node("chef", generate_recipe)
    builder.add_edge(START, "analyze")
    builder.add_edge("analyze", "combination")
    for node, following in [
        ("combination", "substitutions"),
        ("substitutions", "confirmation"),
        ("confirmation", "chef"),
    ]:
        builder.add_conditional_edges(
            node,
            lambda s: s["flow_action"],
            {"recheck": "analyze", "continue": following},
        )
    builder.add_edge("chef", END)
    return builder.compile(checkpointer=checkpointer)
