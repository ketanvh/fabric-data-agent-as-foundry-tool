"""Foundry side: agent version management, function-call dispatch, response loop."""

import json
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from openai.types.responses.response_input_param import (
    FunctionCallOutput,
    ResponseInputParam,
)

from . import fabric
from .fabric import FABRIC_DATA_TOOL


def execute_function(name: str, arguments: str) -> str:
    """Dispatch a Foundry function call to the Fabric pass-through."""
    if name != FABRIC_DATA_TOOL.name:
        return json.dumps({"error": f"Unknown function: {name}"})

    parsed = json.loads(arguments)
    return fabric.query_fabric_data_agent(**parsed)


def ensure_agent_has_fabric_tool(
    project_client: AIProjectClient,
    agent_name: str,
) -> None:
    """Publish a version only when the agent is missing the Fabric tool."""
    current = project_client.agents.get(agent_name).versions.latest
    definition = current.definition
    existing_names = {
        getattr(tool, "name", None)
        for tool in (getattr(definition, "tools", None) or [])
    }
    if existing_names == {FABRIC_DATA_TOOL.name}:
        return

    project_client.agents.create_version(
        agent_name=agent_name,
        definition=PromptAgentDefinition(
            model=definition.model,
            instructions=definition.instructions,
            tools=[FABRIC_DATA_TOOL],
        ),
    )


def get_agent_response(
    openai_client: Any,
    conversation_id: str,
    prompt: str,
) -> str:
    """Resolve Foundry function calls until the agent returns final text."""
    response = openai_client.responses.create(
        input=prompt,
        conversation=conversation_id,
    )

    while True:
        function_outputs: ResponseInputParam = []
        for item in response.output:
            if item.type == "function_call":
                function_outputs.append(
                    FunctionCallOutput(
                        type="function_call_output",
                        call_id=item.call_id,
                        output=execute_function(item.name, item.arguments),
                    )
                )

        if not function_outputs:
            return response.output_text

        response = openai_client.responses.create(
            input=function_outputs,
            conversation=conversation_id,
        )
