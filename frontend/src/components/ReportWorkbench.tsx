import {
  Activity,
  ArrowLeft,
  Boxes,
  Check,
  Circle,
  Download,
  FileOutput,
  FileSpreadsheet,
  Loader2,
  Play,
  RefreshCw,
  Sparkles,
  UploadCloud,
  XCircle,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { ExecutionTask, ReportRun } from "../types";

const SAMPLE_REQUIREMENT =
  "整理上传的数据，识别并统一字段，处理空记录和重复记录；自动发现可汇总的数值指标及分类维度，生成清洗后数据、Excel 分析报表和可追溯的验证结果。";

export function ReportWorkbench({ onBack }: { onBack: () => void }) {
  const [title, setTitle] = useState("数据整理与经营报表");
  const [requirement, setRequirement] = useState(SAMPLE_REQUIREMENT);
  const [files, setFiles] = useState<File[]>([]);
  const [fileInputVersion, setFileInputVersion] = useState(0);
  const [runs, setRuns] = useState<ReportRun[]>([]);
  const [activeRun, setActiveRun] = useState<ReportRun | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadRuns(preferredId?: string) {
    const rows = await api.reportRuns();
    setRuns(rows);
    const selected = rows.find((run) => run.id === preferredId) ?? activeRun ?? rows[0] ?? null;
    if (selected) setActiveRun(selected);
  }

  useEffect(() => {
    loadRuns().catch((reason) => setError(reason instanceof Error ? reason.message : "加载执行记录失败。"));
  }, []);

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
    }, 900);
    return () => window.clearInterval(timer);
  }, [activeRun?.id, activeRun?.status]);

  async function submit() {
    if (requirement.trim().length < 8) {
      setError("请描述数据整理目标、指标或期望交付物。");
      return;
    }
    if (files.length === 0) {
      setError("请至少选择一个 CSV 或 XLSX 文件。");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const created = await api.createReportRun(requirement.trim(), title.trim(), files);
      setActiveRun(created);
      setRuns((current) => [created, ...current.filter((run) => run.id !== created.id)]);
      setFiles([]);
      setFileInputVersion((current) => current + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "启动执行失败。");
    } finally {
      setSubmitting(false);
    }
  }

  const progress = useMemo(() => {
    if (!activeRun) return 0;
    const completed = activeRun.tasks.filter((task) => task.status === "succeeded").length;
    return activeRun.tasks.length ? Math.round((completed / activeRun.tasks.length) * 100) : 0;
  }, [activeRun]);

  return (
    <main className="reportShell">
      <aside className="reportSidebar">
        <div className="brand">
          <Boxes size={26} />
          <div>
            <strong>Ontology AI</strong>
            <span>Goal-to-Artifact Runtime</span>
          </div>
        </div>
        <button className="backButton" onClick={onBack}>
          <ArrowLeft size={16} />
          返回本体工作台
        </button>
        <div className="runListHeader">
          <span>最近执行</span>
          <button onClick={() => loadRuns(activeRun?.id)} title="刷新记录">
            <RefreshCw size={14} />
          </button>
        </div>
        <div className="runList">
          {runs.length === 0 ? (
            <p className="empty">还没有执行记录。</p>
          ) : (
            runs.map((run) => (
              <button
                key={run.id}
                className={activeRun?.id === run.id ? "runItem active" : "runItem"}
                onClick={() => setActiveRun(run)}
              >
                <span>{run.title}</span>
                <small>{statusText(run.status)}</small>
              </button>
            ))
          )}
        </div>
      </aside>

      <section className="reportWorkspace">
        <header className="reportHeader">
          <div>
            <p>通用需求执行 · 首个数据能力闭环</p>
            <h1>整理数据并生成可验证报表</h1>
          </div>
          <div className="runtimePill">
            <Zap size={15} />
            Task · Skill · MCP · Artifact
          </div>
        </header>

        <section className="requestComposer">
          <div className="requestHeading">
            <Sparkles size={18} />
            <div>
              <strong>输入目标</strong>
              <span>系统会生成结果合同、Task DAG 和临时 Skill，再执行并验证产物。</span>
            </div>
          </div>
          <label className="field">
            <span>执行名称</span>
            <input value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <label className="field">
            <span>数据整理与报表需求</span>
            <textarea rows={4} value={requirement} onChange={(event) => setRequirement(event.target.value)} />
          </label>
          <div className="uploadRow">
            <label className="uploadBox">
              <UploadCloud size={22} />
              <span>{files.length ? `已选择 ${files.length} 个文件` : "选择 CSV / XLSX 文件"}</span>
              <small>单文件最大 25 MB，可一次上传多个来源</small>
              <input
                key={fileInputVersion}
                type="file"
                accept=".csv,.xlsx"
                multiple
                onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
              />
            </label>
            <div className="fileSelection">
              {files.map((file) => (
                <span key={`${file.name}-${file.size}`}>
                  <FileSpreadsheet size={14} />
                  {file.name}
                  <small>{formatBytes(file.size)}</small>
                </span>
              ))}
            </div>
            <button className="runButton" onClick={submit} disabled={submitting || files.length === 0}>
              {submitting ? <Loader2 className="spin" size={17} /> : <Play size={17} />}
              启动执行
            </button>
          </div>
        </section>

        {error && (
          <div className="errorBanner reportError">
            <strong>执行提示：</strong>
            <span>{error}</span>
            <button onClick={() => setError(null)}>关闭</button>
          </div>
        )}

        {!activeRun ? (
          <section className="reportEmpty">
            <Activity size={28} />
            <h2>等待第一个数据需求</h2>
            <p>上传数据并启动后，这里会展示需求合同、每个 Task 的执行证据和最终产物。</p>
          </section>
        ) : (
          <>
            <section className="runOverview">
              <div>
                <div className="runTitleLine">
                  <StatusIcon status={activeRun.status} />
                  <h2>{activeRun.title}</h2>
                  <span className={`statusBadge ${activeRun.status}`}>{statusText(activeRun.status)}</span>
                </div>
                <p>{activeRun.requirement}</p>
              </div>
              <strong>{progress}%</strong>
              <div className="progressTrack" aria-label={`执行进度 ${progress}%`}>
                <span style={{ width: `${progress}%` }} />
              </div>
              {activeRun.error && <p className="runError">{activeRun.error}</p>}
            </section>

            <section className="reportMetrics">
              <ReportMetric label="输入记录" value={activeRun.summary.input_rows} />
              <ReportMetric label="清洗后记录" value={activeRun.summary.output_rows} />
              <ReportMetric label="移除重复" value={activeRun.summary.duplicates_removed} />
              <ReportMetric label="最终产物" value={activeRun.summary.artifact_count ?? activeRun.artifacts.length} />
            </section>

            <section className="executionGrid">
              <div className="executionColumn">
                <section className="reportPanel">
                  <div className="sectionTitle">
                    <Sparkles size={18} />
                    <h2>结果合同</h2>
                  </div>
                  <Contract run={activeRun} />
                </section>

                <section className="reportPanel">
                  <div className="sectionTitle">
                    <Activity size={18} />
                    <h2>执行过程</h2>
                  </div>
                  <div className="taskTimeline">
                    {activeRun.tasks.map((task) => (
                      <TaskRow task={task} key={task.id} />
                    ))}
                  </div>
                </section>
              </div>

              <aside className="resultColumn">
                <section className="reportPanel resultPanel">
                  <div className="sectionTitle">
                    <FileOutput size={18} />
                    <h2>最终结果</h2>
                  </div>
                  {activeRun.status !== "succeeded" ? (
                    <p className="empty">执行完成并通过验证后，产物会显示在这里。</p>
                  ) : (
                    <>
                      <div className="verificationSummary">
                        <Check size={18} />
                        <div>
                          <strong>交付验证通过</strong>
                          <span>{activeRun.tasks.length} 个 Task 已完成</span>
                        </div>
                      </div>
                      <div className="artifactList">
                        {activeRun.artifacts.map((artifact) => (
                          <a
                            key={artifact.id}
                            href={api.artifactUrl(artifact.download_url)}
                            className="artifactItem"
                          >
                            <FileSpreadsheet size={19} />
                            <span>
                              <strong>{artifact.name}</strong>
                              <small>{artifact.kind} · {formatBytes(artifact.size)}</small>
                            </span>
                            <Download size={16} />
                          </a>
                        ))}
                      </div>
                    </>
                  )}
                </section>
              </aside>
            </section>
          </>
        )}
      </section>
    </main>
  );
}

