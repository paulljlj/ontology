"""Materialize observed CSVs for read-only MCP. Never imports evaluation files."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TABLES = ("cases", "nodes", "links", "services", "routes", "route_hops", "traffic",
          "node_metrics", "link_metrics", "service_metrics", "events")


def prepare(root: Path, runtime: Path, node: str | None = None) -> dict:
    import duckdb
    observed = (root / "observed").resolve()
    if not observed.is_dir():
        raise ValueError("缺少observed输入目录")
    runtime.mkdir(parents=True, exist_ok=True)
    database = runtime / "satellite-observed.duckdb"
    connection = duckdb.connect(str(database))
    try:
        connection.execute("BEGIN TRANSACTION")
        connection.execute("CREATE OR REPLACE TABLE _satellite_sources (name VARCHAR, sha256 VARCHAR, row_count BIGINT)")
        for table in TABLES:
            file = (observed / f"{table}.csv").resolve()
            file.relative_to(observed)
            if not file.is_file():
                raise ValueError(f"缺少观测文件：{table}.csv")
            # Bind filenames, preserve ISO timestamps and explicit blank cells.
            connection.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM read_csv_auto(?, all_varchar=true)', [str(file)])
            count = connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            connection.execute("INSERT INTO _satellite_sources VALUES (?, ?, ?)",
                [table, hashlib.sha256(file.read_bytes()).hexdigest(), count])
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()
    exe = Path(sys.executable).resolve()
    duckdb_server = exe.with_name("mcp-server-motherduck.exe" if sys.platform == "win32" else "mcp-server-motherduck")
    if not duckdb_server.is_file():
        raise ValueError("当前Python环境未安装mcp-server-motherduck入口")
    node_exe = node or shutil.which("node")
    if not node_exe:
        raise ValueError("找不到Node可执行文件，请传--node绝对路径")
    node_path = Path(node_exe).resolve()
    if not node_path.is_file():
        raise ValueError("Node可执行文件不存在")
    node_version = subprocess.run([str(node_path), "--version"], capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    if int(node_version.lstrip("v").split(".")[0]) < 24:
        raise ValueError("Filesystem MCP 2.0.0需要Node 24或更新版本；请传--node绝对路径")
    fs_entry = ROOT / "backend" / "mcp" / "node_modules" / "@modelcontextprotocol" / "server-filesystem" / "dist" / "index.js"
    if not fs_entry.is_file():
        raise ValueError("Filesystem MCP未安装，请先在backend/mcp目录npm ci或npm install")
    artifacts = ROOT / "backend" / "report_artifacts" / "satellite"
    artifacts.mkdir(parents=True, exist_ok=True)
    config = {"default_mode": "mcp", "database": str(database), "dataset_root": str(root.resolve()),
        "note": "本地开源DuckDB MCP查询观测数据，官方Filesystem MCP产出报告；均实际调用并留痕。",
        "servers": {
            "duckdb": {"enabled": True, "transport": "stdio", "command": str(duckdb_server),
                "args": ["--db-path", str(database),
                    "--max-rows", "1000", "--max-chars", "500000", "--query-timeout", "30",
                    "--init-sql", "SET enable_external_access=false; SET allow_community_extensions=false; SET lock_configuration=true;"],
                "allowed_tools": ["execute_query"], "source": "https://github.com/motherduckdb/mcp-server-motherduck",
                "version": "1.0.8", "env": {"PYTHONUTF8": "1", "FASTMCP_CHECK_FOR_UPDATES": "off", "FASTMCP_SHOW_SERVER_BANNER": "false"}},
            "filesystem": {"enabled": True, "transport": "stdio", "command": str(node_path),
                "args": [str(fs_entry), str(artifacts.resolve())], "allowed_tools": ["write_file", "get_file_info"],
                "source": "https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem", "version": "2.0.0"},
        }}
    target = runtime / "mcp-servers.local.json"
    target.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"config": str(target), "database": str(database), "tables": len(TABLES),
        "evaluation_imported": False, "credentials_required": False, "servers": list(config["servers"])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data-output" / "satellite_demo_v1")
    parser.add_argument("--runtime-dir", type=Path, default=ROOT / ".satellite-runtime")
    parser.add_argument("--node")
    args = parser.parse_args()
    print(json.dumps(prepare(args.data_dir, args.runtime_dir, args.node), ensure_ascii=False, indent=2))
