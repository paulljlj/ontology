# Neo4j MCP（诊断关系查询，可选）

自动诊断默认使用明确标注的本地时态图，开箱即可运行。若要展示真实开源 MCP，选择前端的“Neo4j MCP”前必须完成以下准备；连接失败会直接报错，不会伪装成本地成功。

1. 安装 Docker，设置私有环境变量 `NEO4J_PASSWORD`，在本目录执行 `docker compose up -d`。
2. 安装项目后端依赖，设置 `NEO4J_MCP_URI`、`NEO4J_MCP_USERNAME`、`NEO4J_MCP_PASSWORD`。
3. 从官方 `neo4j/mcp` v1.6.0 Release 下载当前系统架构的二进制；不要把二进制、密码或数据库卷提交到仓库。设置 `NEO4J_MCP_BIN` 为其绝对路径。
4. 从仓库根执行图导入：

   ```powershell
   Set-Location backend
   python -m satellite_diagnosis import-graph
   ```

5. 先显式运行实时集成测试，再在前端选择该模式：

   ```powershell
   $env:SATELLITE_MCP_INTEGRATION='1'
   Set-Location backend
   python -m pytest tests/satellite_diagnosis_module/test_live_mcp.py -v
   ```

本模块只使用 Server 暴露的 `get-schema` 与 `read-cypher`；要求 `NEO4J_MCP_READ_ONLY=true`，并检查 `write-cypher` 未暴露。图中只导入节点、链路、业务、路由与跳点关系，服务指标仍由观测白名单读取。当前仓库未附带第三方可执行文件；使用者应从官方发布页获取并遵守其许可证。
