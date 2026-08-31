from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.identity import ClientSecretCredential
import os
from pathlib import Path

from dotenv import load_dotenv

def chat_with_agent():
    TENANT_ID = os.environ["TENANT_ID"]
    CLIENT_ID = os.environ["FABRIC_SPN_CLIENT_ID"]
    CLIENT_SECRET = os.environ["FABRIC_SPN_CLIENT_SECRET"]
    PROJECT_ENDPOINT = os.environ["PROJECT_ENDPOINT"]
    # This is Azure Agent having Fabric data agent as a tool. Make sure .env file has correct information
    AGENT_NAME = os.environ.get("AGENT_NAME","Fabric-Agent") 

    credentals = DefaultAzureCredential()

    client_credentials = ClientSecretCredential(
                tenant_id=TENANT_ID,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
            )
    
    project = AIProjectClient(
        endpoint=PROJECT_ENDPOINT,
        credential=client_credentials,
    )

    openai_client = project.get_openai_client(agent_name=AGENT_NAME)
    conversation = openai_client.conversations.create()
    print(f"Chat started with agent:{AGENT_NAME} with conversation ID: {conversation.id}. Type 'end' to stop.")

    try:
        while True:
            user_input = input("You: ").strip()
            if user_input.casefold() == "end":
                break
            if not user_input:
                continue

            response = openai_client.responses.create(
                conversation=conversation.id,
                input=user_input,
            )
            print(f"Agent: {response.output_text}")


    except (EOFError, KeyboardInterrupt):
        print()

if __name__ == "__main__":
    env_path = Path(__file__).resolve().parent.parent / "../.env"
    print(env_path)
    load_dotenv(env_path)
    chat_with_agent()
