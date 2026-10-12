import {
  Activity,
  Boxes,
  CheckCircle2,
  GitBranch,
  GitCommitHorizontal,
  Loader2,
  Maximize2,
  Minus,
  Play,
  Plus,
  RefreshCw,
  Search,
  ServerCog,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { Graph, OntologyClass, OntologyInstance } from "./types";
import Topology from "./components/Topology";

const CORE_CLASSES = ["Project", "Feature", "Spec", "Plan", "Task", "Checklist", "ExecutionLog", "ServiceLog"];
const PRIORITY_OPTIONS = [
  { value: "low", label: "低" },
  { value: "medium", label: "中" },
  { value: "high", label: "高" },
  { value: "critical", label: "紧急" },
];

type ComposerState = {
  title: string;
  description: string;
  priority: string;
  tags: string;
};

const EMPTY_COMPOSER: ComposerState = {
  title: "",
  description: "",
  priority: "medium",
  tags: "",
};

export function App() {
  const [classes, setClasses] = useState<OntologyClass[]>([]);
  const [instances, setInstances] = useState<OntologyInstance[]>([]);
  const [graph, setGraph] = useState<Graph>({ nodes: [], edges: [] });
  const [selectedClass, setSelectedClass] = useState("Feature");
  const [selected, setSelected] = useState<OntologyInstance | null>(null);
  const [query, setQuery] = useState("");
  const [composer, setComposer] = useState<ComposerState>(EMPTY_COMPOSER);
  const [composerOpen, setComposerOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [aiStage, setAiStage] = useState<string | null>(null);
  const [notice, setNotice] = useState("准备就绪：点击「创建 Feature」输入你的需求，然后跑完整工作流。");
  const [error, setError] = useState<string | null>(null);
  const [requireApproval, setRequireApproval] = useState(false);
  const [pendingSpec, setPendingSpec] = useState<OntologyInstance | null>(null);

  async function load(nextClass = selectedClass, rootId = selected?.id) {
    const [classRows, instanceRows, graphRows] = await Promise.all([
      api.classes(),
      api.instances(nextClass, query),
      api.graph(rootId),
    ]);
    setClasses(classRows);
    setInstances(instanceRows);
    setGraph(graphRows);
    if (!selected && instanceRows[0]) setSelected(instanceRows[0]);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, []);

  async function refresh() {
    setBusy(true);
    try {
      await load();
      setNotice("数据已刷新。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "刷新失败。");
    } finally {
      setBusy(false);
    }
  }

  async function createFeature() {
    if (!composer.title.trim()) {
      setError("请填写 Feature 标题。");
      return;
    }
    const featureClass = classes.find((item) => item.name === "Feature");
    if (!featureClass) {
      setError("本体中尚未注册 Feature 类。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const tags = composer.tags
        .split(/[,，]/)
        .map((tag) => tag.trim())
        .filter(Boolean);
      const created = await api.createInstance({
        class_id: featureClass.id,
        title: composer.title.trim(),
        status: "idea",
        properties: {
          description: composer.description.trim(),
          priority: composer.priority,
          tags,
          source: "web-ui",
          created_via: "composer",
        },
      });
      setSelectedClass("Feature");
      setSelected(created);
      setComposer(EMPTY_COMPOSER);
      setComposerOpen(false);
      await load("Feature", created.id);
      setNotice(`Feature 已创建：「${created.title}」。可以点击「跑完整工作流」让 AI 扩展 Spec/Plan/Task。`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败。");
    } finally {
      setBusy(false);
    }
  }

  async function runFullWorkflow() {
    if (!selected || selected.class_name !== "Feature") {
      setError("请先选择一个 Feature。");
      return;
    }
    setBusy(true);
    setError(null);
    setPendingSpec(null);
    try {
      setAiStage(requireApproval ? "正在生成 Spec 并提交飞书审批..." : "正在生成 Spec（LLM 推理中）...");
      const specResult = await api.specFromFeature(selected.id, requireApproval);
      const spec = specResult.spec;

      // 门禁开启时：Spec 停在 pending_review，停在门禁处等待审批
      if (spec.status === "pending_review") {
        setPendingSpec(spec);
        setSelected(spec);
        await load("Spec", spec.id);
        setNotice(
          `Spec 已提交飞书审批（instance_code 见详情面板）。审批通过后会自动续跑 Plan/Tasks；被拒后 Spec 会回到 draft。`,
        );
        return;
      }

      setAiStage("正在生成 Plan（LLM 推理中）...");
      const planResult = await api.planFromSpec(spec.id);
      setAiStage("正在拆解 Tasks（LLM 推理中）...");
      await api.tasksFromPlan(planResult.plan.id);
      setAiStage("正在跑完整性检查...");
      await api.runChecklist(selected.id);
      setAiStage("正在模拟 Jenkins 构建...");
      await api.triggerJenkins(selected.id);
      await api.searchLogs();
      await load("Feature", selected.id);
      setNotice("完整工作流已跑通：Spec → Plan → Task → Checklist → Mock Jenkins → Mock Log 全部生成。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "工作流执行失败。");
    } finally {
      setBusy(false);
      setAiStage(null);
    }
  }

  async function checkApprovalStatus() {
    if (!pendingSpec) return;
    setBusy(true);
    setError(null);
    try {
      // 直接 fetch 拉最新 Spec 状态（绕过 search 的 status 过滤）
      const fresh = await fetch(`${import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api"}/instances/${pendingSpec.id}`)
        .then((r) => r.json() as Promise<OntologyInstance>);
      const status = fresh.status;
      if (status === "ready") {
        setPendingSpec(null);
        setNotice("飞书审批通过，Plan + Tasks 已自动生成。正在跑收尾...");
        const featureId = selected?.class_name === "Feature" ? selected.id : pendingSpec.id;
        await api.runChecklist(featureId);
        await api.triggerJenkins(pendingSpec.id);
        await api.searchLogs();
        await load("Feature", featureId);
        setNotice("审批通过：Spec → Plan → Task → Checklist → Mock Jenkins 全部自动跑完。");
      } else if (status === "draft") {
        setPendingSpec(null);
        setError("飞书审批被拒绝：Spec 已回到 draft，请编辑后重新发起审批。");
        await load("Feature", selected?.id);
      } else {
        setNotice(`Spec 仍在 ${status}，审批人尚未在飞书 App 操作。`);
        setPendingSpec({ ...pendingSpec, status });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "检查审批状态失败。");
    } finally {
      setBusy(false);
    }
  }

  async function runChecklistOnly() {
    if (!selected) return;
    setBusy(true);
    try {
      await api.runChecklist(selected.id);
      await load(selectedClass, selected.id);
      setNotice("Checklist 已执行。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Checklist 执行失败。");
    } finally {
      setBusy(false);
    }
  }

  async function selectClass(className: string) {
    setSelectedClass(className);
    setSelected(null);
    try {
      const rows = await api.instances(className, query);
      setInstances(rows);
      if (rows[0]) {
        setSelected(rows[0]);
        setGraph(await api.graph(rows[0].id));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败。");
    }
  }

  const classCounts = useMemo(() => {
    const counts = new Map<string, number>();
    graph.nodes.forEach((node) => counts.set(node.class_name, (counts.get(node.class_name) ?? 0) + 1));
    return counts;
  }, [graph.nodes]);

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <Boxes size={26} />
          <div>
            <strong>Ontology AI</strong>
            <span>Coding Workbench</span>
          </div>
        </div>
        <nav className="classNav">
          {classes
            .filter((item) => CORE_CLASSES.includes(item.name))
            .map((item) => (
              <button
                key={item.id}
                className={item.name === selectedClass ? "active" : ""}
                onClick={() => selectClass(item.name)}
                title={item.description}
              >
                <GitCommitHorizontal size={16} />
                <span>{item.name}</span>
                <b>{classCounts.get(item.name) ?? 0}</b>
              </button>
            ))}
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p>本体驱动软件工程 MVP</p>
            <h1>从需求到发布的语义拓扑工作台</h1>
          </div>
          <button className="iconButton" onClick={refresh} disabled={busy} title="刷新">
            <RefreshCw size={18} />
          </button>
        </header>

        <section className="composer">
          {composerOpen ? (
            <div className="composerPanel">
              <div className="composerHeader">
                <Sparkles size={18} />
                <strong>新建 Feature</strong>
                <button className="linkBtn" onClick={() => setComposerOpen(false)}>
                  收起
                </button>
              </div>
              <label className="field">
                <span>标题</span>
                <input
                  value={composer.title}
                  onChange={(e) => setComposer({ ...composer, title: e.target.value })}
                  placeholder="例：用户登录"
                />
              </label>
              <label className="field">
                <span>需求描述（喂给 LLM 的关键输入）</span>
                <textarea
                  value={composer.description}
                  onChange={(e) => setComposer({ ...composer, description: e.target.value })}
                  placeholder="详细描述这个需求：&#10;- 业务背景&#10;- 涉及场景&#10;- 已知约束 / 边界&#10;- 验收要点"
                  rows={5}
                />
              </label>
              <div className="fieldRow">
                <label className="field">
                  <span>优先级</span>
                  <select
                    value={composer.priority}
                    onChange={(e) => setComposer({ ...composer, priority: e.target.value })}
                  >
                    {PRIORITY_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field grow">
                  <span>标签（逗号分隔）</span>
                  <input
                    value={composer.tags}
                    onChange={(e) => setComposer({ ...composer, tags: e.target.value })}
                    placeholder="auth, 安全, v2.0"
                  />
                </label>
              </div>
              <div className="composerActions">
                <button onClick={() => setComposer(EMPTY_COMPOSER)} disabled={busy}>
                  清空
                </button>
                <button className="primary" onClick={createFeature} disabled={busy || !composer.title.trim()}>
                  {busy ? <Loader2 className="spin" size={16} /> : <Plus size={16} />}
                  创建 Feature
                </button>
              </div>
            </div>
          ) : (
            <div className="inputWrap featureInput">
              <Plus size={17} />
              <input
                value={composer.title}
                onChange={(e) => setComposer({ ...composer, title: e.target.value })}
                placeholder="输入需求标题，例如：用户登录 / 性能优化 / 数据库迁移"
                onFocus={() => setComposerOpen(true)}
              />
            </div>
          )}
          {!composerOpen && (
            <button onClick={() => setComposerOpen(true)} disabled={busy}>
              <Plus size={17} />
              创建 Feature
            </button>
          )}
          <div className="inputWrap">
            <Search size={17} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索实例标题"
            />
          </div>
          <button onClick={refresh} disabled={busy}>
            <Search size={17} />
            搜索
          </button>
        </section>

        {aiStage && (
          <div className="aiBanner">
            <Loader2 className="spin" size={18} />
            <span>{aiStage}</span>
          </div>
        )}
        {error && (
          <div className="errorBanner">
            <strong>出错了：</strong>
            <span>{error}</span>
            <button onClick={() => setError(null)}>知道了</button>
          </div>
        )}

        <section className="contentGrid">
          <div className="mainColumn">
            <div className="metrics">
              <Metric label="Nodes" value={graph.nodes.length} />
              <Metric label="Edges" value={graph.edges.length} />
              <Metric label="Tasks" value={classCounts.get("Task") ?? 0} />
              <Metric
                label="Logs"
                value={(classCounts.get("ExecutionLog") ?? 0) + (classCounts.get("ServiceLog") ?? 0)}
              />
            </div>

            <section className="graphPanel">
              <div className="sectionTitle">
                <GitBranch size={18} />
                <h2>语义拓扑图</h2>
              </div>
              <Topology
                graph={graph}
                selected={selected}
                onSelect={(instance) => {
                  setSelected(instance);
                  api.graph(instance.id).then(setGraph).catch((err) => setError(err.message));
                }}
              />
            </section>

            <section className="listPanel">
              <div className="sectionTitle">
                <Activity size={18} />
                <h2>{selectedClass} 实例</h2>
              </div>
              <div className="instanceList">
                {instances.length === 0 ? (
                  <p className="empty">暂无实例。可以先创建 Feature，或切换左侧本体类型。</p>
                ) : (
                  instances.map((item) => (
                    <button
                      key={item.id}
                      className={selected?.id === item.id ? "row selected" : "row"}
                      onClick={() => {
                        setSelected(item);
                        api.graph(item.id).then(setGraph).catch((err) => setError(err.message));
                      }}
                    >
                      <span>{item.title}</span>
                      <b className={item.status === "pending_review" ? "badge pending" : ""}>
                        {item.status}
                      </b>
                    </button>
                  ))
                )}
              </div>
            </section>
          </div>

          <aside className="detailPanel">
            <div className="sectionTitle">
              <CheckCircle2 size={18} />
              <h2>实例详情</h2>
            </div>
            {selected ? (
              <>
                <p className="classPill">{selected.class_name}</p>
                <h3>{selected.title}</h3>
                <p className="statusLine">状态：{selected.status}</p>
                <DetailProperties properties={selected.properties} />
                <div className="actions">
                  <button onClick={runFullWorkflow} disabled={busy || selected.class_name !== "Feature"}>
                    {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
                    跑完整工作流（LLM）
                  </button>
                  <button onClick={runChecklistOnly} disabled={busy}>
                    <CheckCircle2 size={16} />
                    Checklist
                  </button>
                  <button onClick={() => api.triggerJenkins(selected.id).then(() => refresh())} disabled={busy}>
                    <ServerCog size={16} />
                    Mock Jenkins
                  </button>
                </div>
                {selected.class_name === "Feature" && (
                  <label className="approvalToggle">
                    <input
                      type="checkbox"
                      checked={requireApproval}
                      onChange={(e) => setRequireApproval(e.target.checked)}
                    />
                    <span>需飞书审批后再继续</span>
                    <small>勾选后，Spec 会停在 pending_review，等审批人同意再自动续跑 Plan/Tasks</small>
                  </label>
                )}
                {pendingSpec && selected.id === pendingSpec.id && (
                  <div className="pendingBanner">
                    <strong>⏳ 等待飞书审批</strong>
                    <p>审批人通过后，后端会自动续跑 Plan + Tasks；被拒绝后 Spec 会回到 draft。</p>
                    <button onClick={checkApprovalStatus} disabled={busy}>
                      {busy ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                      检查审批状态
                    </button>
                  </div>
                )}
              </>
            ) : (
              <p className="empty">从列表或拓扑图中选择一个实例。</p>
            )}
            <p className="notice">{notice}</p>
          </aside>
        </section>
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DetailProperties({ properties }: { properties: Record<string, unknown> }) {
  const entries = Object.entries(properties ?? {});
  if (entries.length === 0) {
    return <pre className="propsEmpty">（无附加属性）</pre>;
  }
  return (
    <div className="props">
      {entries.map(([key, value]) => (
        <div key={key} className="propRow">
          <span className="propKey">{key}</span>
          <span className="propValue">
            {Array.isArray(value) ? value.join("、") : typeof value === "object" && value !== null ? JSON.stringify(value) : String(value)}
          </span>
        </div>
      ))}
    </div>
  );
}