import {
  Activity,
  BarChart3,
  BrainCircuit,
  Check,
  CheckCircle2,
  Circle,
  Database,
  Download,
  FileOutput,
  FileText,
  GitBranch,
  History,
  Loader2,
  Lightbulb,
  Network,
  Play,
  RefreshCw,
  Workflow,
  X,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  ExecutionTask,
  Graph,
  OntologyInstance,
  OntologyRelation,
  ReportRun,
} from "../types";
import Topology from "./Topology";

const SAMPLE_REQUIREMENT =
  "分析最近三个月各区域、各产品的销售额和回款情况，自动清洗重复与缺失数据，生成经营分析报告，并说明完整执行路径和验证结果。";

type OntologyReasoning = {
  input_classes?: string[];
  matched_concepts?: string[];
  rule?: string;
  inference?: string;
};

type ResultKpi = {
  label: string;
  value: number;
  display: string;
  format?: string;
  tone?: string;
};

type ResultChart = {
  title: string;
  dimension?: string;
  series: Array<{ key: string; label: string; format?: string }>;
  items: Array<{ label: string; records?: number; values: Record<string, number> }>;
};

export function ReportWorkbench() {
  const [requirement, setRequirement] = useState(SAMPLE_REQUIREMENT);
  const [runs, setRuns] = useState<ReportRun[]>([]);
  const [activeRun, setActiveRun] = useState<ReportRun | null>(null);
  const [selectedOntology, setSelectedOntology] = useState<OntologyInstance | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [resultOpen, setResultOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadRuns = useCallback(async (preferredId?: string) => {
    const rows = await api.reportRuns();
    setRuns(rows);
    setActiveRun((current) => rows.find((run) => run.id === preferredId) ?? current ?? rows[0] ?? null);
  }, []);

  useEffect(() => {
    loadRuns().catch((reason) => setError(reason instanceof Error ? reason.message : "加载执行记录失败。"));
  }, [loadRuns]);

  useEffect(() => {
    if (!activeRun || !["planning", "running"].includes(activeRun.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const fresh = await api.reportRun(activeRun.id);
        setActiveRun(fresh);
        setRuns((current) => current.map((run) => (run.id === fresh.id ? fresh : run)));
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "刷新执行状态失败。");
      }
    }, 450);
    return () => window.clearInterval(timer);
  }, [activeRun?.id, activeRun?.status]);

  async function submit() {
    const goal = requirement.trim();
    if (goal.length < 8) {
      setError("请用一句完整的话描述目标、期望结果或验收要求。");
      return;
    }
    setSubmitting(true);
    setResultOpen(false);
    setSelectedOntology(null);
    setError(null);
    try {
      const created = await api.createReportRun(goal, "本体智能体执行");
      setActiveRun(created);
      setRuns((current) => [created, ...current.filter((run) => run.id !== created.id)]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "启动执行失败。");
    } finally {
      setSubmitting(false);
    }
  }

  const progress = useMemo(() => {
    if (!activeRun) return 0;
    const reported = Number(activeRun.summary.progress);
    if (Number.isFinite(reported)) return reported;
    const completed = activeRun.tasks.filter((task) => task.status === "succeeded").length;
    return activeRun.tasks.length ? Math.round((completed / activeRun.tasks.length) * 100) : 0;
  }, [activeRun]);

  const visibleTasks = useMemo(() => revealTasks(activeRun?.tasks ?? []), [activeRun]);
  const runtimeGraph = useMemo(() => buildRuntimeGraph(activeRun, visibleTasks), [activeRun, visibleTasks]);

  useEffect(() => {
    if (!activeRun) return;
    const running = visibleTasks.find((task) => task.status === "running") ?? visibleTasks[visibleTasks.length - 1];
    const nodeId = running ? `${activeRun.id}-task-${running.task_key}` : `${activeRun.id}-goal`;
    setSelectedOntology(runtimeGraph.nodes.find((node) => node.id === nodeId) ?? runtimeGraph.nodes[0] ?? null);
  }, [activeRun?.updated_at, runtimeGraph, visibleTasks]);

  const activeTask =
    visibleTasks.find((task) => task.status === "running") ??
    [...visibleTasks].reverse().find((task) => task.status === "succeeded") ??
    visibleTasks[0];
  const activeReasoning = reasoningOf(activeTask);

  const selectGraphNode = useCallback((instance: OntologyInstance) => {
    setSelectedOntology(instance);
  }, []);

  return (
    <main className="goalShell">
      <header className="goalHeader">
        <div className="goalBrand">
          <div className="brandMark"><Network size={23} /></div>
          <div>
            <strong>本体智能体工作台</strong>
            <span>ONTOLOGY AGENT WORKBENCH</span>
          </div>
        </div>
        <div className="headerActions">
          <label className="runHistory">
            <History size={15} />
            <span>执行记录</span>
            <select
              value={activeRun?.id ?? ""}
              onChange={(event) => {
                const selected = runs.find((run) => run.id === event.target.value) ?? null;
                setActiveRun(selected);
                setSelectedOntology(null);
                setResultOpen(false);
              }}
            >
              <option value="">暂无记录</option>
              {runs.map((run) => <option key={run.id} value={run.id}>{run.title} · {statusText(run.status)}</option>)}
            </select>
          </label>
          <button className="quietButton" onClick={() => loadRuns(activeRun?.id)} title="刷新执行记录">
            <RefreshCw size={16} />
          </button>
        </div>
      </header>

      <section className="goalIntro">
        <div>
          <span className="eyebrow"><GitBranch size={14} /> ONTOLOGY WORKFLOW</span>
          <h1>本体驱动的任务执行工作台</h1>
          <p>从自然语言需求到任务拆解、规则推理、能力编排与结果交付，完整过程可观察、可追溯。</p>
        </div>
        <div className="capabilityRail" aria-label="本体执行阶段">
          <div><small>01</small><span>需求建模</span></div>
          <div><small>02</small><span>本体推理</span></div>
          <div><small>03</small><span>能力编排</span></div>
          <div><small>04</small><span>结果验证</span></div>
        </div>
      </section>

      <section className="goalComposer">
        <div className="composerIcon"><BrainCircuit size={23} /></div>
        <label>
          <span>输入执行需求</span>
          <textarea
            rows={3}
            value={requirement}
            onChange={(event) => setRequirement(event.target.value)}
            placeholder="描述目标、约束和期望产物，不需要预先拆解任务。"
          />
        </label>
        <button className="executeButton" onClick={submit} disabled={submitting || activeRun?.status === "running"}>
          {submitting ? <Loader2 className="spin" size={18} /> : <Play size={18} />}
          运行需求
        </button>
      </section>

      {error && (
        <div className="goalError">
          <XCircle size={17} /><span>{error}</span><button onClick={() => setError(null)}><X size={15} /></button>
        </div>
      )}

      <section className="runtimeSummary">
        <div>
          <span className={`liveDot ${activeRun?.status ?? "idle"}`} />
          <strong>{activeRun ? statusText(activeRun.status) : "等待需求"}</strong>
          <span>{activeRun ? activeRun.requirement : "输入目标后，执行流程和本体图谱会在同一页面同步生长。"}</span>
        </div>
        <b>{progress}%</b>
        <div className="globalProgress"><span style={{ width: `${progress}%` }} /></div>
      </section>

      <section className="runtimeGrid">
        <section className="processPanel">
          <div className="panelHeading">
            <div><Workflow size={18} /><h2>执行流程</h2></div>
            <span>{visibleTasks.length}/{activeRun?.tasks.length ?? 0} 步骤</span>
          </div>
          <div className="flowCanvas">
            <article className={`goalNode ${activeRun ? "ready" : "waiting"}`}>
              <div className="flowIndex"><Network size={15} /></div>
              <div>
                <small>需求目标</small>
                <strong>{activeRun ? activeRun.requirement : "等待输入一个目标"}</strong>
                <p>自然语言需求将先被本体编译成可执行、可验收的结果合同。</p>
              </div>
            </article>

            {visibleTasks.map((task) => (
              <FlowTask
                key={task.id}
                task={task}
                selected={selectedOntology?.id === `${activeRun?.id}-task-${task.task_key}`}
                onSelect={() => {
                  const node = runtimeGraph.nodes.find((item) => item.id === `${activeRun?.id}-task-${task.task_key}`);
                  if (node) setSelectedOntology(node);
                }}
              />
            ))}

            {activeRun?.status === "succeeded" && (
              <article className="resultNode">
                <div className="resultNodeIcon"><CheckCircle2 size={20} /></div>
                <div>
                  <small>结果交付</small>
                  <strong>结果已生成并通过验证</strong>
                  <p>{activeRun.artifacts.length} 个产物 · {activeRun.tasks.length} 个步骤 · 全路径可追溯</p>
                </div>
                <button onClick={() => setResultOpen(true)}><FileOutput size={16} /> 查看结果</button>
              </article>
            )}
          </div>
        </section>

        <section className="ontologyPanel">
          <div className="panelHeading">
            <div><GitBranch size={18} /><h2>实时本体知识图谱</h2></div>
            <div className="graphLegend">
              <span><b className="nodeKind project">Project</b>项目类</span>
              <span><b className="nodeKind feature">Feature</b>需求类</span>
              <span><b className="nodeKind spec">Spec</b>规格类</span>
              <span><b className="nodeKind plan">Plan</b>计划类</span>
              <span><b className="nodeKind task">Task</b>任务类</span>
              <span><b className="groupKind semantic">语义类</b></span>
              <span><b className="groupKind capability">能力类</b></span>
              <span><b className="groupKind delivery">产物类</b></span>
              <span><b className="groupKind evidence">验证类</b></span>
              <span><i className="solid" />显式关系</span>
              <span><i className="inferred" />推理关系</span>
            </div>
          </div>
          {activeRun ? (
            <>
              <div className="runtimeTopology">
                <Topology graph={runtimeGraph} selected={selectedOntology} onSelect={selectGraphNode} />
              </div>
              <div className="reasoningConsole">
                <div className="reasoningTitle">
                  <BrainCircuit size={17} />
                  <div><strong>推理机判断</strong><span>{activeTask?.title ?? "等待推理"}</span></div>
                  {activeTask && <b>{statusText(activeTask.status)}</b>}
                </div>
                <div className="reasoningPath">
                  {(activeReasoning.input_classes ?? []).map((name) => <span key={name}>{name}</span>)}
                  <i>→</i>
                  {(activeReasoning.matched_concepts ?? []).map((name) => <span className="matched" key={name}>{name}</span>)}
                </div>
                <dl>
                  <div><dt>触发规则</dt><dd>{activeReasoning.rule ?? activeTask?.skill_spec.ontology_rule ?? "等待规则匹配"}</dd></div>
                  <div><dt>推理结论</dt><dd>{activeReasoning.inference ?? "执行到该节点后显示推理结论。"}</dd></div>
                  <div><dt>当前节点</dt><dd>{selectedOntology ? ontologyDisplayLabel(selectedOntology) : "未选择"}</dd></div>
                </dl>
              </div>
            </>
          ) : (
            <div className="graphWaiting">
              <Network size={42} />
              <strong>知识图谱等待生长</strong>
              <p>执行后，目标、结果规格、任务、能力、产物与验证节点会随推理过程逐步出现。</p>
            </div>
          )}
        </section>
      </section>

      {resultOpen && activeRun && (
        <ResultDialog run={activeRun} onClose={() => setResultOpen(false)} />
      )}
    </main>
  );
}

