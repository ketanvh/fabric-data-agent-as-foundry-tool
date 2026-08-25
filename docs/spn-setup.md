# Fabric data agent + service principal (SPN): setup guide

End-to-end setup for calling a **published Microsoft Fabric data agent** from outside Fabric
using a **Microsoft Entra service principal** over the **MCP endpoint**.

Three different admin roles are involved. If one person doesn't hold all three, note who owns
each part before starting:

| Part | Who does it | Role needed |
| --- | --- | --- |
| Part 1 — Register the SPN | Entra admin | Cloud Application Administrator (or higher) |
| Part 2 — Enable Fabric API access | Fabric tenant admin | Fabric Administrator |
| Part 3 — Grant workspace + data access | Workspace owner | Workspace **Admin** or **Member** |

---

## Prerequisites

- A paid **F2 or higher** Fabric capacity, or **Power BI Premium P1 or higher** with Fabric enabled.
- **Cross-geo processing and cross-geo storing for AI** enabled, per the Fabric data agent tenant settings.
- At least one supported data source with data: warehouse, lakehouse, Power BI semantic model,
  KQL database, mirrored database, or ontology.
- The data agent must be **published**. The MCP endpoint returns an error until it is.

> **Capacity note.** You do **not** grant an SPN access to a Fabric capacity. There is no such
> assignment. The capacity requirement is satisfied by the *workspace* being assigned to an
> eligible capacity. All SPN permissions are granted at the **workspace** and **data source** levels.

### Known limitations

- **Managed identities are not supported.** You must use a service principal.
- **SPN authentication is not supported for data agents connected to a KQL database (Kusto).**
  Check your agent's data sources before starting.
- Sharing the data agent item alone is **not** sufficient — the SPN needs read access to every
  underlying data source.

---

## Part 1 — Register the service principal in Microsoft Entra ID

