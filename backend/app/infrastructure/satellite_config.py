"""Isolated settings; never rewrites the existing project's .env."""
from __future__ import annotations
import json
import os
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = WORKSPACE_ROOT / "backend"


def data_root() -> Path:
    return Path(os.environ.get("SATELLITE_DATA_ROOT", WORKSPACE_ROOT / "data-output" / "satellite_demo_v1")).resolve()


def artifact_root() -> Path:
    return Path(os.environ.get("SATELLITE_ARTIFACT_ROOT", BACKEND_ROOT / "report_artifacts" / "satellite")).resolve()


def mcp_config() -> dict:
    filename = Path(os.environ.get("SATELLITE_MCP_CONFIG", WORKSPACE_ROOT / ".satellite-runtime" / "mcp-servers.local.json"))
    if not filename.is_file():
        return {"default_mode": "file", "servers": {}, "note": "未配置外部MCP；当前为明确标注的本地文件模式。"}
    result = json.loads(filename.read_text(encoding="utf-8-sig"))
    if result.get("default_mode", "file") not in {"file", "mcp"}:
        raise ValueError("MCP default_mode必须为file或mcp")
    return result


def mcp_public_status() -> dict:
    config = mcp_config()
    servers = [{"name": name, "enabled": bool(s.get("enabled")), "transport": s.get("transport", "stdio"),
            "tools": list(s.get("allowed_tools", [])), "status": "configured_not_probed" if s.get("enabled") else "disabled",
            "source": s.get("source", ""), "version": s.get("version", "")}
            for name, s in config.get("servers", {}).items()]
    binary = os.environ.get("NEO4J_MCP_BIN", "")
    neo4j_enabled = bool(binary and Path(binary).is_file() and os.environ.get("NEO4J_MCP_URI"))
    servers.append({"name": "neo4j", "enabled": neo4j_enabled, "transport": "stdio",
        "tools": ["get-schema", "read-cypher"],
        "status": "configured_not_probed" if neo4j_enabled else "disabled",
        "source": "https://github.com/neo4j/mcp", "version": "1.6.0"})
    return {"default_mode": config.get("default_mode", "file"), "note": config.get("note", ""),
        "servers": servers}