function FlowTask({
  task,
  selected,
  onSelect,
}: {
  task: ExecutionTask;
  selected: boolean;
  onSelect: () => void;
}) {
  const reasoning = reasoningOf(task);
  return (
    <article className={`flowTask ${task.status} ${selected ? "selected" : ""}`} onClick={onSelect}>
      <div className="flowConnector" />
      <div className="flowIndex"><TaskStatusIcon status={task.status} /></div>
      <div className="flowTaskBody">
        <div className="flowTaskTitle">
          <div><small>STEP {String(task.order_index).padStart(2, "0")}</small><strong>{task.title}</strong></div>
          <span>{statusText(task.status)}</span>
        </div>
        <p>{task.description}</p>
        <div className="executionBinding">
          <b>Skill</b><code>{task.skill_spec.name}</code>
          {(task.skill_spec.mcp_bindings ?? []).map((binding) => <span key={binding}>{binding}</span>)}
        </div>
        {(task.status === "running" || task.status === "succeeded") && (
          <div className="ontologyDecision">
            <BrainCircuit size={14} />
            <span><b>本体规则</b>{reasoning.rule ?? task.skill_spec.ontology_rule}</span>
          </div>
        )}
        {task.status === "running" && <div className="stepProgress"><span /></div>}
        {task.outputs.length > 0 && <div className="flowOutputs">输出：{task.outputs.join(" · ")}</div>}
        {task.error && <div className="flowFailure">{task.error}</div>}
      </div>
    </article>
  );
}

