# 接手入口：卫星场景协作演示 fengongdemo1

更新日期：2026-10-19。仓库：`paulljlj/ontology`；交接分支：`fengongdemo1`。

这是给换账号、换会话或新同学的完整接手说明。先读本文件，再看代码；不要把早期方案、PPT或数据生成器答案当成当前系统已经实现的功能。

## 1. 我们到底在做什么

原项目是本体驱动的任务执行MVP：从用户需求得到需求约定与计划，每个步骤有task_key、skill_spec，执行器通过已注册处理器调用真实Python能力/工具，保存状态、证据与产物，再展示和下载数据报告。

新场景是卫星网络服务分析：发现多个业务的可用度下降后，检查它们在当时共同依赖哪些卫星、地面站或链路，结合指标和告警提出原因候选、关注轻微持续下降，并评估是否有满足约束的备选通信路径。

目标不是预先认定“某颗卫星坏了”。候选也可以是地面站、链路或容量瓶颈。服务可用度不是AI可信度，更不等于硬件健康度。现阶段全用合成文件数据，不接真实设备控制；复杂因果模型暂不作为首版前提。

最终报告六部分：异常概况；根因候选与异常原因；潜在或轻微异常；备选通信路径；影响与对照；结论与待补证据。

## 2. 当前权威分工（不要沿用旧方案）

| 负责人 | 独立负责 | 当前状态 |
| --- | --- | --- |
| 我们 / A / 当前仓库维护方 | 备选路径计算、本体类/关系/约束、任务编排、MCP统一接入、API、前端报告、下载和联调 | 本分支已有可运行首版 |
| 同学 / B | 异常概况、根因候选与原因、潜在或轻微异常、影响与正常对照、结论与缺失证据 | 已发分工；本仓库尚未收到她的实际诊断代码/结果 |

我们也已经实现了系统侧文件适配器；B仍可直接使用同一套CSV独立开发，不依赖我们的前端/数据库/OWL环境。B不用重做路径算法。不要把两个人安排成“必须等A做完，B才能开始”。

导师希望体现MCP：先查有没有合适的开源Server，通用查询/文件能力优先复用；卫星专用判断没有现成工具时补Python。不是为了凑数量把每个函数伪装成开源MCP。

### 已发给B的交付要求

B从CSV独立分析，先终端运行，输出结构化JSON；每项原因判断可对应具体指标、时间或告警。交付：

- `.py`代码，可调用函数；Python版本和依赖清单。
- 运行示例、JSON示例、测试代码与测试说明。
- 若用了MCP，提供Server版本、启动配置和工具调用示例。
- `evaluation/`只用于独立测试核对，不作为分析输入。

推荐函数边界：`analyze(data_dir, case_id, analysis_start, analysis_end, as_of) -> dict`。这只是建议函数名；对接以诊断JSON Schema为准。

## 3. 已完成什么、尚未完成什么

已完成：

1. 详细模拟数据、字段说明、演示规则、完整11CSV、答案隔离与数据一致性检查；现在把纯Node生成器和通用Python校验器也纳入版本控制。
2. 新增9个具体本体类、2个抽象父类、9种关系、数值类型检查，已同步导出`engineering.owl`。保留原Goal、Spec、Plan、Task等通用模型。
3. 文件与真实MCP时点快照；按case_id、路由生效时间、采样区间和证据可获时间过滤；核对CSV哈希；不填造缺失值。
4. 有向备选路径搜索、容量联合预留与回溯验算；同时检查迁移业务和共享资源的未迁移业务时延；固定业务源与允许出口，检查接触窗口；不声称全局最优。
5. 六步执行链，外部诊断存在时加第七步；skill_spec实际绑定注册处理器；步骤/错误/工具调用/文件哈希可追踪；重复执行不污染已完成终态。
6. 新卫星工作台、案例和历史选择、网络拓扑、路径前后与资源负载、六部分报告、证据弹窗、JSON/可阅读HTML下载；旧经营报表入口保留。
7. 两个真实开源MCP：本地DuckDB查询、官方Filesystem产物写入/核对；有真实SDK连接/工具发现/调用日志，不只是标签。
8. 给B的诊断Schema、开发样例、校验和页面接收入口。

