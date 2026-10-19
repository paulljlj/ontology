"""Allowlisted real MCP calls, with discoverable schemas and execution traces.

Configuration is administrator-controlled. Neither the HTTP API nor diagnosis
JSON can provide an executable, server URL, tool name, or arbitrary SQL.
"""
from __future__ import annotations
import hashlib
import json
import os
import time
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any

from jsonschema import Draft202012Validator
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def describe_exception(exc: BaseException) -> str:
    nested = getattr(exc, "exceptions", None)
    if nested:
        return "; ".join(describe_exception(child) for child in nested)[:2000]
    return str(exc) or type(exc).__name__


def _safe_arguments(arguments: dict) -> dict:
    result = {}
    for key, value in arguments.items():
        if any(word in key.lower() for word in ("password", "secret", "token", "authorization")):
            result[key] = "[redacted]"
        elif key == "content":
            raw = str(value).encode("utf-8")
            result[key] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        else:
            result[key] = str(value)[:1500] if isinstance(value, str) else value
    return result


def decode_result(result: Any) -> Any:
    if getattr(result, "isError", False):
        raise RuntimeError("MCP工具返回错误：" + str([getattr(c, "text", "") for c in result.content])[:1200])
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured
    blocks = []
    for block in result.content:
        content = getattr(block, "text", None)
        if content is None:
            raise ValueError("本流程仅接受MCP结构化/文本结果，不接受不可验证的媒体结果")
        try:
            blocks.append(json.loads(content))
        except (ValueError, TypeError):
            blocks.append(content)
    return blocks[0] if len(blocks) == 1 else blocks


class McpGateway:
    def __init__(self, servers: dict[str, dict], timeout_seconds: float = 45):
        self.servers = servers
        self.timeout_seconds = timeout_seconds
        self.stack = AsyncExitStack()
        self.sessions: dict[str, ClientSession] = {}
        self.schemas: dict[tuple[str, str], dict] = {}
        self.calls: list[dict] = []
        self.discovered: list[dict] = []

    async def __aenter__(self):
        await self.stack.__aenter__()
        return self

    async def __aexit__(self, *exc):
        return await self.stack.__aexit__(*exc)

    async def connect(self, name: str) -> ClientSession:
        if name in self.sessions:
            return self.sessions[name]
        config = self.servers.get(name)
        if not config or not config.get("enabled"):
            raise ValueError(f"MCP Server未启用：{name}")
        if config.get("transport", "stdio") != "stdio":
            raise ValueError("首版只接本地stdio Server；不擅自访问外部MCP地址")
        command = config.get("command", "")
        if not command or not os.path.isabs(command):
            raise ValueError("MCP启动命令必须为管理员配置的绝对可执行路径")
        params = StdioServerParameters(command=command, args=config.get("args", []),
            env={"PYTHONIOENCODING": "utf-8", **config.get("env", {})}, cwd=config.get("cwd"))
        # The SDK's session timeout handles individual messages. Do not use a
        # cross-task asyncio timeout to exit an AnyIO stdio cancel scope.
        read, write = await self.stack.enter_async_context(stdio_client(params))
        session = await self.stack.enter_async_context(ClientSession(read, write,
            read_timeout_seconds=timedelta(seconds=self.timeout_seconds)))
        await session.initialize()
        response = await session.list_tools()
        allowed = set(config.get("allowed_tools", []))
        found = set()
        for tool in response.tools:
            if tool.name in allowed:
                found.add(tool.name)
                self.schemas[(name, tool.name)] = tool.inputSchema
                self.discovered.append({"server": name, "tool": tool.name, "input_schema": tool.inputSchema,
                    "source": config.get("source", ""), "version": config.get("version", "")})
        if allowed - found:
            raise ValueError(f"MCP Server缺少已约定工具：{sorted(allowed - found)}")
        self.sessions[name] = session
        return session

    async def call(self, server: str, tool: str, arguments: dict) -> Any:
        config = self.servers.get(server, {})
        if tool not in config.get("allowed_tools", []):
            raise ValueError(f"MCP工具不在允许清单：{server}/{tool}")
        call = {"server": server, "tool": tool, "arguments": _safe_arguments(arguments),
            "source": config.get("source", ""), "version": config.get("version", ""), "status": "running"}
        started = time.monotonic()
        try:
            session = await self.connect(server)
            Draft202012Validator(self.schemas[(server, tool)]).validate(arguments)
            result = decode_result(await session.call_tool(tool, arguments=arguments))
            call.update(status="succeeded", result_sha256=hashlib.sha256(json.dumps(result, ensure_ascii=False, default=str).encode()).hexdigest())
            return result
        except BaseException as exc:
            call.update(status="failed", error=describe_exception(exc)[:1200])
            raise
        finally:
            call["duration_ms"] = round((time.monotonic() - started) * 1000, 2)
            self.calls.append(call)