function ResultDialog({ run, onClose }: { run: ReportRun; onClose: () => void }) {
  const answer = typeof run.summary.answer === "string"
    ? run.summary.answer
    : `任务已完成，共生成 ${run.artifacts.length} 项交付结果。`;
  const highlights = stringList(run.summary.highlights);
  const recommendations = stringList(run.summary.recommendations);
  const kpis = resultKpis(run.summary.kpis);
  const charts = resultCharts(run.summary.charts);
  return (
    <div className="resultOverlay" role="dialog" aria-modal="true" aria-label="执行结果">
      <div className="resultDialog">
        <header>
          <div><span className="eyebrow"><CheckCircle2 size={14} /> 交付验证通过</span><h2>结果回答与报告</h2></div>
          <button onClick={onClose} title="关闭"><X size={18} /></button>
        </header>

        <section className="resultAnswer">
          <div className="sectionLabel"><Lightbulb size={17} /> 问题回答</div>
          <p>{answer}</p>
          {highlights.length > 0 && <ul>{highlights.map((item) => <li key={item}>{item}</li>)}</ul>}
        </section>

        <div className="resultStats">
          {kpis.length > 0 ? kpis.map((item) => (
            <ResultStat key={item.label} label={item.label} value={item.display} tone={item.tone} />
          )) : (
            <>
              <ResultStat label="输入记录" value={run.summary.input_rows} />
              <ResultStat label="清洗后记录" value={run.summary.output_rows} />
              <ResultStat label="移除重复" value={run.summary.duplicates_removed} />
              <ResultStat label="本体推理" value={`${run.tasks.length} 次`} />
            </>
          )}
        </div>

        {charts.length > 0 && (
          <section className="resultVisuals">
            <div className="sectionLabel"><BarChart3 size={16} /> 数据对比</div>
            <div className="resultChartGrid">{charts.map((chart) => <ResultChartView key={chart.title} chart={chart} />)}</div>
          </section>
        )}

        {recommendations.length > 0 && (
          <section className="resultRecommendations">
            <div className="sectionLabel"><Lightbulb size={16} /> 建议</div>
            <ol>{recommendations.map((item) => <li key={item}>{item}</li>)}</ol>
          </section>
        )}

        <div className="resultNarrative">
          <section><small>任务目标</small><p>{run.result_contract.goal ?? run.requirement}</p></section>
          <section><small>数据来源</small><p>{run.summary.source_mode === "autonomous_demo" ? "内置演示数据源。用于验证流程，正式分析需连接真实数据源。" : "已连接的数据源。"}</p></section>
        </div>
        <section className="resultPath">
          <div className="sectionLabel"><Activity size={16} /> 系统执行路径</div>
          <div>{run.tasks.map((task) => <span key={task.id}><Check size={13} />{task.title}</span>)}</div>
        </section>
        <section className="resultFiles">
          <div className="sectionLabel"><FileOutput size={16} /> 面向用户的报告</div>
          <div className="resultFileGrid">
            {run.artifacts.map((artifact) => (
              <a key={artifact.id} href={api.artifactUrl(artifact.download_url)}>
                <div className="fileIcon">{artifact.mime_type.includes("sheet") ? <Database size={20} /> : artifact.mime_type.includes("markdown") ? <FileText size={20} /> : <BarChart3 size={20} />}</div>
                <span>
                  <strong>{metadataText(artifact.metadata, "display_name") || artifact.name}</strong>
                  <small>{metadataText(artifact.metadata, "description") || `${artifact.kind} · ${formatBytes(artifact.size)}`}</small>
                </span>
                <Download size={17} />
              </a>
            ))}
          </div>
        </section>
        <p className="resultFootnote">页面先给出结论和可视化；下载文件用于阅读、汇报和执行审计，不再把原始 CSV/JSON 作为用户交付。</p>
      </div>
    </div>
  );
}

