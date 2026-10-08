import asyncio
from types import SimpleNamespace

from conftest import assessment
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import recipe_agent.graph as workflow
from recipe_agent import chef
from recipe_agent.state import initial_state


def test_actual_chef_forwards_each_chunk_and_only_approved_ingredients(monkeypatch):
    prompts = []

    class Model:
        async def astream(self, messages):
            prompts.extend(messages)
            yield SimpleNamespace(content="# Dinner")
            await asyncio.sleep(0)
            yield SimpleNamespace(content="\nUse rice.")

    async def analyze(state):
        return {"assessment": assessment(), "flow_action": "continue"}

    monkeypatch.setattr(chef, "get_llm", lambda temperature: Model())
    monkeypatch.setattr(workflow, "validate_ingredients", analyze)

    async def run():
        graph = workflow.build_graph(InMemorySaver())
        cfg = {"configurable": {"thread_id": "chef-test"}}
        paused = await graph.ainvoke(initial_state(["rice"], "vegan", ["sesame"]), cfg)
        assert paused["__interrupt__"] and not prompts
        streamed = [
            item
            async for item in graph.astream(
                Command(resume={"action": "generate"}), cfg, stream_mode="custom"
            )
        ]
        tokens = [item["text"] for item in streamed if item["type"] == "token"]
        assert tokens == ["# Dinner", "\nUse rice."]
        assert (await graph.aget_state(cfg)).values["recipe"] == "".join(tokens)

    asyncio.run(run())
    assert '"approved_ingredients": ["rice"]' in prompts[-1].content
    assert "sesame" in prompts[-1].content
