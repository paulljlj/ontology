import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, AlertTriangle, ArrowRight, CheckCircle2, ChevronRight, Clock3, Database,
  Download, FileJson, GitBranch, History, Info, Loader2, Network, Play, RadioTower,
  RefreshCw, Route, Satellite, ShieldCheck, X, XCircle,
} from "lucide-react";
import { satelliteApi } from "../satellite-api";
import type { SatelliteCase, SatelliteMcpStatus, SatelliteReport, SatelliteRun, SatelliteSection } from "../satellite-types";

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
  const [requirement, setRequirement] = useState("查看当前网络状态，并对指定待避对象评估备选通信路由，说明约束与未解决风险。");
  const [autoDiagnosis, setAutoDiagnosis] = useState(true);
  const [diagnosisBackend, setDiagnosisBackend] = useState<"local" | "neo4j_mcp">("local");
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

  return <main className="satelliteWorkspace">
    <header className="satelliteHeader">
      <div className="satelliteIdentity"><span className="satelliteLogo"><Satellite size={24} /></span><div><strong>卫星网络分析工作台</strong><small>SATELLITE NETWORK WORKBENCH</small></div></div>
      <div className="satelliteHeaderActions">
        <label className="satelliteHistory"><History size={15} /><span className="srOnly">历史执行记录</span><select value={activeRun?.id ?? ""} onChange={(event) => void selectRun(event.target.value)} disabled={selecting}><option value="">选择执行记录</option>{runs.map((run) => <option key={run.id} value={run.id}>{run.title || run.id.slice(0, 8)} · {STATUS[run.status] ?? run.status}</option>)}</select></label>
        <button className="satelliteIconButton" type="button" aria-label="刷新案例与执行记录" onClick={() => void refresh()} disabled={loading}><RefreshCw size={17} className={loading ? "satelliteSpin" : ""} /></button>
      </div>
    </header>

    <section className="satelliteHero">
      <div><p className="satelliteEyebrow"><Activity size={14} /> 数据诊断与路由模拟</p><h1>看清异常原因，评估备选路径</h1><p>把异常检测、候选证据、正常对照和通信路由方案放在一起，逐项核对。</p></div>
      <div className="satelliteBoundary"><ShieldCheck size={20} /><div><strong>模拟评估，不执行设备切换</strong><span>当前使用合成数据。诊断候选有证据但不等于已经确认硬件故障。</span></div></div>
    </section>

    {error && <div className="satelliteError" role="alert"><AlertTriangle size={19} /><p>{error}</p><button type="button" aria-label="关闭错误提示" onClick={() => setError(null)}><X size={16} /></button></div>}

    <div className="satelliteMainGrid">
      <div className="satelliteWorkColumn">
        <section className="satellitePanel satelliteComposer">
          <div className="satelliteSectionHeading"><h2><GitBranch size={18} /> 分析输入</h2><span className="satelliteMuted">仅接受案例编号和参数</span></div>
          <div className="satelliteInputGrid">
            <label><span>数据案例</span><select value={caseId} onChange={(event) => setCaseId(event.target.value)} disabled={loading || !cases.length}><option value="">{loading ? "正在加载案例…" : "请选择案例"}</option>{cases.map((item) => <option value={item.case_id} key={item.case_id}>{item.case_id} · {item.dataset_kind === "synthetic" ? "合成数据" : item.dataset_kind}</option>)}</select></label>
            <label><span>诊断方式</span><select value={autoDiagnosis ? diagnosisBackend : "off"} onChange={(event) => {
              if (event.target.value === "off") setAutoDiagnosis(false);
              else { setAutoDiagnosis(true); setDiagnosisBackend(event.target.value as "local" | "neo4j_mcp"); }
            }}><option value="local">自动诊断（本地时态图）</option><option value="neo4j_mcp">自动诊断（Neo4j MCP）</option><option value="off">不自动诊断</option></select></label>
            <label><span>待避对象 <small>可选人工覆盖</small></span><input value={avoid} onChange={(event) => setAvoid(event.target.value)} placeholder="留空则采用诊断优先对象；或填 SAT-20" maxLength={600} /></label>
          </div>
          {selectedCase && <div className="satelliteCaseInfo"><span><Satellite size={14} /> {count(selectedCase.satellites)} 颗卫星</span><span><RadioTower size={14} /> {count(selectedCase.ground_stations)} 个地面站</span><span><Network size={14} /> {count(selectedCase.links)} 条链路</span><span><Clock3 size={14} /> 分析时段 {displayTime(selectedCase.analysis_start)} 至 {displayTime(selectedCase.analysis_end_exclusive)}（不含结束时刻）</span></div>}
          <label className="satelliteRequirement"><span>本次需要查看什么</span><textarea value={requirement} onChange={(event) => setRequirement(event.target.value)} rows={2} maxLength={3000} /></label>
          <details className="satelliteAdvanced"><summary>评估时刻与外部诊断输入 <ChevronRight size={14} /></summary><div className="satelliteInputGrid"><label><span>路由评估时刻 at</span><input value={at} onChange={(event) => setAt(event.target.value)} placeholder="带时区的 ISO 时间" /></label><label><span>可读取数据截止时刻 as_of</span><input value={asOf} onChange={(event) => setAsOf(event.target.value)} placeholder="带时区的 ISO 时间" /></label></div><label><span>外部诊断 JSON <small>可选；填写后优先使用它</small></span><textarea className="satelliteCodeInput" value={diagnosisJson} onChange={(event) => setDiagnosisJson(event.target.value)} rows={5} maxLength={200000} placeholder="通常留空，由已接入的同学诊断模块自动生成。" /></label><p className="satelliteHelper">自动诊断只读取观测白名单和截止时刻前的数据，不读取 evaluation。Neo4j MCP 模式需要先启动数据库、导入关系图并配置官方 Server；连接失败会明确报错，不静默退回本地图。</p></details>
          <div className="satellitePresets"><span>演示参数</span><button type="button" onClick={() => usePreset("CASE-001", "SAT-20")}>SAT-20 待避测试</button><button type="button" onClick={() => usePreset("CASE-001", "GS-01")}>GS-01 固定站约束</button><button type="button" onClick={() => usePreset("CASE-008", "SAT-20")}>CASE-008 缺证测试</button></div>
          <p className="satelliteHelper">SAT-20 参数用于拥塞绕行演示，GS-01 检查固定站约束，CASE-008 检查缺证处理。预设只填写参数，不预填诊断结论。</p>
          <div className="satelliteSubmitRow"><p><Info size={14} /> 自动诊断先给候选与依据，再用优先对象验算路线；候选不等于故障定论。</p><button type="button" className="satellitePrimaryButton" onClick={() => void submit()} disabled={submitting || loading || !caseId || busy}>{submitting ? <Loader2 size={17} className="satelliteSpin" /> : <Play size={17} />}{submitting ? "正在提交" : busy ? "执行中" : "生成分析与路由报告"}</button></div>
        </section>

        <section className="satellitePanel satelliteExecution">
          <div className="satelliteSectionHeading"><h2><Activity size={18} /> 执行过程</h2><span className={`satelliteRunState state-${activeRun?.status ?? "idle"}`}>{selecting ? "读取记录中" : activeRun ? STATUS[activeRun.status] ?? activeRun.status : "等待运行"}</span></div>
          {activeRun ? <><div className="satelliteProgress"><span style={{ width: `${progress}%` }} /></div><div className="satelliteProgressCaption"><span>{completed} / {total} 个步骤完成</span><strong>{progress}%</strong></div><ol className="satelliteTaskList">{(activeRun.tasks ?? []).map((task) => <li key={task.id} className={`task-${task.status}`}><TaskIcon status={task.status} /><div><strong>{task.title}</strong><p>{task.description}</p><div className="satelliteTaskMeta"><code>{task.task_key}</code><span>{STATUS[task.status] ?? task.status}</span>{task.started_at && <time>{displayTime(task.started_at)}</time>}</div>{task.outputs?.length > 0 && <p className="satelliteTaskOutput">输出：{task.outputs.map((item) => text(item)).join("、")}</p>}{task.error && <p className="satelliteInlineError">{task.error}</p>}<button type="button" className="satelliteTextButton" onClick={() => setEvidence({ title: `${task.title}：执行证据`, value: task.evidence })}>查看证据 <ChevronRight size={13} /></button></div></li>)}</ol>{!total && <EmptyState text="服务尚未返回执行步骤。" />}{activeRun.error && <p className="satelliteInlineError" role="alert">{activeRun.error}</p>}</> : <EmptyState text="选择案例并发起运行后，这里展示后端真实返回的步骤、输出和错误。" />}
        </section>

        <section className="satellitePanel">
          <div className="satelliteSectionHeading"><h2><Network size={18} /> 当前网络关系</h2><span className="satelliteMuted">报告中的实际节点与连接</span></div>
          {report?.topology?.nodes?.length ? <NetworkTopology topology={report.topology} /> : <EmptyState text="尚无拓扑结果。等待后端读取所选时段的连接关系，不生成示意节点替代数据。" />}
        </section>

        <section className="satellitePanel">
          <div className="satelliteSectionHeading"><h2><Route size={18} /> 备选路径与模拟对照</h2><span className="satelliteSimulationLabel">仅方案，不切换</span></div>
          <RoutePlans report={report} onEvidence={openEvidence} />
        </section>

        <section className="satellitePanel satelliteMcpPanel">
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
        <ReportPart number="01" title="异常概况"><p>{report?.overview?.summary ?? "运行后展示观测到的网络状态，不预填异常数量或下降幅度。"}</p>{array(report?.overview?.metrics).length > 0 && <div className="satelliteMetricList">{report!.overview.metrics!.map((metric, index) => <div key={index}><span>{metric.label}</span><strong>{text(metric.value)}<small>{metric.unit}</small></strong></div>)}</div>}{array(report?.overview?.observations).length > 0 && <button type="button" className="satelliteTextButton" onClick={() => setEvidence({ title: "原始观测摘要", value: report?.overview.observations })}>查看观测记录 <ChevronRight size={13} /></button>}</ReportPart>
        <ReportPart number="02" title="可能原因"><ReportItems section={report?.causes} empty="本次没有诊断原因结论。手动输入待避对象本身不会生成根因。" onEvidence={openEvidence} /></ReportPart>
        <ReportPart number="03" title="需要关注的对象"><ReportItems section={report?.watch_items} empty="尚无诊断提供的风险提示。潜在风险不等于已经发生故障。" onEvidence={openEvidence} /></ReportPart>
        <ReportPart number="04" title="备选通信路由"><p>{report ? `${array(report.route_options?.proposals).length} 项路径方案，${text(report.route_options?.status)}。` : "根据待避对象，评估可用路径与容量约束。"}</p><p className="satelliteHelper">下方与左侧展示的前后变化均为模拟估计，不是已经实施的优化效果。</p>{strings(report?.route_options?.limitations).map((item, index) => <p key={index} className="satelliteRiskLine"><AlertTriangle size={13} />{item}</p>)}</ReportPart>
        <ReportPart number="05" title="影响与其他分析"><ReportItems section={report?.impact} empty="等待运行结果，展示受到影响的业务及相关约束。" onEvidence={openEvidence} /></ReportPart>
        <ReportPart number="06" title="结论与待查事项">{strings(report?.conclusions?.items).length ? <ul>{strings(report?.conclusions?.items).map((item, index) => <li key={index}>{item}</li>)}</ul> : <p>尚无结论。先完成数据读取，再核查可行性与证据缺口。</p>}{strings(report?.conclusions?.missing_evidence).length > 0 && <div className="satelliteMissing"><strong>还缺哪些证据</strong><ul>{strings(report?.conclusions?.missing_evidence).map((item, index) => <li key={index}>{item}</li>)}</ul></div>}</ReportPart>
        <div className="satelliteDownloads"><h3><Download size={15} /> 报告与运行记录</h3>{activeRun?.artifacts?.length ? activeRun.artifacts.map((artifact) => <a key={artifact.id} href={satelliteApi.artifactUrl(artifact.download_url)} target="_blank" rel="noreferrer"><FileJson size={16} /><span>{typeof artifact.metadata?.display_name === "string" ? artifact.metadata.display_name : artifact.name}<small>{artifact.mime_type.includes("json") ? "结构化 JSON" : artifact.mime_type.includes("html") ? "可阅读 HTML" : artifact.kind}</small></span><Download size={14} /></a>) : <p>运行完成后，下载后端实际生成的 JSON / HTML 文件。</p>}</div>
      </aside>
    </div>
    <footer className="satelliteFooter"><span>本体关系与能力编排</span><p>合成数据用于验证流程。诊断结论、路由模拟和真实设备操作严格区分。</p></footer>
    {evidence && <div className="satelliteEvidenceOverlay" role="dialog" aria-modal="true" aria-label={evidence.title} onClick={() => setEvidence(null)}><section onClick={(event) => event.stopPropagation()}><header><div><span>执行记录与证据</span><h2>{evidence.title}</h2></div><button type="button" className="satelliteIconButton" aria-label="关闭证据" onClick={() => setEvidence(null)}><X size={20} /></button></header><p>以下内容来自当前运行返回的数据。引用编号只有在返回了对应来源记录时，才构成可追溯证据。</p><JsonDetails value={evidence.value} expanded /><button type="button" className="satellitePrimaryButton" onClick={() => setEvidence(null)}>返回报告</button></section></div>}
  </main>;
}