尚未完成：

- B的真实诊断：异常数量、下降幅度/持续时间、原因比较、轻微风险和正常对照。
- 真实卫星数据接入、真实故障答案、正式准确率评估、切换后实测和真实控制。
- 贝叶斯网络、PCMCI+、反事实或分类模型；这些只是后续研究，不要向导师说已经做了。
- 任意自然语言自动生成新Python算法/工具。卫星首版是按已注册能力形成场景化小计划；requirement保留要求，但不自由改写算法。

没有诊断时，报告对应部分明确“待接入”。人工输入SAT-20仅表示“试着避开它验算路径”，不是系统找出的根因；即便路径可行也不等于故障已解决。

## 4. 数据集完整说明

目录：`data-output/satellite_demo_v1/`。42颗卫星、3个地面站、126条有向链路；8个独立案例；每例18个端到端业务；11CSV共201,206行、约32MB原始文件。固定种子20260915。

| 文件 | 用途 |
| --- | --- |
| observed/cases.csv | 案例、采样/分析窗、基线和证据截止时间，无预设根因标签 |
| observed/nodes.csv | 45个节点、类型与额定能力 |
| observed/links.csv | 有向链路、带宽、传播时延和模拟接触窗口 |
| observed/services.csv | 18个业务的源、允许出口、SLA与探测口径 |
| observed/routes.csv | 分案例、业务和生效区间的路由版本 |
| observed/route_hops.csv | 路由有序节点及下一跳链路 |
| observed/traffic.csv | 每分钟源端请求流量 |
| observed/node_metrics.csv | 节点容量、到达/转发/丢弃、队列、电压、环境与设备计数 |
| observed/link_metrics.csv | 链路状态、有效容量、流量、SNR与误码 |
| observed/service_metrics.csv | 端到端服务可用度、探测、交付流量、丢包和时延 |
| observed/events.csv | 告警、计划切换、维护/数据质量及信息发布时间 |
| demo_rules.json | 可配置演示阈值和约束，不是行业标准 |
| 字段说明.md / data_dictionary.json | 字段、单位、空值、关联键与CSV哈希 |
| manifest.json / validation_report.json | 完整性元数据、生成器一致性检查；不是诊断准确率 |
| evaluation/ | 注入答案、参考改路与派生检查，仅用于显式验收，禁止运行诊断读取 |

采样区间为北京时间`[2026-09-15 09:30, 11:31)`，每分钟1点，121点；最后timestamp=11:30。基线`[09:30,10:00)`，首轮分析`[10:00,10:15)`，末条采样10:14覆盖至10:15；初诊证据截止10:16。必须同时考虑样本完整结束和available_at，不能用故障后恢复记录做“事先诊断”。

CSV有UTF-8 BOM，空值不等于0，有向链路不能反向使用，不可混合不同case的时间线。`.gitattributes`关闭这些CSV的Git换行转换，保留manifest字节哈希。

可用度=成功探测数/有效探测总数×100；99%到92%下降7个百分点。演示重大异常为相对可比基线下降严格>5个百分点且连续3个有效点；关注为下降1–5个百分点且持续10点并结合负载/设备证据。具体以demo_rules.json和B实现/测试为准，不能把这些拟用规则说成已有诊断算法。

环境计数、辐射相关设备错误、接触窗口和时延全部是简化合成场景，不是星历、空间环境或射频物理仿真。生成器参考可用度提升不是当前路径模块预测结果；现有模块不预测改路后可用度。

## 5. 换账号/新克隆如何跑

### Windows最短路径（Python3.12 + Node>=24 + Git + npm）

```powershell
git clone --branch fengongdemo1 --single-branch https://github.com/paulljlj/ontology.git
Set-Location ontology
python backend/scripts/verify_satellite_dataset.py
```

若是在原电脑同一目录切换GPT账号，已有环境/配置仍在，可直接` .\start-satellite.ps1 `或按运行文档传现有Python/Node绝对路径。不要因为换了账号就删除工作区或重新覆盖数据。

