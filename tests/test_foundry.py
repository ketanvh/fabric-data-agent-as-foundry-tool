import json

from foundry_fabric_demo import fabric
from foundry_fabric_demo.foundry import execute_function


def test_execute_function_forwards_the_question(monkeypatch) -> None:
    questions: list[str] = []

    def fake_query(userQuestion: str) -> str:
        questions.append(userQuestion)
        return "Sales were $42M."

    monkeypatch.setattr(fabric, "query_fabric_data_agent", fake_query)

    result = execute_function(
        "query_fabric_data_agent",
        json.dumps({"userQuestion": "What were total sales last quarter?"}),
    )

    assert result == "Sales were $42M."
    assert questions == ["What were total sales last quarter?"]


def test_execute_function_rejects_unknown_tools() -> None:
    result = execute_function("unknown", "{}")

    assert json.loads(result) == {"error": "Unknown function: unknown"}