function TaskIcon({ status }: { status: string }) {
  if (status === "running") return <Loader2 size={18} className="satelliteSpin" />;
  if (status === "succeeded") return <CheckCircle2 size={18} />;
  if (status === "failed") return <XCircle size={18} />;
  return <span className="satellitePendingCircle" />;
}
function EmptyState({ text: message }: { text: string }) { return <div className="satelliteEmpty"><Network size={28} /><p>{message}</p></div>; }
function ReportPart({ number, title, children }: { number: string; title: string; children: React.ReactNode }) {
  return <section className="satelliteReportPart"><h3><span>{number}</span>{title}</h3>{children}</section>;
}
function JsonDetails({ value, expanded = false }: { value: unknown; expanded?: boolean }) {
  return <details className="satelliteJson" open={expanded}><summary>结构化数据与原始字段</summary><pre>{JSON.stringify(value ?? null, null, 2)}</pre></details>;
}
function ReportItems({ section, empty, onEvidence }: { section?: SatelliteSection; empty: string; onEvidence: (title: string, value: unknown) => void }) {
  const items = array(section?.items);
  return <>{section?.note && <p>{section.note}</p>}{items.length ? <div className="satelliteReportItems">{items.map((value, index) => {
    const item = record(value);
    const title = text(item.title ?? item.name ?? item.object_id ?? item.candidate_id ?? item.hypothesis ?? item.cause ?? `分析项 ${index + 1}`);
    const description = item.description ?? item.reason ?? item.mechanism ?? item.note ?? item.summary;
    return <article key={index}><strong>{title}</strong>{description !== undefined && <p>{text(description)}</p>}{item.status !== undefined && <span className="satelliteItemState">{text(item.status)}</span>}<button type="button" className="satelliteTextButton" onClick={() => onEvidence(title, item)}>查看依据与字段 <ChevronRight size={12} /></button></article>;
  })}</div> : <p className="satelliteHelper">{empty}</p>}</>;
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
