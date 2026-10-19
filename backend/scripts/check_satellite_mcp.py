"""Probe the two real open-source MCP servers without any model or credentials."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.infrastructure.mcp_gateway import McpGateway
from app.infrastructure.satellite_config import artifact_root, mcp_config


async def main():
    config = mcp_config()
    async with McpGateway(config["servers"]) as gateway:
        rows = await gateway.call("duckdb", "execute_query", {"sql": "SELECT node_id, node_type, forwarding_capacity_mbps FROM nodes ORDER BY node_id LIMIT 3"})
        print(json.dumps({"sample_query_result": rows}, ensure_ascii=False, default=str))
        folder = artifact_root() / "mcp-smoke"
        folder.mkdir(parents=True, exist_ok=True)
        file = folder / "mcp-probe.json"
        written = await gateway.call("filesystem", "write_file", {"path": str(file), "content": json.dumps({"probe": "real MCP tool call", "query_result": rows}, ensure_ascii=False)})
        info = await gateway.call("filesystem", "get_file_info", {"path": str(file)})
        print(json.dumps({"written": written, "file_info": info, "calls": gateway.calls,
            "tools": [{"server": t["server"], "tool": t["tool"]} for t in gateway.discovered]}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