function ResultStat({ label, value, tone = "neutral" }: { label: string; value: unknown; tone?: string }) {
  return <div className={`tone-${tone}`}><span>{label}</span><strong>{value == null ? "—" : String(value)}</strong></div>;
}

function ResultChartView({ chart }: { chart: ResultChart }) {
  const maximum = Math.max(1, ...chart.items.flatMap((item) => chart.series.map((series) => Number(item.values[series.key]) || 0)));
  return (
    <article className="resultChart">
      <div className="resultChartTitle">
        <strong>{chart.title}</strong>
        <span>{chart.series.map((series) => series.label).join(" / ")}</span>
      </div>
      <div className="resultChartRows">
        {chart.items.map((item) => (
          <div className="resultChartRow" key={item.label}>
            <span title={item.label}>{item.label}</span>
            <div>
              {chart.series.map((series, index) => {
                const value = Number(item.values[series.key]) || 0;
                return <i key={series.key} className={index ? "secondary" : ""} style={{ width: `${Math.max(1.5, value / maximum * 100)}%` }} />;
              })}
            </div>
            <em>{chart.series.map((series) => formatResultValue(item.values[series.key], series.format)).join(" / ")}</em>
          </div>
        ))}
      </div>
    </article>
  );
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function resultKpis(value: unknown): ResultKpi[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!isRecord(item) || typeof item.label !== "string") return [];
    const numericValue = Number(item.value);
    return [{
      label: item.label,
      value: Number.isFinite(numericValue) ? numericValue : 0,
      display: typeof item.display === "string" ? item.display : String(item.value ?? "—"),
      format: typeof item.format === "string" ? item.format : undefined,
      tone: typeof item.tone === "string" ? item.tone : undefined,
    }];
  });
}