1. Sign in to the [Microsoft Entra admin center](https://entra.microsoft.com) as at least a
   **Cloud Application Administrator**.
2. Go to **Entra ID** > **App registrations** > **New registration**.
3. Give it a name, for example `fabric-data-agent-spn`.
4. Under **Supported account types**, select **Accounts in this organizational directory only**.
5. Select **Register**.
6. From the app's **Overview** page, copy and keep:
    - **Application (client) ID**
    - **Directory (tenant) ID**
7. Add a credential under **Certificates & secrets**. In order of preference:
    - **Certificate** (recommended)
    - **Federated identity credential** (no stored secret; good for CI/CD)
    - **Client secret** (simplest; copy the value immediately — it is shown only once)

> If you can't register applications yourself, ask your Entra admin for the **App ID**,
> **credential**, and **tenant ID**.

### Recommended: create a security group now

Part 2 lets you scope Fabric API access to a security group rather than the whole organization.
Creating the group now avoids a rerun later, and it is the more common enterprise choice:

1. In Entra, go to **Groups** > **New group**.
2. Type: **Security**. Name it, for example `fabric-api-service-principals`.
3. Add your service principal (search by its **application display name**) as a **member**.

---

## Part 2 — Enable service principals to use Fabric APIs

Performed by a **Fabric tenant administrator**. Without this, the SPN cannot call Fabric at all.

1. Open the **Fabric admin portal** > **Tenant settings**.
2. Find **Developer settings** > **Service principals can use Fabric APIs**.
3. Turn it **on**.
4. Set the scope:
   - **The entire organization**, or
   - **Specific security groups** — select the group from Part 1.
5. **Apply**.

> **Tenant setting changes can take up to an hour to propagate.** If something fails immediately
> after this step, wait before assuming it's misconfigured.

---

## Part 3 — Grant the SPN access to the workspace

Performed by a workspace **Admin** or **Member**.

1. Open the workspace that hosts the data agent in Fabric.
2. Select **Manage access**.
3. Select **Add people or groups**.
4. Search for the service principal **by its application display name** — not the client ID.
5. Assign a role:
   - **Contributor** or **Member** — sufficient for querying the data agent.
   - **Admin** — only if the SPN must also manage the workspace.

### If the SPN doesn't appear in the picker

This is the most common snag. Work through these in order:

- **Search by display name, not client ID.** The picker matches on name.
- **Confirm Part 2 is enabled** and, if scoped to a group, that this SPN is a member of it.
  This is the usual culprit.
- **Verify the enterprise application exists.** An app registration creates a service principal
  object in the same tenant; check **Entra ID > Enterprise applications**.
- **Confirm you are a workspace Member or Admin.** Viewers and Contributors can't grant access.
- **Wait for propagation** — both the tenant setting and new Entra objects take time.
- **Confirm the same tenant.** The app must live in the tenant that hosts Fabric.

---

## Part 4 — Grant the SPN read access to every data source

The data agent runs queries **under the calling identity**. The SPN sees only what it can access,
even though the agent itself was shared with it.

For each data source attached to the agent — lakehouse, warehouse, semantic model, mirrored
database, ontology — grant the SPN at least **read** access.

> **Symptom of missing this step:** the agent responds successfully but reports that it has no
> data, can't see any tables, or returns empty results. That's a data-source permission gap, not
> an authentication failure.

For a Power BI semantic model, **Read** permission is enough to query it through a data agent.

---

## Part 5 — Collect the endpoint details

1. Open the published data agent > **Settings** > **Model Context Protocol** tab.
2. Copy the **MCP server URL**. (You can also download `mcp.json` here for VS Code.)

Or build the URL yourself:

```
https://api.fabric.microsoft.com/v1/mcp/workspaces/{WorkspaceId}/dataagents/{DataAgentId}/agent
```

| Placeholder | Description |
| --- | --- |
| `{WorkspaceId}` | ID of the workspace containing the data agent |
| `{DataAgentId}` | ID of the published data agent |

A manually built URL works **only after the agent is published**.

---

## Part 6 — Authenticate and call

The SPN uses the **client credentials flow** to get a token, then sends it as a bearer token.

**Token scope:** `https://api.fabric.microsoft.com/.default`

> **Scope discrepancy, worth knowing.** The Microsoft SPN article references
> `https://analysis.windows.net/powerbi/api/.default` for the Fabric resource, while the MCP
> article specifies `https://api.fabric.microsoft.com/.default`. The Fabric scope is the one that
> matches the MCP endpoint host and is confirmed working. If you get a 401 despite correct
> permissions, try the other scope.

Requirements:

- **Python 3.10 or later** (the `mcp` package requires it).
- `pip install mcp azure-identity`

Working client: see `fabric_data_agent_spn_mcp.py` (script) or `fabric_data_agent_spn.ipynb`
(notebook, uses top-level `await` instead of `asyncio.run`).

Minimal shape:

```python
from azure.identity import ClientSecretCredential

credential = ClientSecretCredential(
    tenant_id=TENANT_ID, client_id=CLIENT_ID, client_secret=CLIENT_SECRET
)
token = credential.get_token("https://api.fabric.microsoft.com/.default")
headers = {"Authorization": f"Bearer {token.token}"}
```

Then connect over MCP streamable HTTP, run `initialize`, `tools/list`, and `tools/call`. The agent
exposes exactly **one** tool, whose input schema is:

```json
{"type": "object", "properties": {"userQuestion": {"type": "string"}}, "required": ["userQuestion"]}
```

There is **no conversation or thread parameter** — each call is independent. To get
playground-style follow-ups, your client must keep the history and fold prior turns into
`userQuestion`. Note that re-sending history costs input tokens on every turn.

> **Never hardcode the client secret**, especially in a notebook — notebooks persist source *and*
> outputs to disk. Use environment variables, `getpass`, or Azure Key Vault.

---

## Verification checklist

Run through this in order; each step isolates a different failure.

1. **Token acquires** — `credential.get_token(...)` returns without error. Fails → Entra
   credentials wrong or expired.
2. **Endpoint reachable, tool listed** — `list_tools()` returns one tool. Fails → see the error
   table below.
3. **Agent answers** — `call_tool` returns text.
4. **Agent sees data** — ask "what tables are available?" A successful answer with no data means
   a data-source permission gap (Part 4).

### Error reference

| Symptom | Likely cause |
| --- | --- |
| `401 Unauthorized` | Part 2 not enabled, SPN not in the scoped security group, wrong scope, or bad/expired credential |
| `403 Forbidden` | SPN lacks workspace access (Part 3) or data source access (Part 4) |
| `404 Not Found` | Agent not published, or wrong workspace/agent ID |
| Answers, but "no data" / no tables | Data source permissions missing (Part 4) |
| SPN missing from **Manage access** picker | See the troubleshooting list in Part 3 |
| Changes not taking effect | Tenant settings take up to an hour |
| `ImportError: cannot import name 'streamablehttp_client'` | `mcp` 2.x renamed it to `streamable_http_client` and dropped the `headers=` argument |
| `RuntimeError: asyncio.run() cannot be called from a running event loop` | In a notebook — use top-level `await`, not `asyncio.run()` |

---

## A note on which API to use

Use the **MCP endpoint** for querying. Microsoft's own SDK documentation is explicit that the
Fabric data agent SDK (`fabric-data-agent-sdk`) is a **management-plane** tool — create,
configure, publish, evaluate — and that runtime querying goes through MCP.

The older published-URL path built on the **OpenAI Assistants API** shuts down **2026-08-26**.
Only the *querying* portion of the SDK is affected; creating, configuring, and publishing are
unchanged.

---

## Reference

- [Use service principal authentication with Fabric data agent](https://learn.microsoft.com/en-us/fabric/data-science/data-agent-service-principal)
- [Data agent as Model Context Protocol server](https://learn.microsoft.com/en-us/fabric/data-science/data-agent-mcp-server)
- [Fabric data agent Python SDK](https://learn.microsoft.com/en-us/fabric/data-science/fabric-data-agent-sdk)
- [Service principals in Microsoft Fabric](https://learn.microsoft.com/en-us/fabric/data-warehouse/service-principals)
- [Create a Microsoft Entra application and service principal](https://learn.microsoft.com/en-us/entra/identity-platform/howto-create-service-principal-portal)