新电脑/新目录需要首次安装（联网下载公开依赖，不需要LLM/MotherDuck/API密钥）：

```powershell
# 传入本机Python3.12、Node24及npm；已经在PATH上时可省略参数。
.\bootstrap-satellite.ps1 -Python 'C:\path\to\python.exe' -Node 'C:\path\to\node.exe' -Npm 'C:\path\to\npm.cmd'
.\start-satellite.ps1
```

bootstrap只在`.satellite-runtime/app`创建后端环境，在`.satellite-runtime/python`创建MCP服务环境，并安装两个npm目录、验证数据、生成观测DuckDB和本机MCP配置。不会安装到共享Conda环境，不读取/上传`.env`，不启动真实设备控制。开始前需要本机已有Python、Node、npm；执行策略阻止脚本时请让用户自行选择合适执行方式，不擅自修改系统策略。

本机地址：前端<http://127.0.0.1:5174>，API<http://127.0.0.1:8001/docs>。隔离SQLite为`.satellite-runtime/preview.db`；关闭飞书和真实LLM，旧数据库及`.env`不变；只监听本机，未加用户鉴权，不要直接公网部署。停止用` .\stop-satellite.ps1 `，只核对并停止本次预览进程，保留数据库和报告。

如果只想先试路径计算，后端纯路径CLI不需要MCP、数据库和LLM：

```powershell
python backend/scripts/satellite_route_demo.py --case CASE-001 --avoid SAT-20
```

Linux/macOS请按`docs/卫星路径模块_运行与联调.md`所述结构手工创建两个环境；MCP完整锁含Windows专用依赖，不直接套用到其他平台。当前首要复现目标是Windows/Python3.12。bootstrap是此次新增的准备脚本，发布前验证语法和组成命令；不要把已有手工环境的成功说成“已在全新机器自动安装成功”。

### 实际MCP与完整链路

```powershell
.\.satellite-runtime\app\Scripts\python.exe backend/scripts/check_satellite_mcp.py
.\.satellite-runtime\app\Scripts\python.exe backend/scripts/satellite_workflow_demo.py --case CASE-001 --avoid SAT-20
```

MCP母进程用后端Python；prepare脚本用隔离MCP Python，避免混装。`requirements-satellite.txt`固定新增关键SDK版本；`backend/mcp/python-runtime.lock`是另一套完整服务端锁（不能装进FastAPI后端）。

MCP配置不进Git：新目录必须重新运行prepare/bootstrap生成绝对路径。没有配置时为明确file模式，不是假装成功的MCP；已配置的MCP运行出错则失败，不暗降级。DuckDB只含11个observed表，禁止外部文件/扩展；Filesystem仅允许报告目录。服务是本地stdio，不连接MotherDuck云。

Server版本：mcp-server-motherduck1.0.8、duckdb1.5.5、官方Filesystem2.0.0；客户端MCP SDK1.29.0；官方Filesystem需要Node>=24。

## 6. 系统代码导航与真实流程

| 文件 | 重点 |
| --- | --- |
| backend/app/domain/ontology.py、engineering.owl | Satellite、GroundStation、CommunicationLink、Route、NetworkService、MetricObservation、AlarmEvent、NetworkSnapshot、RouteProposal；9种关系 |
| backend/app/domain/reasoner.py、satellite_rules.py | OWL派生字段/关系校验、有限数值、类型/端点/时间/容量约束；不是用Pellet计算最短路或证明因果 |
| backend/app/domain/satellite_schemas.py | 对B的DiagnosisInput、EvidenceReference、CauseCandidate；运行参数SatelliteRunCreate |
| backend/app/infrastructure/satellite_data.py | 严格allowlist文件与时点快照、缺失和时间边界 |
| backend/app/infrastructure/satellite_mcp_data.py | 真实SQL结果替换当前快照，校验来源哈希/行数/结构/时间，不以文件结果冒充MCP结果 |
| backend/app/infrastructure/mcp_gateway.py | SDK stdio连接、initialize/list_tools、允许清单、JSONSchema参数校验、调用证据 |
| backend/app/infrastructure/satellite_config.py | 数据/产物根、管理员MCP配置与公开状态；不接请求里的命令/SQL/路径 |
| backend/app/application/satellite_routing.py | optimize_routes/optimize_snapshot；有向候选搜索+联合回溯；所有需求同时预留；共享业务时延与保守背景负载 |
| backend/app/application/satellite_workflow.py | build_satellite_plan、PROCESSORS、执行、诊断证据核验、报告、MCP产物与哈希 |
| backend/app/api/satellite_routes.py | cases、mcp/status、创建/历史/详情和受运行/目录约束的下载 |
| frontend/src/components/SatelliteWorkbench.tsx | 输入、实际进度、拓扑、路由/资源对照、六部分报告、MCP日志、证据与下载 |
| frontend/src/satellite-api.ts、satellite-types.ts、satellite.css | API、数据类型和样式；App.tsx保留旧入口 |
| backend/scripts/prepare_satellite_mcp.py | 导入11观测表、记录哈希、生成本机只读MCP配置 |
| backend/scripts/satellite_workflow_demo.py、satellite_route_demo.py | 全流程CLI / 仅路径CLI |