function resultCharts(value: unknown): ResultChart[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!isRecord(item) || typeof item.title !== "string" || !Array.isArray(item.series) || !Array.isArray(item.items)) return [];
    const series = item.series.flatMap((entry) => {
      if (!isRecord(entry) || typeof entry.key !== "string") return [];
      return [{ key: entry.key, label: typeof entry.label === "string" ? entry.label : entry.key, format: typeof entry.format === "string" ? entry.format : undefined }];
    });
    const items = item.items.flatMap((entry) => {
      if (!isRecord(entry) || typeof entry.label !== "string" || !isRecord(entry.values)) return [];
      const values = Object.fromEntries(Object.entries(entry.values).map(([key, raw]) => [key, Number(raw) || 0]));
      return [{ label: entry.label, records: Number(entry.records) || 0, values }];
    });
    return [{ title: item.title, dimension: typeof item.dimension === "string" ? item.dimension : undefined, series, items }];
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function metadataText(metadata: Record<string, unknown>, key: string): string {
  return typeof metadata[key] === "string" ? metadata[key] : "";
}

function formatResultValue(value: number | undefined, format?: string): string {
  const number = Number(value) || 0;
  if (format === "percent") return `${(number * 100).toFixed(1)}%`;
  if (format === "currency") return `¥${number.toLocaleString("zh-CN", { maximumFractionDigits: 0 })}`;
  return number.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function TaskStatusIcon({ status }: { status: ExecutionTask["status"] }) {
  if (status === "succeeded") return <Check size={15} />;
  if (status === "failed") return <XCircle size={15} />;
  if (status === "running") return <Loader2 className="spin" size={15} />;
  return <Circle size={13} />;
}

function reasoningOf(task?: ExecutionTask): OntologyReasoning {
  if (!task) return {};
  const value = task.evidence?.ontology_reasoning;
  return value && typeof value === "object" ? value as OntologyReasoning : {};
}

function revealTasks(tasks: ExecutionTask[]) {
  if (!tasks.length) return [];
  const progressed = tasks.filter((task) => task.status !== "pending");
  if (!progressed.length) return tasks.slice(0, 1);
  const lastOrder = Math.max(...progressed.map((task) => task.order_index));
  const allDone = progressed.length === tasks.length;
  return tasks.filter((task) => task.order_index <= lastOrder + (allDone ? 0 : 1));
}

function buildRuntimeGraph(run: ReportRun | null, tasks: ExecutionTask[]): Graph {
  if (!run) return { nodes: [], edges: [] };
  const nodes: OntologyInstance[] = [];
  const edges: OntologyRelation[] = [];
  const node = (id: string, className: string, title: string, status: string, properties: Record<string, unknown>) => {
    nodes.push({
      id,
      class_id: className,
      class_name: className,
      title,
      status,
      properties: {
        ontology_category: ontologyCategory(className),
        ontology_group: ontologyGroupLabel(className),
        ...properties,
      },
      created_at: run.created_at,
      updated_at: run.updated_at,
    });
  };
  const edge = (source: string, target: string, type: string, inferred = false, reason = "") => {
    edges.push({
      id: `${source}-${type}-${target}`,
      source_id: source,
      target_id: target,
      type,
      properties: { inferred, reason },
      inferred,
      reason,
      created_at: run.created_at,
    });
  };

  const projectId = `${run.id}-project`;
  const featureId = `${run.id}-feature`;
  const goalId = `${run.id}-goal`;
  const specId = `${run.id}-spec`;
  const planId = `${run.id}-plan`;
  node(projectId, "Project", "本体智能体执行项目", run.status, { workflow_type: run.workflow_type });
  node(featureId, "Feature", compact(run.requirement, 38), run.status, { requirement: run.requirement });
  node(goalId, "Goal", compact(run.requirement, 38), run.status, { requirement: run.requirement });
  node(specId, "ReportSpecification", "动态结果合同", taskState(tasks[0]), run.result_contract);
  node(planId, "Plan", `动态执行计划 · ${tasks.length} 个任务`, taskState(tasks[0]), {
    task_count: tasks.length,
    task_keys: tasks.map((task) => task.task_key),
  });
  edge(projectId, featureId, "HAS_FEATURE", false, "项目显式包含当前用户需求");
  edge(featureId, goalId, "FORMULATES_GOAL", true, "从自然语言 Feature 推导结构化 Goal");
  edge(goalId, specId, "INFERRED_AS", true, "目标包含分析与交付意图，推导 ReportSpecification");
  edge(specId, planId, "HAS_PLAN", true, "根据结果合同推导动态执行计划");

  const metricIds = (run.result_contract.metrics ?? []).map((metric, index) => {
    const id = `${run.id}-metric-${index}`;
    node(id, "MetricDefinition", metric, taskState(tasks.find((task) => task.task_key === "calculate_summary")), { metric });
    edge(specId, id, "DEFINES_METRIC", true, `需求明确要求指标：${metric}`);
    return id;
  });
  const dimensionIds = (run.result_contract.dimensions ?? [])
    .filter((dimension) => !dimension.startsWith("系统自动"))
    .map((dimension, index) => {
      const id = `${run.id}-dimension-${index}`;
      node(id, "Dimension", dimension, taskState(tasks.find((task) => task.task_key === "compare_dimensions")), { dimension });
      edge(specId, id, "GROUPS_BY", true, `需求明确要求维度：${dimension}`);
      return id;
    });
  (run.result_contract.analysis_intents ?? []).forEach((intent, index) => {
    const id = `${run.id}-intent-${index}`;
    node(id, "AnalysisIntent", intentText(intent), taskState(tasks[0]), { intent });
    edge(goalId, id, "MATCHES_INTENT", true, `自然语言命中 ${intent}`);
    edge(id, specId, "CONSTRAINS", true, "分析意图约束结果合同与任务计划");
  });
  const timeScopeId = run.result_contract.time_scope ? `${run.id}-time-scope` : "";
  if (run.result_contract.time_scope) {
    node(timeScopeId, "TimeScope", run.result_contract.time_scope.label ?? "目标期间", taskState(tasks.find((task) => task.task_key === "scope_time")), run.result_contract.time_scope);
    edge(specId, timeScopeId, "APPLIES_SCOPE", true, "需求包含时间范围");
  }

  let previousId = planId;
  tasks.forEach((task) => {
    const taskId = `${run.id}-task-${task.task_key}`;
    const skillId = `${run.id}-skill-${task.task_key}`;
    const reasoning = reasoningOf(task);
    node(taskId, "ExecutableTask", task.title, task.status, {
      description: task.description,
      rule: reasoning.rule ?? task.skill_spec.ontology_rule,
      inference: reasoning.inference,
    });
    node(skillId, "SkillDefinition", task.skill_spec.name ?? "generated-skill", task.status, {
      capabilities: task.skill_spec.required_capabilities,
      mcp_bindings: task.skill_spec.mcp_bindings,
    });
    edge(previousId, taskId, previousId === planId ? "HAS_TASK" : "PRECEDES", true, reasoning.rule ?? "任务依赖规则");
    edge(taskId, skillId, "IMPLEMENTED_BY", false, "Skill 提供 Task 所需能力");
    if (task.task_key === "calculate_summary") metricIds.forEach((metricId) => edge(taskId, metricId, "COMPUTES"));
    if (task.task_key === "compare_dimensions") dimensionIds.forEach((dimensionId) => edge(taskId, dimensionId, "USES_DIMENSION"));
    if (task.task_key === "scope_time" && timeScopeId) edge(taskId, timeScopeId, "APPLIES");
    previousId = taskId;
  });

  run.artifacts.forEach((artifact) => {
    const artifactId = `${run.id}-artifact-${artifact.id}`;
    node(artifactId, "Artifact", artifact.name, "ready", { kind: artifact.kind, size: artifact.size });
    const producer = tasks.find((task) => task.id === artifact.task_id);
    edge(producer ? `${run.id}-task-${producer.task_key}` : previousId, artifactId, "PRODUCES_ARTIFACT");
  });

  if (run.status === "succeeded") {
    const verificationId = `${run.id}-verification`;
    const bundleId = `${run.id}-bundle`;
    node(verificationId, "Verification", "验收证据通过", "succeeded", { criteria: run.result_contract.acceptance_criteria });
    node(bundleId, "DeliveryBundle", "最终交付包", "succeeded", { artifact_count: run.artifacts.length });
    edge(previousId, verificationId, "VERIFIED_BY", true, "全部 AcceptanceCriterion 已满足");
    edge(verificationId, bundleId, "SATISFIES", true, "验证通过后组织交付包");
  }
  return { nodes, edges };
}

function taskState(task?: ExecutionTask) {
  if (!task) return "pending";
  return task.status === "succeeded" ? "ready" : task.status;
}

function ontologyCategory(className: string) {
  if (className === "ReportSpecification" || className === "Spec") return "Spec";
  if (className === "ExecutableTask" || className === "Task") return "Task";
  return className;
}

function ontologyGroupLabel(className: string) {
  if (["Project", "Feature", "Spec", "ReportSpecification", "Plan", "Task", "ExecutableTask"].includes(className)) return "主干类";
  if (["Goal", "AnalysisIntent", "TimeScope", "Dimension", "MetricDefinition", "UserStory", "Clarification"].includes(className)) return "语义类";
  if (["SkillDefinition", "DataModel", "Contract", "ADR"].includes(className)) return "能力类";
  if (["Artifact", "DeliveryBundle"].includes(className)) return "产物类";
  if (["Verification", "Acceptance", "Checklist", "Reflection", "ExecutionLog", "ServiceLog"].includes(className)) return "验证类";
  return "扩展类";
}

function ontologyDisplayLabel(instance: OntologyInstance) {
  const category = String(instance.properties.ontology_category ?? ontologyCategory(instance.class_name));
  const group = String(instance.properties.ontology_group ?? ontologyGroupLabel(instance.class_name));
  const concreteType = category === instance.class_name ? category : `${category} / ${instance.class_name}`;
  return `${group} · ${concreteType} · ${instance.title}`;
}

function compact(value: string, max: number) {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

function statusText(status: string) {
  return ({ planning: "规划中", pending: "等待", running: "执行中", succeeded: "已完成", failed: "失败", idle: "等待" } as Record<string, string>)[status] ?? status;
}

function intentText(intent: string) {
  return ({
    data_quality: "数据质量",
    descriptive_analysis: "描述性分析",
    time_scope: "时间范围",
    dimension_comparison: "维度对比",
    trend_analysis: "趋势分析",
    collection_analysis: "销售回款分析",
    anomaly_detection: "异常识别",
  } as Record<string, string>)[intent] ?? intent;
}

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}
