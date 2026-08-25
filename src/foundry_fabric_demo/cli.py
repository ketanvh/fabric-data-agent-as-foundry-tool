"""Interactive command-line demo."""

import os

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

from .fabric import close_fabric_client
from .foundry import ensure_agent_has_fabric_tool, get_agent_response


def main() -> None:
    load_dotenv()
    project_endpoint = os.environ["PROJECT_ENDPOINT"]
    agent_name = os.environ.get("AGENT_NAME", "SimpleAgent")

    with DefaultAzureCredential() as foundry_credential:
        project_client = AIProjectClient(
            endpoint=project_endpoint,
            credential=foundry_credential,
        )
        ensure_agent_has_fabric_tool(project_client, agent_name)
        openai_client = project_client.get_openai_client(agent_name=agent_name)
        conversation = openai_client.conversations.create()

        print("Chat started. Type 'end' to stop.")
        try:
            while True:
                user_input = input("You: ").strip()
                if user_input.casefold() == "end":
                    break
                if not user_input:
                    continue

                answer = get_agent_response(
                    openai_client,
                    conversation.id,
                    user_input,
                )
                print(f"Agent: {answer}")
        except (EOFError, KeyboardInterrupt):
            print()
        finally:
            close_fabric_client()
            openai_client.conversations.delete(
                conversation_id=conversation.id
            )