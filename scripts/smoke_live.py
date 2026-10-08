r"""Manual integration check against the running API; uses real Groq calls.

Run from the root: .\.venv\Scripts\python.exe scripts/smoke_live.py [API_BASE_URL]
All inputs and allergy confirmations below are synthetic test data.
"""

import json
import sys
import time

import httpx

sys.stdout.reconfigure(encoding="utf-8")
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")


def send(client, path, payload):
    started = time.monotonic()
    records = []
    token_times = []
    with client.stream("POST", BASE + path, json=payload) as response:
        response.raise_for_status()
        assert "text/event-stream" in response.headers["content-type"]
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            assert event["type"] != "error", event
            records.append(event)
            if event["type"] == "token":
                token_times.append(time.monotonic() - started)
    if token_times:
        print(
            f"Stream: {len(token_times)} chunks; first at {token_times[0]:.2f}s, last at {token_times[-1]:.2f}s"
        )
        assert len(token_times) > 1
        assert token_times[0] < token_times[-1]
    return records


with httpx.Client(timeout=180) as client:
    print("Health:", client.get(BASE + "/health").json())
    scenarios = [
        {
            "ingredients": ["pasta", "tomatoes", "garlic", "olive oil"],
            "preferences": "Quick vegetarian dinner",
        },
        {
            "ingredients": ["milk", "rice", "cinnamon"],
            "preferences": "Dairy-free rice pudding. Replace milk.",
            "allergies": ["milk"],
        },
        {
            "ingredients": ["milk", "rice", "cinnamon"],
            "preferences": "Rice pudding",
            "substitution_requests": ["milk"],
        },
    ]
    for scenario in scenarios:
        print("\nInput:", scenario)
        data = send(client, "/api/sessions", scenario)
        sid = next(e["session_id"] for e in data if e["type"] == "session")
        reviewed_swap = False
        for _ in range(8):
            pending = next((e["review"] for e in data if e["type"] == "review"), None)
            if pending is None:
                assert data[-1]["type"] == "done"
                print(
                    "Completed:",
                    data[-1]["ingredients"],
                    "; recipe characters:",
                    len(data[-1]["recipe"]),
                )
                restored = client.get(f"{BASE}/api/sessions/{sid}")
                restored.raise_for_status()
                assert restored.json()["recipe"] == data[-1]["recipe"]
                break
            print("Review:", pending["kind"], pending["message"])
            assert not client.get(f"{BASE}/api/sessions/{sid}").json()["recipe"]
            payload = {"review_id": pending["review_id"]}
            if pending["kind"] == "combination":
                payload["action"] = "keep"
            elif pending["kind"] == "substitutions":
                reviewed_swap = True
                print("Proposals:", pending["substitutions"])
                decisions = [
                    {
                        "ingredient": p["ingredient"],
                        "accept": True,
                        "allergy_confirmed": False,
                    }
                    for p in pending["substitutions"]
                ]
                rejected = client.post(
                    f"{BASE}/api/sessions/{sid}/respond",
                    json=payload | {"action": "substitutions", "decisions": decisions},
                )
                assert rejected.status_code == 422
                payload |= {
                    "action": "substitutions",
                    "decisions": [d | {"allergy_confirmed": True} for d in decisions],
                }
            elif pending["kind"] == "confirmation":
                payload["action"] = "generate"
            else:
                raise AssertionError(f"Unexpected block: {pending}")
            data = send(client, f"/api/sessions/{sid}/respond", payload)
        else:
            raise AssertionError("Too many review rounds")
        if scenario.get("allergies") or scenario.get("substitution_requests"):
            assert reviewed_swap
    unusual = send(
        client, "/api/sessions", {"ingredients": ["fish", "chocolate syrup", "onions"]}
    )
    review = next(e["review"] for e in unusual if e["type"] == "review")
    print("\nCreative-combination assessment:", review["kind"], review["message"])
    print("\nLive integration checks passed.")