实际步骤：`load_snapshot → validate_domain → [accept_diagnosis] → plan_routes → build_report → publish_report → verify_delivery`。方括号仅在有外部诊断时加入；无诊断6步，有诊断7步。

task_key是本次业务步骤标识；每步skill_spec有processor、依赖、能力/工具绑定等配置。执行器查PROCESSORS注册表调用真实处理器；处理器可组合多个Python函数或真实MCP工具。不是Python读取一段自然语言就自动知道怎么执行，也不是每步都动态生成新代码。

路由默认85%请求利用率上限、150ms模型时延上限、最多3个方案。保持业务源与允许出口；缺少关键观测不填0；不进行实际切换，不保证全局最优或全部SLA/可用度改善。

## 7. 与B怎么联调（最重要的下一步）

权威Schema：`docs/satellite-diagnosis.schema.json`，来源`DiagnosisInput`；样例`docs/satellite-diagnosis.example.json`明确development_fixture，不是已交付诊断。B返回overview、causes、watch_items、impact、conclusions、missing_evidence、evidence及时间/案例/source；不负责route_options。我们的完整report再插入路径结果形成六部分。

每条证据填evidence_id、object_id、timestamp、available_at、source_file、record_id；引用真实sample_id或event_id。候选区分candidate/supported/insufficient_evidence，支持和反对证据引用已存在ID。supported只是有证据，不是因果确认或校准概率。

系统已检查候选实际类型、同案例、分析窗、快照时刻、available_at、观测记录存在与证据引用。自由JSON摘要不是自动因果验证。暂可把B的JSON粘到页面“评估时刻与诊断输入”中；也可CLI传`--diagnosis-json`。不要为了演示填造她未交付的结果。

接下来依次做：

1. 把Schema和开发样例发给B，确认函数参数、结束时间不含边界及证据ID。
2. 收到代码/依赖/测试后先在独立环境运行，审查是否读取evaluation或未来恢复，核对每个结论来源。
3. 用她的真实JSON通过现有入口联调；如结构一致无需改前端API。
4. 再在注册的诊断处理器中接她的可调用函数（替换只接JSON的方式），或按需要封装自研诊断MCP，明确区别于网上开源Server。
5. 在同一批案例比较仅关系规则与规则+数据对照；再索取脱敏真实数据、指标口径和人工确认根因，不能先承诺准确率。

当前代码里没有她的satellite_analysis.py，查不到不是遗漏。不要重做已完成的路径模块，也不要把B尚未完成的算法当作我们系统已经做对。

## 8. 测试、复现与已知结果

2026-10-19原工作区实测：89项指定测试通过，前端TypeScript/生产构建通过（大chunk提示是构建警告）。浏览器发起CASE-001完成6步、100%，真实HTML下载200。这是历史验证记录，新目录仍要自己复跑。

