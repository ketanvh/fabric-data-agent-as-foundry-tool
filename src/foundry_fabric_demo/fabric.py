"""Fabric side: MCP client, session lifecycle, and Foundry function-tool schema."""

import asyncio
import os
import threading
import time
from contextlib import AsyncExitStack
from typing import Any, Coroutine

from azure.ai.projects.models import FunctionTool
from azure.core.credentials import AccessToken
from azure.identity import ClientSecretCredential
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client


FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"


FABRIC_DATA_TOOL = FunctionTool(
    name="query_fabric_data_agent",
    description=(
        "Answers questions about enterprise data by passing a natural-language "
        "question to a Microsoft Fabric data agent. Pass plain English, not SQL, "
        "DAX, table names, or column names."
    ),
    parameters={
        "type": "object",
        "properties": {
            "userQuestion": {
                "type": "string",
                "description": "A single, self-contained business question.",
            }
        },
        "required": ["userQuestion"],
        "additionalProperties": False,
    },
    strict=True,
)


def _root_cause(exception: BaseException) -> str:
    while isinstance(exception, BaseExceptionGroup) and exception.exceptions:
        exception = exception.exceptions[0]
    return f"{type(exception).__name__}: {exception}"


class FabricDataAgentClient:
    """Keep one Fabric MCP session alive for synchronous Foundry tool calls."""

    def __init__(self) -> None:
        tenant_id = os.environ["TENANT_ID"]
        client_id = os.environ["FABRIC_SPN_CLIENT_ID"]
        client_secret = os.environ["FABRIC_SPN_CLIENT_SECRET"]
        workspace_id = os.environ["FABRIC_WORKSPACE_ID"]
        data_agent_id = os.environ["FABRIC_DATA_AGENT_ID"]

        self._mcp_url = (
            "https://api.fabric.microsoft.com/v1/mcp/workspaces/"
            f"{workspace_id}/dataagents/{data_agent_id}/agent"
        )
        self._credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )
        self._token: AccessToken | None = None
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._tool_name: str | None = None
        self._question_argument: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None:
            return self._loop

        ready = threading.Event()

        def run_loop() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            ready.set()
            loop.run_forever()

        self._thread = threading.Thread(target=run_loop, name="fabric-mcp", daemon=True)
        self._thread.start()
        ready.wait()
        if self._loop is None:
            raise RuntimeError("Fabric MCP event loop did not start")
        return self._loop

    def _run(self, coroutine: Coroutine[Any, Any, str | None]) -> str | None:
        return asyncio.run_coroutine_threadsafe(
            coroutine, self._ensure_loop()
        ).result()

    async def _open(self) -> None:
        self._token = self._credential.get_token(FABRIC_SCOPE)
        headers = {"Authorization": f"Bearer {self._token.token}"}
        stack = AsyncExitStack()
        try:
            http_client = await stack.enter_async_context(
                create_mcp_http_client(headers=headers)
            )
            read_stream, write_stream = await stack.enter_async_context(
                streamable_http_client(self._mcp_url, http_client=http_client)
            )
            session = await stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()
            tools = (await session.list_tools()).tools
            if not tools:
                raise RuntimeError("Fabric data agent exposed no MCP tools")

            tool = tools[0]
            properties = tool.input_schema.get("properties", {})
            if not properties:
                raise RuntimeError("Fabric MCP tool has no input property")

            self._tool_name = tool.name
            self._question_argument = next(iter(properties))
            self._session = session
            self._stack = stack
        except BaseException:
            await stack.aclose()
            raise

    async def _close_session(self) -> None:
        stack = self._stack
        self._stack = None
        self._session = None
        if stack is not None:
            await stack.aclose()

    async def _ensure_session(self) -> None:
        token_expiring = (
            self._token is None or self._token.expires_on <= time.time() + 60
        )
        if self._session is None or token_expiring:
            await self._close_session()
            await self._open()

    async def _query(self, question: str) -> str:
        await self._ensure_session()
        if not self._session or not self._tool_name or not self._question_argument:
            raise RuntimeError("Fabric MCP session was not initialized")

        try:
            result = await self._session.call_tool(
                self._tool_name, {self._question_argument: question}
            )
        except BaseException:
            await self._close_session()
            await self._open()
            if not self._session or not self._tool_name or not self._question_argument:
                raise RuntimeError("Fabric MCP session could not be reopened")
            result = await self._session.call_tool(
                self._tool_name, {self._question_argument: question}
            )

        return "\n".join(
            block.text for block in result.content if block.type == "text"
        )

    def query(self, question: str) -> str:
        try:
            return self._run(self._query(question)) or ""
        except BaseException as exception:
            return f"Fabric query failed: {_root_cause(exception)}"

    def close(self) -> None:
        if self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._close_session(), self._loop
            ).result(timeout=5)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread is not None:
                self._thread.join(timeout=5)
            self._credential.close()
            self._loop = None
            self._thread = None


_client: FabricDataAgentClient | None = None


def query_fabric_data_agent(userQuestion: str) -> str:
    """Lazy pass-through to the Fabric data agent MCP tool."""
    global _client
    if _client is None:
        _client = FabricDataAgentClient()
    return _client.query(userQuestion)


def close_fabric_client() -> None:
    """Idempotent cleanup; safe to call whether or not the tool was ever invoked."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