function Contract({ run }: { run: ReportRun }) {
  const contract = run.result_contract;
  return (
    <div className="contractGrid">
      <ContractGroup label="输入" values={contract.inputs} />
      <ContractGroup label="处理步骤" values={contract.operations} />
      <ContractGroup label="维度" values={contract.dimensions} />
      <ContractGroup label="指标" values={contract.metrics} />
      <ContractGroup label="交付物" values={contract.deliverables} />
      <ContractGroup label="验收条件" values={contract.acceptance_criteria} />
    </div>
  );
}

function ContractGroup({ label, values = [] }: { label: string; values?: string[] }) {
  return (
    <div className="contractGroup">
      <strong>{label}</strong>
      <div>{values.map((value) => <span key={value}>{value}</span>)}</div>
    </div>
  );
}

function TaskRow({ task }: { task: ExecutionTask }) {
  return (
    <article className={`taskRow ${task.status}`}>
      <div className="taskMarker"><TaskStatusIcon status={task.status} /></div>
      <div className="taskBody">
        <div className="taskTitle">
          <strong>{task.order_index}. {task.title}</strong>
          <span>{statusText(task.status)}</span>
        </div>
        <p>{task.description}</p>
        <div className="skillLine">
          <b>Skill</b>
          <code>{task.skill_spec.name}</code>
          {(task.skill_spec.mcp_bindings ?? []).map((binding) => <span key={binding}>{binding}</span>)}
        </div>
        {task.outputs.length > 0 && <p className="taskOutputs">产物：{task.outputs.join("、")}</p>}
        {task.error && <p className="taskFailure">{task.error}</p>}
      </div>
    </article>
  );
}

function ReportMetric({ label, value }: { label: string; value?: number }) {
  return <div><span>{label}</span><strong>{value ?? "—"}</strong></div>;
}

function StatusIcon({ status }: { status: ReportRun["status"] }) {
  if (status === "succeeded") return <Check size={20} />;
  if (status === "failed") return <XCircle size={20} />;
  return <Loader2 className="spin" size={20} />;
}

function TaskStatusIcon({ status }: { status: ExecutionTask["status"] }) {
  if (status === "succeeded") return <Check size={15} />;
  if (status === "failed") return <XCircle size={15} />;
  if (status === "running") return <Loader2 className="spin" size={15} />;
  return <Circle size={13} />;
}

function statusText(status: string) {
  return ({ planning: "规划中", pending: "等待", running: "执行中", succeeded: "已完成", failed: "失败" } as Record<string, string>)[status] ?? status;
}

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}
