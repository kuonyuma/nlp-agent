# Tool Runtime

Pro_NLP uses one catalog and one execution path for Coordinator and Worker tools.
The model-visible tool list and the executable tool list always come from the same
immutable `ToolSet` grant.

## Built-in and custom tools

Built-ins are registered with a validated `ToolDescriptor`. Custom Python modules
can be listed under `tools.custom.modules`; each module exports `TOOLS` or
`get_tools()`. Installed packages can publish tools through the
`nlp_agent.tools` entry-point group. Duplicate names are startup errors.

Every custom provider must also declare `TOOL_MANIFEST` (or be configured under
`tools.custom.manifests`). The manifest supplies the provider id, version,
category, model-facing display priority, scopes, capabilities and risk. A
provider may return a `BaseTool` or a `ToolDescriptor`; the manifest remains
the authorization baseline in both cases.

```python
from langchain_core.tools import StructuredTool

TOOL_MANIFEST = {
    "id": "nlp-analysis-tools",
    "version": "1.0",
    "category": "nlp",
    "prompt_priority": 200,
    "scopes": ["worker"],
    "capabilities": ["nlp.analyze"],
    "risk": "low",
}

async def extract_entities(text: str) -> dict:
    return {"entities": []}

TOOLS = [StructuredTool.from_function(
    coroutine=extract_entities,
    name="nlp_extract_entities",
    description="从文本中提取实体",
)]
```

NLP custom tools must use the `nlp_` prefix. MCP tools are always namespaced as
`mcp_<server>_<tool>`. Source collisions are intentionally fail-closed: custom
tools never silently replace built-ins, other custom tools, or MCP tools.

`prompt_priority` only determines the deterministic order shown to the model;
it never grants permissions or changes collision behavior. Higher values appear
first, then built-in/custom/MCP source order and tool name break ties.

Every input schema should be a Pydantic v2 model. Validation, timeout handling,
concurrency limits, permission errors, and tool failures are normalized by the
central executor.

## Coordinator and Worker policy

`tools.policies` in `configs/agent_config.yaml` controls role-level grants and
denials. Worker Profiles combine Skills, explicit tools, and capability names.
Skills contain SOP instructions and requirements; they do not execute tools or
act as a second permission system.

When a Worker starts, its resolved grant is written to metadata as `toolGrant`.
A resumed Worker restores exactly that grant. Newly added global permissions do
not silently broaden an existing Worker.

## MCP

MCP servers support `stdio`, `sse`, and `streamable_http`. Discovered tools are
namespaced as `mcp_<server>_<tool>` and retain their original JSON Schema. Use
`enabled_tools` to allow all (`["*"]`) or select raw/namespaced tool names.

Remote MCP URLs reject private and special network addresses by default. For a
trusted local server, opt in explicitly with `allow_private_network: true`.
Connections are owned by the runtime, closed during application shutdown, and
retried once after a transport failure.

Example:

```yaml
tools:
  mcp_servers:
    filesystem:
      transport: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", ".data"]
      enabled_tools: ["read_file"]
      scopes: [worker]
```
