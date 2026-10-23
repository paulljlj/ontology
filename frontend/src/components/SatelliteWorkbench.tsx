import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, AlertTriangle, ArrowRight, CheckCircle2, ChevronRight, Clock3, Database,
  FileJson, GitBranch, History, Info, Loader2, Network, Play, RadioTower,
  RefreshCw, Route, Satellite, ShieldCheck, TrendingDown, X, XCircle, Zap,
} from "lucide-react";
import { satelliteApi } from "../satellite-api";
import type { SatelliteCase, SatelliteMcpStatus, SatelliteReport, SatelliteRun } from "../satellite-types";

const STATUS: Record<string, string> = {
  planning: "正在准备", running: "正在执行", succeeded: "已完成", failed: "执行失败",
  pending: "待接入", provided: "已提供", ready: "已就绪", skipped: "未执行",
  feasible: "模拟可行", infeasible: "不可行", partial: "部分完成", blocked: "条件不足",
  insufficient_evidence: "证据不足", not_provided: "未提供", completed: "已完成",
  success: "成功", ok: "成功", error: "失败", disabled: "未启用", configured: "已配置",
  configured_not_probed: "已配置，未探测", insufficient_data: "数据不足", no_feasible_route: "无可行路径",
  no_change_needed: "无需改路", candidate: "候选对象", supported: "有支持证据，未最终确认",
};