本次交接补充验证：对已提交的完整快照`9686e1d`创建不含旧运行目录/依赖的干净检出，使用已有、版本匹配的后端解释器复跑，89项测试通过（54.59秒）；11CSV的201,206行、字段和全部SHA-256校验通过；CASE-001纯路径CLI复现1个方案、10条业务调整。另把生成器输出到新临时目录，11CSV哈希与原数据完全一致。PowerShell三脚本语法检查通过，准备脚本的数组/空格路径参数已核对。没有声称在另一台全新电脑上实际联网安装过所有依赖；bootstrap安装由新环境按需执行。

| 人工评估条件 | 真实完整MCP链结果 | 解释 |
| --- | --- | --- |
| CASE-001，避SAT-20 | feasible；1方案，10业务经SAT-21；14次工具调用 | 同时预留后约82.2%；保留SAT-24等未解决风险，不预测可用度 |
| CASE-002，避GS-01 | no_feasible_route；0方案；14次工具调用 | 固定允许出口不能擅换站 |
| CASE-008，避SAT-20 | insufficient_data；0方案；14次工具调用 | 缺关键数据，不强判可行 |

workflow.status=succeeded只表示本次分析与报告交付成功，不表示有可行路线，更不表示故障解决。早期失败尝试已保存在旧电脑隔离运行库，不必复制运行库来复现代码。

明确安全的测试命令（从仓库根执行，PowerShell）：

```powershell
$env:DATABASE_URL='sqlite:///:memory:'
$env:FEISHU_EVENT_ENABLED='false'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
Set-Location backend
..\.satellite-runtime\app\Scripts\python.exe -m pytest tests/test_satellite_ontology.py tests/test_satellite_routing.py tests/test_satellite_mcp_data.py tests/test_satellite_workflow.py tests/test_report_workflow.py -q -p no:cacheprovider
Set-Location ../frontend
npm run build
```

不要裸跑全仓库pytest。部分旧test_ontology_rules.py/test_api_workflow.py在导入时会删除固定DB；test_feishu_e2e_neo4j.py会操作配置图数据库。新测试用内存SQL、临时产物和隔离路由，不连接真实飞书/Neo4j。单测假的MCP不算真实调用；完整CLI/probe另验真实Server。

可重生成数据（只开发/评估时用，不进入诊断上下文）：

```powershell
node scripts/datasets/generate_satellite_demo.mjs --out .satellite-data-build/regenerated
python backend/scripts/verify_satellite_dataset.py --data-root .satellite-data-build/regenerated
```

生成器默认拒绝覆盖已有非空目录；不要随意--force。只保证11CSV相同字节/哈希，生成文档可能保留生成时的早期接入措辞，进度仍以本文件为准。通用校验不依赖Codex绘图库。

## 9. 仓库包含/不包含什么

包含完整源代码、两个前端入口、数据与evaluation隔离答案、生成器、校验器、说明、Schema/样例、依赖/锁、脚本、测试、已保留的PPT参考。`ppt-output`是研究汇报历史产物，不代表当前诊断实现；代码导读中的旧销售例子也不是卫星已实现功能。

不上传：`.env`/密钥、共享Conda/venv/node_modules、SQLite/DuckDB运行文件、本机绝对路径MCP配置、PID/运行日志、大量临时图表/PPT中间文件。它们不属于可移植源代码；新目录按bootstrap重新生成，不是遗失进度。进度和已知结果已记录在本文件，不依赖旧GPT聊天记忆。

旧MVP基线已推`origin/dataanalyseorigin`，提交`ffb8b36`。新开发源自该提交，历史工作分支`codex/satellite-routing`；本次交接快照在`fengongdemo1`。继续开发前先看git status，保留用户后续改动，不force push，不覆盖main或旧基线。

补充阅读：`docs/卫星路径模块_运行与联调.md`是实现细节；`docs/卫星分析首版_技术方案与两人分工.md`及数据包接入路线是早期方案，若冲突以本文件、当前代码和Schema为准。旧经营分析链的Mock/内置适配器不等于此次新增的真实开源MCP链。

给新GPT账号的一句话：**请先读本分支HANDOFF.md，核对代码和数据可复跑，在不改写既有路径模块、不虚构B诊断结果、不读取evaluation做诊断的前提下，接着推进与同学诊断模块的联调。**