const FIELD_LABELS: Record<string, string> = {
  object_id: "对象", object_type: "对象类型", candidate_id: "候选对象", service_id: "业务",
  cause: "原因假设", hypothesis: "原因假设", description: "说明", reason: "依据", note: "说明",
  evidence: "证据", evidence_ids: "证据编号", supporting_evidence: "支持证据", opposing_evidence: "反对证据",
  missing_evidence: "缺失证据", priority: "排查优先级", status: "状态", confidence: "模型输出（非已确认概率）",
  before_nodes: "原路径", after_nodes: "备选路径", estimated_latency_ms: "预计时延（ms）",
  latency_ms: "时延（ms）", before_latency_ms: "原时延（ms）", after_latency_ms: "模拟后时延（ms）",
  changes: "路径变更", limitations: "限制条件", unresolved_risks: "未解决风险", feasible: "是否可行",
  title: "标题", name: "名称", metric: "指标", value: "数值", unit: "单位", timestamp: "时间",
  source: "来源", source_file: "来源文件", rows: "相关记录", details: "详情", impact: "影响",
  additional_hops: "新增跳数", added_latency_ms: "增加时延（ms）", path: "路径", nodes: "节点",
  cost: "代价", constraints: "约束", before: "模拟前", after: "模拟后", summary: "摘要",
  offered_mbps: "业务请求流量（Mbps）", estimated_total_changed_latency_ms: "变更业务总预计时延（ms）",
  latency_limit_ms: "时延上限（ms）", estimated_latency_within_limit: "预计时延满足约束",
  availability_sla_evaluated: "已验证可用度 SLA", capacity_mbps: "容量（Mbps）",
  effective_capacity_mbps: "有效容量（Mbps）", ingress_mbps: "到达流量（Mbps）",
  forwarded_mbps: "已转发流量（Mbps）", discarded_mbps: "丢弃流量（Mbps）",
  demand_utilization_pct: "容量占用（%）", availability_pct: "业务可用度（%）",
  queue_depth_mb: "排队数据量（MB）", event_code: "告警事件",
};

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function array(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
function strings(value: unknown): string[] { return array(value).filter((item): item is string => typeof item === "string"); }
function text(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") return Number.isFinite(value) ? value.toLocaleString("zh-CN", { maximumFractionDigits: 3 }) : "—";
  if (typeof value === "string") return STATUS[value] ?? value;
  return JSON.stringify(value);
}
function number(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}
function fixed(value: unknown, digits = 1): string {
  const parsed = number(value);
  return parsed === undefined ? "—" : parsed.toFixed(digits);
}
function failure(error: unknown): string { return error instanceof Error ? error.message : "请求失败，请稍后重试。"; }
function count(value: number | string[] | undefined): number | string { return Array.isArray(value) ? value.length : value ?? "—"; }
function displayTime(value?: string): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

export function SatelliteWorkbench() {
  const [cases, setCases] = useState<SatelliteCase[]>([]);
  const [caseId, setCaseId] = useState("");
  const [avoid, setAvoid] = useState("");
  const [at, setAt] = useState("");
  const [asOf, setAsOf] = useState("");
  const [requirement, setRequirement] = useState("比较业务可用度与正常基线，执行本体关系规则，给出异常候选、轻微异常、影响对照和备选通信路径。");
  const [autoDiagnosis, setAutoDiagnosis] = useState(true);
  const [diagnosisBackend, setDiagnosisBackend] = useState<"local" | "neo4j_mcp">("neo4j_mcp");
  const [diagnosisJson, setDiagnosisJson] = useState("");
  const [runs, setRuns] = useState<SatelliteRun[]>([]);
  const [activeRun, setActiveRun] = useState<SatelliteRun | null>(null);
  const [mcp, setMcp] = useState<SatelliteMcpStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [selecting, setSelecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<{ title: string; value: unknown } | null>(null);

  const selectedCase = cases.find((item) => item.case_id === caseId);
  const report = activeRun?.summary?.satellite_report;
  const busy = activeRun?.status === "planning" || activeRun?.status === "running";

  function openEvidence(title: string, value: unknown) {
    const item = record(value);
    const ids = [...strings(item.supporting_evidence_ids), ...strings(item.contradicting_evidence_ids), ...strings(item.evidence_ids)];
    if (!ids.length) { setEvidence({ title, value }); return; }
    const resolved: Record<string, unknown>[] = [];
    function collect(input: unknown, depth: number) {
      if (depth > 7 || input === null || typeof input !== "object") return;
      if (Array.isArray(input)) { input.forEach((entry) => collect(entry, depth + 1)); return; }
      const row = record(input);
      if (typeof row.evidence_id === "string" && ids.includes(row.evidence_id)) resolved.push(row);
      Object.values(row).forEach((entry) => collect(entry, depth + 1));
    }
    collect(report, 0);
    (activeRun?.tasks ?? []).forEach((task) => collect(task.evidence, 0));
    const unique = [...new Map(resolved.map((row) => [String(row.evidence_id), row])).values()];
    setEvidence({ title, value: { analysis_item: item, resolved_evidence: unique, missing_references: ids.filter((id) => !unique.some((row) => row.evidence_id === id)), note: "仅展示当前报告和运行记录中实际返回的证据，不根据编号编造原始数据。" } });
  }

  const refresh = useCallback(async () => {
    setLoading(true);
    const results = await Promise.allSettled([satelliteApi.cases(), satelliteApi.runs(), satelliteApi.mcpStatus()]);
    const problems: string[] = [];
    if (results[0].status === "fulfilled") {
      const rows = Array.isArray(results[0].value) ? results[0].value : [];
      setCases(rows);
      setCaseId((current) => rows.some((item) => item.case_id === current) ? current : rows[0]?.case_id ?? "");
    } else problems.push(failure(results[0].reason));
    if (results[1].status === "fulfilled") {
      const rows = Array.isArray(results[1].value) ? results[1].value : [];
      setRuns(rows);
      setActiveRun((current) => current ? rows.find((item) => item.id === current.id) ?? current : rows[0] ?? null);
    } else problems.push(`执行记录：${failure(results[1].reason)}`);
    if (results[2].status === "fulfilled") setMcp(results[2].value);
    else { setMcp(null); problems.push(`MCP 状态：${failure(results[2].reason)}`); }
    setError(problems.length ? [...new Set(problems)].join("\n") : null);
    setLoading(false);
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!evidence) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setEvidence(null); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [evidence]);
  useEffect(() => {
    if (!selectedCase) return;
    const configuredSampling = Number(selectedCase.sampling_seconds ?? 60);
    const samplingSeconds = Number.isFinite(configuredSampling) && configuredSampling > 0 ? configuredSampling : 60;
    const end = Date.parse(selectedCase.analysis_end_exclusive);
    setAt(Number.isFinite(end) ? new Date(end - samplingSeconds * 1000).toISOString() : "");
    setAsOf(selectedCase.initial_diagnosis_cutoff ?? selectedCase.analysis_start);
  }, [selectedCase?.case_id]);

  useEffect(() => {
    if (!activeRun || !busy) return;
    let disposed = false;
    let pending = false;
    const runId = activeRun.id;
    const timer = window.setInterval(async () => {
      if (pending) return;
      pending = true;
      try {
        const fresh = await satelliteApi.run(runId);
        if (!disposed) {
          setActiveRun((current) => current?.id === runId ? fresh : current);
          setRuns((current) => current.map((item) => item.id === fresh.id ? fresh : item));
        }
      } catch (problem) {
        if (!disposed) setError(`状态更新失败，页面保留上次收到的数据。${failure(problem)}`);
      } finally { pending = false; }
    }, 1100);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [activeRun?.id, busy]);

  const mcpCalls = useMemo<Array<Record<string, unknown>>>(() => (activeRun?.tasks ?? []).flatMap((task) => array(task.evidence?.mcp_calls).map((call) => ({ task: task.title, ...record(call) }))), [activeRun]);
  const diagnosisEvidence = useMemo(() => {
    const task = (activeRun?.tasks ?? []).find((item) => item.task_key === "diagnose_network");
    return array(task?.evidence?.evidence).map(record);
  }, [activeRun]);
  const total = activeRun?.tasks?.length ?? 0;
  const completed = activeRun?.tasks?.filter((task) => task.status === "succeeded").length ?? 0;
  const reportedProgress = activeRun?.summary?.progress;
  const progress = typeof reportedProgress === "number" && Number.isFinite(reportedProgress)
    ? Math.max(0, Math.min(100, reportedProgress)) : total ? Math.round(completed / total * 100) : 0;

  function usePreset(id: string, avoidObject: string) {
    if (!cases.some((item) => item.case_id === id)) { setError(`后端尚未提供 ${id}，请先加载案例；不会用其他案例替代这个预设。`); return; }
    setCaseId(id);
    setAvoid(avoidObject);
    setDiagnosisJson("");
    setError(null);
  }

  async function submit() {
    setError(null);
    if (!caseId) { setError("请先加载并选择一个后端提供的案例。"); return; }
    const avoidObjects = [...new Set(avoid.split(/[,，\s]+/).map((item) => item.trim()).filter(Boolean))];
    if (avoidObjects.some((item) => !/^[A-Za-z0-9_-]{1,80}$/.test(item))) {
      setError("待避对象请填写编号，例如 SAT-20 或 GS-01，多个编号用逗号分隔。"); return;
    }
    for (const [label, value] of [["评估时刻", at], ["数据截止时刻", asOf]]) {
      if (value && (Number.isNaN(Date.parse(value)) || !/([zZ]|[+-]\d{2}:\d{2})$/.test(value))) { setError(`${label}不是有效时间，请使用带时区的 ISO 格式。`); return; }
    }
    if (at && asOf && Date.parse(at) > Date.parse(asOf)) { setError("路由评估时刻不能晚于可读取数据截止时刻。"); return; }
    const configuredSampling = Number(selectedCase?.sampling_seconds ?? 60);
    const samplingSeconds = Number.isFinite(configuredSampling) && configuredSampling > 0 ? configuredSampling : 60;
    if (at && asOf && Date.parse(at) + samplingSeconds * 1000 > Date.parse(asOf)) {
      setError(`采样周期为 ${samplingSeconds} 秒。请将数据截止时间设在该次采样结束之后，或选择更早的评估时刻。`); return;
    }
    let diagnosis: Record<string, unknown> | undefined;
    if (diagnosisJson.trim()) {
      try {
        const parsed: unknown = JSON.parse(diagnosisJson);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("需要 JSON 对象");
        diagnosis = parsed as Record<string, unknown>;
      } catch { setError("诊断 JSON 格式不正确，需要一个 JSON 对象；也可以留空并使用自动诊断。"); return; }
    }
    const useAutoDiagnosis = autoDiagnosis && !diagnosis;
    if (!avoidObjects.length && !array(diagnosis?.causes).some((cause) => record(cause).status === "supported") && !useAutoDiagnosis) {
      setError("请输入待避对象编号、提供带证据的外部诊断，或启用系统自动诊断。"); return;
    }
    setSubmitting(true);
    try {
      const created = await satelliteApi.createRun({ case_id: caseId, avoid_objects: avoidObjects, at: at || undefined,
        as_of: asOf || undefined, requirement: requirement.trim() || undefined, auto_diagnosis: useAutoDiagnosis,
        diagnosis_graph_backend: diagnosisBackend, diagnosis });
      setActiveRun(created);
      setRuns((current) => [created, ...current.filter((item) => item.id !== created.id)]);
    } catch (problem) { setError(failure(problem)); }
    finally { setSubmitting(false); }
  }

  async function selectRun(id: string) {
    if (!id) return;
    setSelecting(true);
    setError(null);
    try { setActiveRun(await satelliteApi.run(id)); }
    catch (problem) { setError(failure(problem)); }
    finally { setSelecting(false); }
  }

  return <main className="satelliteWorkspace satelliteSimple">
    <header className="satelliteHeader">
      <div className="satelliteIdentity"><span className="satelliteLogo"><Satellite size={24} /></span><div><strong>卫星网络分析工作台</strong><small>SATELLITE NETWORK WORKBENCH</small></div></div>
      <div className="satelliteHeaderActions">
        <label className="satelliteHistory"><History size={15} /><span className="srOnly">历史执行记录</span><select value={activeRun?.id ?? ""} onChange={(event) => void selectRun(event.target.value)} disabled={selecting}><option value="">选择执行记录</option>{runs.map((run) => <option key={run.id} value={run.id}>{run.title || run.id.slice(0, 8)} · {STATUS[run.status] ?? run.status}</option>)}</select></label>
        <button className="satelliteIconButton" type="button" aria-label="刷新案例与执行记录" onClick={() => void refresh()} disabled={loading}><RefreshCw size={17} className={loading ? "satelliteSpin" : ""} /></button>
      </div>
    </header>

    <section className="satelliteHero">
      <div><p className="satelliteEyebrow"><Activity size={14} /> 数据诊断与路由模拟</p><h1>卫星网络可用度异常关联分析</h1><p>从业务下降出发，结合本体关系、资源指标、正常对照和路径约束给出排查结论。</p></div>
      <div className="satelliteBoundary"><ShieldCheck size={20} /><div><strong>模拟评估，不执行设备切换</strong><span>当前使用合成数据。诊断候选有证据但不等于已经确认硬件故障。</span></div></div>
    </section>

    {error && <div className="satelliteError" role="alert"><AlertTriangle size={19} /><p>{error}</p><button type="button" aria-label="关闭错误提示" onClick={() => setError(null)}><X size={16} /></button></div>}

    <div className="satelliteMainGrid">
      <div className="satelliteWorkColumn">
        <section className="satellitePanel satelliteComposer">
          <div className="satelliteSectionHeading"><h2><GitBranch size={18} /> 分析输入</h2><span className="satelliteMuted">仅接受案例编号和参数</span></div>
          <div className="satelliteInputGrid">
            <label className="satellitePrimaryControl"><span>选择分析案例</span><select value={caseId} onChange={(event) => setCaseId(event.target.value)} disabled={loading || !cases.length}><option value="">{loading ? "正在加载案例…" : "请选择案例"}</option>{cases.map((item) => <option value={item.case_id} key={item.case_id}>{item.case_id} · {item.dataset_kind === "synthetic" ? "合成数据" : item.dataset_kind}</option>)}</select></label>
            <label className="satelliteAdvancedControl"><span>诊断方式</span><select value={autoDiagnosis ? diagnosisBackend : "off"} onChange={(event) => {
              if (event.target.value === "off") setAutoDiagnosis(false);
              else { setAutoDiagnosis(true); setDiagnosisBackend(event.target.value as "local" | "neo4j_mcp"); }
            }}><option value="local">自动诊断（本地时态图）</option><option value="neo4j_mcp">自动诊断（Neo4j MCP）</option><option value="off">不自动诊断</option></select></label>
            <label className="satelliteAdvancedControl"><span>待避对象 <small>可选人工覆盖</small></span><input value={avoid} onChange={(event) => setAvoid(event.target.value)} placeholder="留空则采用诊断优先对象；或填 SAT-20" maxLength={600} /></label>
          </div>
          {selectedCase && <div className="satelliteCaseInfo"><span><Satellite size={14} /> {count(selectedCase.satellites)} 颗卫星</span><span><RadioTower size={14} /> {count(selectedCase.ground_stations)} 个地面站</span><span><Network size={14} /> {count(selectedCase.links)} 条链路</span><span><Clock3 size={14} /> 分析时段 {displayTime(selectedCase.analysis_start)} 至 {displayTime(selectedCase.analysis_end_exclusive)}（不含结束时刻）</span></div>}
          <label className="satelliteRequirement satelliteAdvancedControl"><span>本次需要查看什么</span><textarea value={requirement} onChange={(event) => setRequirement(event.target.value)} rows={2} maxLength={3000} /></label>
          <details className="satelliteAdvanced"><summary>评估时刻与外部诊断输入 <ChevronRight size={14} /></summary><div className="satelliteInputGrid"><label><span>路由评估时刻 at</span><input value={at} onChange={(event) => setAt(event.target.value)} placeholder="带时区的 ISO 时间" /></label><label><span>可读取数据截止时刻 as_of</span><input value={asOf} onChange={(event) => setAsOf(event.target.value)} placeholder="带时区的 ISO 时间" /></label></div><label><span>外部诊断 JSON <small>可选；填写后优先使用它</small></span><textarea className="satelliteCodeInput" value={diagnosisJson} onChange={(event) => setDiagnosisJson(event.target.value)} rows={5} maxLength={200000} placeholder="通常留空，由已接入的同学诊断模块自动生成。" /></label><p className="satelliteHelper">自动诊断只读取观测白名单和截止时刻前的数据，不读取 evaluation。Neo4j MCP 模式需要先启动数据库、导入关系图并配置官方 Server；连接失败会明确报错，不静默退回本地图。</p></details>
          <div className="satellitePresets"><span>演示参数</span><button type="button" onClick={() => usePreset("CASE-001", "SAT-20")}>SAT-20 待避测试</button><button type="button" onClick={() => usePreset("CASE-001", "GS-01")}>GS-01 固定站约束</button><button type="button" onClick={() => usePreset("CASE-008", "SAT-20")}>CASE-008 缺证测试</button></div>
          <p className="satelliteHelper">SAT-20 参数用于拥塞绕行演示，GS-01 检查固定站约束，CASE-008 检查缺证处理。预设只填写参数，不预填诊断结论。</p>
          <div className="satelliteSubmitRow"><p><Info size={14} /> 自动诊断先给候选与依据，再用优先对象验算路线；候选不等于故障定论。</p><button type="button" className="satellitePrimaryButton" onClick={() => void submit()} disabled={submitting || loading || !caseId || busy}>{submitting ? <Loader2 size={17} className="satelliteSpin" /> : <Play size={17} />}{submitting ? "正在提交" : busy ? "执行中" : "生成分析与路由报告"}</button></div>
        </section>

        <section className="satellitePanel satelliteExecution">
          <div className="satelliteSectionHeading"><h2><Activity size={18} /> 执行过程</h2><span className={`satelliteRunState state-${activeRun?.status ?? "idle"}`}>{selecting ? "读取记录中" : activeRun ? STATUS[activeRun.status] ?? activeRun.status : "等待运行"}</span></div>
          {activeRun ? <><div className="satelliteProgress"><span style={{ width: `${progress}%` }} /></div><div className="satelliteProgressCaption"><span>{completed} / {total} 个步骤完成</span><strong>{progress}%</strong></div><ol className="satelliteTaskList">{(activeRun.tasks ?? []).map((task) => <li key={task.id} className={`task-${task.status}`}><TaskIcon status={task.status} /><div><strong>{task.title}</strong><p>{task.description}</p><div className="satelliteTaskMeta"><code>{task.task_key}</code><span>{STATUS[task.status] ?? task.status}</span>{task.started_at && <time>{displayTime(task.started_at)}</time>}</div>{task.outputs?.length > 0 && <p className="satelliteTaskOutput">输出：{task.outputs.map((item) => text(item)).join("、")}</p>}{task.error && <p className="satelliteInlineError">{task.error}</p>}<button type="button" className="satelliteTextButton" onClick={() => setEvidence({ title: `${task.title}：执行证据`, value: task.evidence })}>查看证据 <ChevronRight size={13} /></button></div></li>)}</ol>{!total && <EmptyState text="服务尚未返回执行步骤。" />}{activeRun.error && <p className="satelliteInlineError" role="alert">{activeRun.error}</p>}</> : <EmptyState text="选择案例并发起运行后，这里展示后端真实返回的步骤、输出和错误。" />}
        </section>

        <section className="satellitePanel satelliteTechnicalOnly">
          <div className="satelliteSectionHeading"><h2><Network size={18} /> 当前网络关系</h2><span className="satelliteMuted">报告中的实际节点与连接</span></div>
          {report?.topology?.nodes?.length ? <NetworkTopology topology={report.topology} /> : <EmptyState text="尚无拓扑结果。等待后端读取所选时段的连接关系，不生成示意节点替代数据。" />}
        </section>

        <section className="satellitePanel satelliteTechnicalOnly">
          <div className="satelliteSectionHeading"><h2><Route size={18} /> 备选路径与模拟对照</h2><span className="satelliteSimulationLabel">仅方案，不切换</span></div>
          <RoutePlans report={report} onEvidence={openEvidence} />
        </section>

        <section className="satellitePanel satelliteMcpPanel satelliteTechnicalOnly">
          <div className="satelliteSectionHeading"><h2><Database size={18} /> 数据接入与 MCP 调用</h2><span className="satelliteMuted">{mcp ? mcp.default_mode === "mcp" ? "默认 MCP 模式" : "默认文件模式" : "状态未获取"}</span></div>
          <p className="satelliteHelper">{mcp?.note ?? "配置状态与真实调用分开展示；配置成功不代表已完成调用。"}</p>
          {report?.provenance?.input_source === "integrated_diagnosis" && <p className="satelliteHelper">诊断关系查询：{report.provenance.diagnosis_graph_backend === "mcp" ? "本次由官方 Neo4j MCP 完成；完整诊断过程保存在原始诊断 JSON 产物。" : "本次使用明确标注的本地时态图模式，不冒充 MCP 调用。"}</p>}
          <div className="satelliteServerList">{mcp?.servers?.map((server) => <div key={server.name}><span className={server.enabled ? "satelliteServerDot enabled" : "satelliteServerDot"} /><strong>{server.name}</strong><span>{server.transport}</span><small>{mcpCalls.some((call) => call.server === server.name && ["success", "succeeded"].includes(String(call.status))) ? "本次已成功调用" : server.enabled ? text(server.status ?? "configured") : "未启用"}</small></div>)}</div>
          {mcp && !mcp.servers?.length && <p className="satelliteHelper">未配置外部 MCP 服务器。文件模式仍须以后端实际执行结果为准。</p>}
          {mcpCalls.length ? <div className="satelliteTableScroll"><table className="satelliteCallTable"><thead><tr><th>服务器 / 工具</th><th>所属步骤</th><th>耗时</th><th>结果</th></tr></thead><tbody>{mcpCalls.map((call, index) => <tr key={index}><td><strong>{text(call.server ?? call.server_name)}</strong><code>{text(call.tool ?? call.tool_name ?? call.name)}</code></td><td>{text(call.task)}</td><td>{text(call.duration_ms ?? call.elapsed_ms)} ms</td><td>{text(call.status ?? (typeof call.ok === "boolean" ? call.ok ? "success" : "error" : undefined))}{typeof call.error === "string" && <small className="satelliteInlineError">{call.error}</small>}</td></tr>)}</tbody></table></div> : <div className="satelliteNoCalls">当前运行没有返回 MCP 调用记录。不会用工具标签代替真实调用。</div>}
        </section>
      </div>

      <aside className="satelliteReportColumn" aria-label="卫星分析报告">
        <div className="satelliteReportHeader"><div><FileJson size={20} /><h2>分析报告</h2></div><span>六部分结果</span></div>
        <div className="satelliteReportNotice"><strong>{report?.provenance?.input_source === "integrated_diagnosis" ? "已完成自动诊断" : report?.diagnosis_status === "provided" ? "已接收外部诊断" : "本次未启用诊断"}</strong><p>{report?.provenance?.input_source === "integrated_diagnosis" ? "已运行同学交付的诊断代码，逐项核对观测证据，再把优先候选交给路径模块。" : report?.diagnosis_status === "provided" ? "原因与风险来自提供的诊断 JSON，尚不代表因果已经确认。" : "当前只展示观测与手动条件下的路由模拟，不自动确认异常原因。"}</p>{report?.provenance?.diagnosis_is_fixture && <b>诊断数据标记为演示 fixture，不能用于真实故障结论。</b>}</div>
        {report && <div className="satelliteReportMeta"><span>{report.case_id} · {report.dataset_kind === "synthetic" ? "合成数据" : report.dataset_kind}</span><span>评估时刻 {displayTime(report.at)}</span><span>数据截止 {displayTime(report.as_of)}</span><span>输入来源：{report.provenance?.input_source === "integrated_diagnosis" ? `自动诊断（${report.provenance.diagnosis_graph_backend === "mcp" ? "Neo4j MCP" : "本地时态图"}）` : report.provenance?.input_source === "diagnosis_json" ? "外部诊断 JSON" : "手动评估条件"}</span></div>}
        <ReportPart number="01" title="异常概况" wide><AnomalyOverview report={report} onDetail={(value) => setEvidence({ title: "业务可用度明细与判断标准", value })} /></ReportPart>
        <OntologyReasoningPanel report={report} onDetail={(value) => setEvidence({ title: "OWL 本体类、关系与本次规则执行", value })} />
        <ReportPart number="02" title="根因候选与异常原因"><CauseOverview report={report} evidence={diagnosisEvidence} onDetail={openEvidence} /></ReportPart>
        <ReportPart number="03" title="潜在或轻微异常"><WatchOverview report={report} onDetail={openEvidence} /></ReportPart>
        <ReportPart number="04" title="备选通信路径"><RouteOverview report={report} onDetail={(value) => setEvidence({ title: "完整路线、容量与限制条件", value })} /></ReportPart>
        <ReportPart number="05" title="影响与正常对照"><ImpactOverview report={report} onDetail={openEvidence} /></ReportPart>
        <ReportPart number="06" title="结论与处理建议" wide><ConclusionOverview report={report} onDetail={(value) => setEvidence({ title: "完整结论与规则执行情况", value })} /></ReportPart>
      </aside>
    </div>
    <footer className="satelliteFooter"><span>本体关系与能力编排</span><p>合成数据用于验证流程。诊断结论、路由模拟和真实设备操作严格区分。</p></footer>
    {evidence && <div className="satelliteEvidenceOverlay" role="dialog" aria-modal="true" aria-label={evidence.title} onClick={() => setEvidence(null)}><section onClick={(event) => event.stopPropagation()}><header><div><span>结论依据</span><h2>{evidence.title}</h2></div><button type="button" className="satelliteIconButton" aria-label="关闭证据" onClick={() => setEvidence(null)}><X size={20} /></button></header><p>先看下面的中文摘要；确需核对接口字段时，再展开底部技术数据。</p><EvidenceSummary value={evidence.value} /><JsonDetails value={evidence.value} /><button type="button" className="satellitePrimaryButton" onClick={() => setEvidence(null)}>返回报告</button></section></div>}
  </main>;
}

function TaskIcon({ status }: { status: string }) {
  if (status === "running") return <Loader2 size={18} className="satelliteSpin" />;
  if (status === "succeeded") return <CheckCircle2 size={18} />;
  if (status === "failed") return <XCircle size={18} />;
  return <span className="satellitePendingCircle" />;
}
function EmptyState({ text: message }: { text: string }) { return <div className="satelliteEmpty"><Network size={28} /><p>{message}</p></div>; }
function ReportPart({ number, title, wide = false, children }: { number: string; title: string; wide?: boolean; children: React.ReactNode }) {
  return <section className={`satelliteReportPart${wide ? " satelliteReportWide" : ""}`}><h3><span>{number}</span>{title}</h3>{children}</section>;
}
function JsonDetails({ value, expanded = false }: { value: unknown; expanded?: boolean }) {
  return <details className="satelliteJson" open={expanded}><summary>结构化数据与原始字段</summary><pre>{JSON.stringify(value ?? null, null, 2)}</pre></details>;
}
function AnomalyOverview({ report, onDetail }: { report?: SatelliteReport; onDetail: (value: unknown) => void }) {
  const rows = array(report?.overview?.service_comparison).map(record);
  if (!report || !rows.length) return <p className="satelliteHelper">运行后显示异常数量、下降幅度和逐业务对比。</p>;
  const major = rows.filter((row) => row.classification === "major");
  const watch = rows.filter((row) => row.classification === "watch");
  const normal = rows.filter((row) => row.classification !== "major" && row.classification !== "watch");
  const shown = major.slice(0, 5);
  const baseline = major.reduce((sum, row) => sum + (number(row.baseline_availability_pct) ?? 0), 0) / Math.max(1, major.length);
  const analysis = major.reduce((sum, row) => sum + (number(row.analysis_mean_availability_pct) ?? 0), 0) / Math.max(1, major.length);
  const summary = record(report.overview.indicator_summary);
  const policy = record(report.overview.indicator_policy);
  const majorRule = record(policy.major_alert);
  const watchRule = record(policy.watch);
  return <><div className="satelliteAlertBanner"><AlertTriangle size={18} /><div><strong>检测到 {major.length} 个业务发生重大下降</strong><span>异常窗口内持续下降，需要进行共同依赖与资源证据排查</span></div></div><div className="satelliteHeadlineMetrics"><MetricCard label="重大异常" value={major.length} unit="个" tone="danger" /><MetricCard label="轻微异常" value={watch.length} unit="个" tone="warning" /><MetricCard label="正常对照" value={normal.length} unit="个" tone="ok" /><MetricCard label="平均下降" value={fixed(baseline - analysis, 2)} unit="百分点" tone="blue" /></div><div className="satelliteQualityStrip"><div><ShieldCheck size={15} /><span><b>{fixed(summary.sample_completeness_pct, 0)}%</b> 数据完整率</span></div><div><TrendingDown size={15} /><span><b>下降 &gt; {text(majorRule.drop_pp_strictly_greater_than)} 点</b> 且连续 {text(majorRule.consecutive_valid_samples)} 次判重大</span></div><div><Activity size={15} /><span><b>{text(watchRule.drop_pp_at_least)}–{text(watchRule.drop_pp_at_most)} 点</b> 且连续 {text(watchRule.consecutive_valid_samples)} 次判关注</span></div></div><div className="satelliteOverviewGrid"><div className="satelliteMiniTable"><div className="satelliteMiniTableHead"><span>业务</span><span>正常基线</span><span>分析时段</span><span>下降</span></div>{shown.map((row) => <div className="satelliteMiniTableRow" key={text(row.service_id)}><strong>{text(row.service_id)}</strong><span>{fixed(row.baseline_availability_pct, 2)}%</span><span>{fixed(row.analysis_mean_availability_pct, 2)}%</span><em>↓ {fixed(row.mean_drop_pp, 2)}</em></div>)}</div><div className="satelliteDropChart"><strong>下降幅度（百分点）</strong>{shown.map((row) => { const drop = number(row.mean_drop_pp) ?? 0; return <div key={text(row.service_id)}><span>{text(row.service_id)}</span><i><b style={{ width: `${Math.min(100, drop / 8 * 100)}%` }} /></i><em>{drop.toFixed(2)}</em></div>; })}</div></div><button type="button" className="satelliteTextButton" onClick={() => onDetail({ policy: report.overview.indicator_policy, summary: report.overview.indicator_summary, services: rows })}>查看全部 {rows.length} 个业务及判断标准 <ChevronRight size={13} /></button></>;
}

function MetricCard({ label, value, unit, tone }: { label: string; value: unknown; unit: string; tone: string }) {
  return <div className={`satelliteHeadlineMetric tone-${tone}`}><span>{label}</span><strong>{text(value)}<small>{unit}</small></strong></div>;
}

function OntologyReasoningPanel({ report, onDetail }: { report?: SatelliteReport; onDetail: (value: unknown) => void }) {
  const comparison = array(report?.overview?.service_comparison).map(record);
  const major = comparison.filter((row) => row.classification === "major");
  const candidates = array(report?.causes?.items).map(record);
  const primary = candidates.find((item) => item.status === "supported") ?? candidates[0];
  const domainRules = array(report?.rule_execution?.domain_rules).map(record);
  const passedDomain = domainRules.filter((rule) => rule.status === "passed").length;
  const graphMode = report?.provenance?.diagnosis_graph_backend === "mcp" ? "Neo4j MCP 时态关系图" : "本地时态关系图";
  const classes = [
    ["NetworkService", "端到端业务"], ["Route", "有效路由"], ["Satellite", "卫星"],
    ["GroundStation", "地面站"], ["CommunicationLink", "通信链路"],
    ["MetricObservation", "指标观测"], ["AlarmEvent", "告警事件"],
    ["RouteProposal", "备选路线"], ["NetworkSnapshot", "网络快照"],
  ];
  const relationRows = [
    { source: "NetworkService", relation: "SERVICE_USES_ROUTE", target: "Route" },
    { source: "Route", relation: "ROUTE_USES_NODE", target: "Satellite / GroundStation" },
    { source: "Route", relation: "ROUTE_USES_LINK", target: "CommunicationLink" },
    { source: "CommunicationLink", relation: "LINK_SOURCE", target: "NetworkNode" },
    { source: "CommunicationLink", relation: "LINK_TARGET", target: "NetworkNode" },
    { source: "MetricObservation", relation: "OBSERVES_ENTITY", target: "NetworkEntity" },
    { source: "AlarmEvent", relation: "ALARM_ON_ENTITY", target: "NetworkEntity" },
    { source: "NetworkSnapshot", relation: "SNAPSHOT_CONTAINS", target: "NetworkEntity" },
    { source: "RouteProposal", relation: "PROPOSAL_FOR_SERVICE", target: "NetworkService" },
  ];
  return <section className="satelliteOntologyPanel"><header><div><span className="satelliteOntologyMark">OWL</span><div><h3>本体语义与关系推理</h3><p>本体限定“对象是什么、关系是否合法”；时态关系规则沿当前有效路由生成共同依赖候选。</p></div></div><button type="button" onClick={() => onDetail({ classes, relations: relationRows, domain_rules: domainRules, diagnostic_rules: report?.rule_execution?.diagnostic_rules })}>查看类与规则 <ChevronRight size={13} /></button></header><div className="satelliteOntologyStats"><span><b>9</b> 个具体领域类</span><span><b>9</b> 种卫星领域关系</span><span><b>{passedDomain}</b> 条本体/快照规则通过</span><span><b>{graphMode}</b> 本次关系来源</span></div><div className="satelliteOntologyClasses">{classes.map(([name, label]) => <div key={name}><code>{name}</code><span>{label}</span></div>)}</div><div className="satelliteOntologyRelations"><div className="satelliteOntologyNode is-service"><small>异常实例</small><strong>{major.length} 个 NetworkService</strong></div><div className="satelliteOntologyEdge"><span>SERVICE_USES_ROUTE</span><i>→</i></div><div className="satelliteOntologyNode"><small>按时间选择</small><strong>有效 Route</strong></div><div className="satelliteOntologyEdge"><span>ROUTE_USES_NODE / LINK</span><i>→</i></div><div className="satelliteOntologyNode is-candidate"><small>共同依赖规则</small><strong>{text(primary?.object_id)} + {Math.max(0, candidates.length - 1)} 个候选</strong></div><div className="satelliteOntologyEdge"><span>指标 + 告警 + 正常对照</span><i>→</i></div><div className="satelliteOntologyNode is-result"><small>证据排序</small><strong>优先核查 {text(primary?.object_id)}</strong></div></div><div className="satelliteOntologyBoundary"><Info size={14} /><span>推理结果是“潜在共同依赖关系和候选顺序”，不是 OWL 自动证明设备故障。根因判断仍由后续观测证据支持或反驳。</span></div></section>;
}

function CauseOverview({ report, evidence, onDetail }: { report?: SatelliteReport; evidence: Record<string, unknown>[]; onDetail: (title: string, value: unknown) => void }) {
  const items = array(report?.causes?.items).map(record);
  if (!items.length) return <p className="satelliteHelper">本次没有返回原因候选。人工指定待避对象不会被当作诊断结论。</p>;
  const primary = items.find((item) => item.status === "supported") ?? items[0];
  const others = items.filter((item) => item !== primary).slice(0, 4);
  const route = record(array(report?.route_options?.proposals)[0]);
  const changes = array(route.changes).map(record);
  const sources = [...new Set(changes.map((change) => text(array(change.before_nodes)[0])).filter((id) => id !== "—"))].slice(0, 5);
  const stations = [...new Set(changes.map((change) => { const nodes = array(change.before_nodes); return text(nodes[nodes.length - 1]); }).filter((id) => id !== "—"))];
  const evidenceText = evidence.filter((row) => row.object_id === primary.object_id).map((row) => text(row.description));
  const metric = (name: string) => { const match = evidenceText.find((entry) => entry.startsWith(`${name}=`))?.match(/=([\d.]+)/); return match?.[1] ?? "—"; };
  const comparison = array(report?.impact?.items).map(record).find((item) => item.candidate_id === primary.object_id);
  const eventFound = evidenceText.some((entry) => entry.startsWith("event_code="));
  return <><div className="satelliteCauseLead"><div><span>优先排查候选</span><strong>{text(primary.object_id)}</strong><small>{text(primary.status)}</small></div><p><Zap size={16} /> {text(primary.mechanism)}</p></div><div className="satelliteCauseMetrics"><MetricCard label="到达流量" value={metric("ingress_mbps")} unit="Mbps" tone="danger" /><MetricCard label="有效容量" value={metric("effective_capacity_mbps")} unit="Mbps" tone="blue" /><MetricCard label="容量占用" value={metric("demand_utilization_pct")} unit="%" tone="warning" /><MetricCard label="丢弃流量" value={metric("discarded_mbps")} unit="Mbps" tone="danger" /></div><div className="satelliteEvidenceChain"><span><b>关系证据</b>{changes.length} 条异常路径共同经过</span><i /><span><b>容量证据</b>{metric("ingress_mbps")} &gt; {metric("effective_capacity_mbps")} Mbps</span><i /><span><b>告警证据</b>{eventFound ? "发现转发队列告警" : "未发现对应告警"}</span><i /><span><b>正常对照</b>{comparison && !strings(comparison.same_resource_normal).length ? "无同资源正常反例" : "存在反例，需降级"}</span></div><div className="satelliteRelationMap"><div className="satelliteRelationSide"><small>异常业务入口</small>{sources.map((source) => <span key={source}>{source}</span>)}</div><div className="satelliteRelationArrow">→</div><button type="button" className="satelliteRootNode" onClick={() => onDetail(text(primary.object_id), primary)}><Satellite size={19} /><strong>{text(primary.object_id)}</strong><small>共同经过</small></button><div className="satelliteRelationArrow">→</div><div className="satelliteRelationSide is-station"><small>到达地面站</small>{stations.map((station) => <span key={station}>{station}</span>)}</div></div><div className="satelliteCandidateStrip">{others.map((item) => <button type="button" key={text(item.object_id)} onClick={() => onDetail(text(item.object_id), item)}><strong>{text(item.object_id)}</strong><span>{item.object_type === "ground_station" ? "地面站候选" : item.object_type === "link" ? "链路候选" : "卫星候选"}</span><small>{text(item.status)}</small></button>)}</div><p className="satelliteExplainLine"><Info size={14} /> 地面站和链路也进入候选，但存在正常业务作为反例，因此当前优先核查 SAT-20，并非宣告它已损坏。</p></>;
}

function WatchOverview({ report, onDetail }: { report?: SatelliteReport; onDetail: (title: string, value: unknown) => void }) {
  const items = array(report?.watch_items?.items).map(record);
  if (!items.length) return <p className="satelliteHelper">没有发现低于重大阈值但需要关注的持续下降。</p>;
  return <><p className="satelliteSectionIntro">未达到“重大异常”阈值，但连续下降，建议继续观察。</p><div className="satelliteWatchGrid">{items.slice(0, 4).map((item) => <button type="button" key={text(item.service_id)} onClick={() => onDetail(text(item.service_id), item)}><div><strong>{text(item.service_id)}</strong><span>{fixed(item.longest_contiguous_minutes ?? item.duration_minutes, 0)} 分钟</span></div><p><b>{fixed(item.baseline_availability_pct, 2)}%</b><ArrowRight size={13} /><b>{fixed(item.analysis_mean_availability_pct, 2)}%</b></p><small>下降 {fixed(item.mean_drop_pp, 2)} 个百分点 · 关联 {text(item.supporting_resource ?? item.resource_id)}</small></button>)}</div></>;
}

function RouteOverview({ report, onDetail }: { report?: SatelliteReport; onDetail: (value: unknown) => void }) {
  const proposal = record(array(report?.route_options?.proposals)[0]);
  const changes = array(proposal.changes).map(record);
  if (!changes.length) return <p className="satelliteHelper">当前没有可展示的备选路径（{text(report?.route_options?.status)}）。</p>;
  const resources = array(proposal.resources).map(record);
  const relay = resources.find((row) => row.object_id === "SAT-21");
  const risks = array(proposal.unresolved_risks ?? report?.route_options?.unresolved_risks).map(record);
  const maximumLatency = Math.max(...changes.map((change) => number(change.estimated_latency_ms) ?? 0));
  const assessed = array(proposal.service_assessments).map(record);
  const withinLimit = assessed.filter((row) => row.changed && row.estimated_latency_within_limit === true).length;
  return <><div className="satelliteRouteSummary"><div><Route size={19} /><span><strong>{changes.length} 条业务可模拟改路</strong><small>避开 SAT-20，统一经 SAT-21 转发</small></span></div><div className="satelliteLoadGauge"><span>SAT-21 模拟负载</span><strong>{fixed(relay?.estimated_demand_utilization_pct, 1)}%</strong><i><b style={{ width: `${Math.min(100, number(relay?.estimated_demand_utilization_pct) ?? 0)}%` }} /></i></div></div><div className="satelliteRouteChecks"><div><strong>{changes.length}/{changes.length}</strong><span>业务找到连续路径</span></div><div><strong>{withinLimit}/{changes.length}</strong><span>模型时延满足上限</span></div><div><strong>{maximumLatency.toFixed(1)} ms</strong><span>变更业务最高时延</span></div></div><div className="satelliteRouteRows">{changes.slice(0, 3).map((change) => <div key={text(change.service_id)}><strong>{text(change.service_id)}</strong><div><PathPills label="原" nodes={change.before_nodes} tone="old" /><PathPills label="新" nodes={change.after_nodes} tone="new" /></div><span>{fixed(change.estimated_latency_ms, 1)} ms</span></div>)}</div>{risks.length > 0 && <div className="satelliteRouteRisk"><AlertTriangle size={15} /><span><strong>仍需注意 {text(risks[0].object_id)}</strong> 当前容量占用约 {fixed(risks[0].estimated_demand_utilization_pct, 1)}%，本方案不能解决该风险。</span></div>}<button type="button" className="satelliteTextButton" onClick={() => onDetail(report?.route_options)}>查看其余 {Math.max(0, changes.length - 3)} 条路线与容量约束 <ChevronRight size={13} /></button></>;
}

function PathPills({ label, nodes, tone }: { label: string; nodes: unknown; tone: string }) {
  return <p className={`satellitePathPills tone-${tone}`}><em>{label}</em>{array(nodes).map((node, index) => <span key={`${text(node)}-${index}`}>{index > 0 && <ArrowRight size={11} />}<b>{text(node)}</b></span>)}</p>;
}

function ImpactOverview({ report, onDetail }: { report?: SatelliteReport; onDetail: (title: string, value: unknown) => void }) {
  const items = array(report?.impact?.items).map(record);
  const overview = items.find((item) => array(item.affected_service_ids).length || array(item.healthy_service_ids).length) ?? {};
  const affected = strings(overview.affected_service_ids);
  const healthy = strings(overview.healthy_service_ids);
  const controls = items.filter((item) => item.candidate_id).slice(0, 3);
  if (!items.length) return <p className="satelliteHelper">等待影响范围和正常对照结果。</p>;
  return <><div className="satelliteImpactNumbers"><div className="is-affected"><TrendingDown size={18} /><span><strong>{affected.length}</strong><small>受影响业务</small></span></div><div className="is-healthy"><CheckCircle2 size={18} /><span><strong>{healthy.length}</strong><small>正常对照业务</small></span></div></div><div className="satelliteServiceChips"><span>受影响</span><div>{affected.map((id) => <b key={id}>{id}</b>)}</div></div><div className="satelliteServiceChips is-healthy"><span>正常对照</span><div>{healthy.map((id) => <b key={id}>{id}</b>)}</div></div><div className="satelliteControlCards">{controls.map((item) => { const normals = strings(item.same_resource_normal); return <button type="button" key={text(item.candidate_id)} onClick={() => onDetail(text(item.candidate_id), item)}><strong>{text(item.candidate_id)}</strong><span>{normals.length ? `${normals.length} 条同资源业务正常，削弱该候选` : "没有同资源正常业务反例"}</span><small>{normals.length ? "优先级降低" : "仍需重点核查"}</small></button>; })}</div></>;
}

function ConclusionOverview({ report, onDetail }: { report?: SatelliteReport; onDetail: (value: unknown) => void }) {
  const causes = array(report?.causes?.items).map(record);
  const primary = causes.find((item) => item.status === "supported");
  const passed = number(report?.rule_execution?.summary?.passed) ?? 0;
  return <><div className="satelliteConclusionLead"><CheckCircle2 size={21} /><div><span>本次判断</span><strong>{primary ? `优先排查 ${text(primary.object_id)} 的容量过载` : "当前证据不足，保留候选"}</strong><p>这是“有证据支持的排查顺序”，不是已经确认的硬件故障。</p></div></div><div className="satelliteConclusionSteps"><div><b>1</b><span><strong>先查原因</strong><small>核对 SAT-20 队列、丢弃与逐业务损失</small></span></div><div><b>2</b><span><strong>再做绕行</strong><small>可模拟改走 SAT-21，不执行真实切换</small></span></div><div><b>3</b><span><strong>最后复测</strong><small>切换后的可用度必须用新观测验证</small></span></div></div><div className="satelliteValidationFlow"><span><CheckCircle2 size={13} />本体关系校验</span><i /><span><CheckCircle2 size={13} />时点数据过滤</span><i /><span><CheckCircle2 size={13} />正常业务对照</span><i /><span><CheckCircle2 size={13} />路径约束验算</span></div><div className="satelliteRuleBadge"><ShieldCheck size={15} /><span>{passed} 条领域、诊断和路由规则已通过；时延为模型校验，可用度尚未实测。</span></div>{report && <button type="button" className="satelliteTextButton" onClick={() => onDetail({ conclusions: report.conclusions, rules: report.rule_execution })}>查看完整结论与规则 <ChevronRight size={13} /></button>}</>;
}

function EvidenceSummary({ value }: { value: unknown }) {
  const container = record(value);
  const item = record(container.analysis_item ?? value);
  const rows = array(container.resolved_evidence).map(record);
  if (Array.isArray(value)) return <div className="satelliteEvidenceReadable"><strong>共 {value.length} 条记录</strong><p>主页面只展示最重要的几项，这里保留全部结果供核对。</p></div>;
  const title = text(item.object_id ?? item.service_id ?? item.candidate_id ?? item.title ?? item.rule_id);
  const description = item.mechanism ?? item.description ?? item.reason ?? item.comparison_note ?? item.note;
  return <div className="satelliteEvidenceReadable">{title !== "—" && <h3>{title}</h3>}{description !== undefined && <p>{text(description)}</p>}{item.status !== undefined && <span className="satelliteEvidenceStatus">判断状态：{text(item.status)}</span>}{rows.length > 0 && <><strong>已找到 {rows.length} 条可追溯证据</strong><div>{rows.slice(0, 8).map((row, index) => <p key={index}><b>{text(row.object_id ?? row.service_id ?? row.source_file ?? `证据 ${index + 1}`)}</b><span>{humanEvidence(row)}</span></p>)}</div></>}{!rows.length && description === undefined && <p>此处保存完整规则、路径或指标明细，供需要时核对。</p>}</div>;
}

function humanEvidence(row: Record<string, unknown>): string {
  const known = ["effective_capacity_mbps", "ingress_mbps", "forwarded_mbps", "discarded_mbps", "demand_utilization_pct", "availability_pct", "queue_depth_mb", "event_code"];
  const parts = known.filter((key) => row[key] !== undefined).map((key) => `${FIELD_LABELS[key] ?? key} ${text(row[key])}`);
  return parts.length ? parts.join("；") : text(row.description ?? row.metric ?? row.timestamp ?? row.source_file);
}

function PathLine({ label, nodes }: { label: string; nodes: unknown }) {
  const values = Array.isArray(nodes) ? nodes : typeof nodes === "string" ? [nodes] : [];
  if (!values.length) return null;
  return <div className="satellitePathLine"><span>{label}</span><div>{values.map((node, index) => <span key={index}>{index > 0 && <ArrowRight size={12} />}<code>{typeof node === "object" ? text(record(node).id ?? record(node).node_id ?? node) : text(node)}</code></span>)}</div></div>;
}

function RoutePlans({ report, onEvidence }: { report?: SatelliteReport; onEvidence: (title: string, value: unknown) => void }) {
  const proposals = array(report?.route_options?.proposals);
  if (!proposals.length) return <><EmptyState text={report ? `当前未返回可展示的备选方案（${text(report.route_options?.status)}）。没有方案不代表已完成切换，也可能是数据或容量条件不足。` : "运行后展示备选通信路径、模拟前后变化，以及容量、时延和固定端点限制。"} />{array(report?.route_options?.unresolved_risks).length > 0 && <JsonDetails value={report?.route_options?.unresolved_risks} />}</>;
  return <div className="satelliteRoutePlans">{proposals.map((value, index) => {
    const proposal = record(value);
    const changes = array(proposal.changes);
    const resources = array(proposal.resources);
    const metrics = Object.entries(proposal).filter(([key, val]) => !["id", "name", "title", "changes", "before_nodes", "after_nodes", "limitations", "unresolved_risks", "status"].includes(key) && (typeof val === "number" || typeof val === "boolean"));
    return <article key={index}><header><div><span>方案 {String(index + 1).padStart(2, "0")}</span><h3>{text(proposal.title ?? proposal.name ?? proposal.proposal_id ?? proposal.id ?? "备选通信路径")}</h3></div><span className="satelliteSimulationLabel">{text(proposal.status ?? "模拟方案")}</span></header>{changes.length ? changes.map((changeValue, changeIndex) => {
      const change = record(changeValue);
      const numbers = Object.entries(change).filter(([key, val]) => !["service_id", "before_nodes", "after_nodes"].includes(key) && (typeof val === "number" || typeof val === "boolean"));
      return <div className="satelliteRouteChange" key={changeIndex}><strong>{text(change.service_id ?? `业务 ${changeIndex + 1}`)}</strong><PathLine label="原路径" nodes={change.before_nodes} /><PathLine label="备选路径" nodes={change.after_nodes} />{numbers.length > 0 && <dl className="satelliteRouteMetrics">{numbers.map(([key, val]) => <div key={key}><dt>{FIELD_LABELS[key] ?? key}</dt><dd>{text(val)}</dd></div>)}</dl>}</div>;
    }) : <><PathLine label="原路径" nodes={proposal.before_nodes} /><PathLine label="备选路径" nodes={proposal.after_nodes} /></>}{resources.length > 0 && <div className="satelliteResourceComparison"><h4>资源负载模拟前后对比</h4><p className="satelliteHelper">请求流量的容量验算，不等于实际测得的吞吐量，也不证明可用度 SLA 已达标。</p><div className="satelliteTableScroll"><table className="satelliteCallTable"><thead><tr><th>对象</th><th>原请求负载</th><th>模拟后负载</th><th>容量</th><th>模拟利用率</th></tr></thead><tbody>{resources.map((resource, i) => { const row = record(resource); return <tr key={i}><td>{text(row.object_id)}</td><td>{text(row.before_reserved_demand_mbps)} Mbps</td><td>{text(row.after_reserved_demand_mbps)} Mbps</td><td>{text(row.capacity_mbps)} Mbps</td><td>{text(row.estimated_demand_utilization_pct)}%</td></tr>; })}</tbody></table></div></div>}{metrics.length > 0 && <dl className="satelliteRouteMetrics">{metrics.map(([key, val]) => <div key={key}><dt>{FIELD_LABELS[key] ?? key}</dt><dd>{text(val)}</dd></div>)}</dl>}{strings(proposal.limitations).map((item, i) => <p key={i} className="satelliteRiskLine"><AlertTriangle size={13} />{item}</p>)}<button type="button" className="satelliteTextButton" onClick={() => onEvidence(`方案 ${index + 1}：约束、模拟结果与完整记录`, proposal)}>查看完整方案与约束 <ChevronRight size={13} /></button><JsonDetails value={proposal} /></article>;
  })}{array(report?.route_options?.unresolved_risks).length > 0 && <div className="satelliteMissing"><strong>尚未解决的风险</strong><JsonDetails value={report?.route_options?.unresolved_risks} expanded /></div>}</div>;
}

function NetworkTopology({ topology }: { topology: NonNullable<SatelliteReport["topology"]> }) {
  const nodes = topology.nodes ?? [];
  const columns = Math.max(1, Math.ceil(nodes.length / 3));
  const width = Math.max(720, columns * 108 + 60);
  const positions = new Map(nodes.map((node, index) => [node.id, { x: 54 + (index % columns) * 108, y: 47 + Math.floor(index / columns) * 89 }]));
  return <div className="satelliteTopology"><svg viewBox={`0 0 ${width} 290`} role="img" aria-label="报告返回的卫星网络连接关系"><title>当前报告的网络节点与连接，不表示所有节点均有故障</title>{(topology.edges ?? []).map((edge, index) => {
    const source = positions.get(edge.source); const target = positions.get(edge.target);
    return source && target ? <line key={edge.id ?? index} x1={source.x} y1={source.y} x2={target.x} y2={target.y} /> : null;
  })}{nodes.map((node) => {
    const position = positions.get(node.id)!;
    const ground = /ground|station|地面/i.test(node.type);
    return <g key={node.id} transform={`translate(${position.x},${position.y})`} className={ground ? "is-ground" : ""}><circle r={20} /><text y={4} textAnchor="middle" className="satelliteNodeMark">{ground ? "G" : /service|业务/i.test(node.type) ? "S" : "N"}</text><text y={38} textAnchor="middle">{node.label ?? node.id}</text><title>{`${node.id} · ${node.type}`}</title></g>;
  })}</svg><p>节点与连线来自报告数据。网络连接关系不等于故障传播结论。</p></div>;
}
