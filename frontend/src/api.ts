import type { Graph, OntologyClass, OntologyInstance, ReportRun } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData;
  const response = await fetch(`${API_BASE}${path}`, {
    headers: isFormData
      ? init?.headers
      : {
          "Content-Type": "application/json",
          ...(init?.headers ?? {}),
        },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  classes: () => request<OntologyClass[]>("/classes"),
  instances: (className?: string, q?: string) => {
    const params = new URLSearchParams();
    if (className) params.set("class", className);
    if (q) params.set("q", q);
    return request<OntologyInstance[]>(`/instances?${params.toString()}`);
  },
  graph: (rootId?: string) => request<Graph>(`/graph${rootId ? `?root_id=${rootId}` : ""}`),
  createInstance: (payload: {
    class_id: string;
    title: string;
    status?: string;
    properties?: Record<string, unknown>;
  }) =>
    request<OntologyInstance>("/instances", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  specFromFeature: (featureId: string, requireFeishuApproval = false) => {
    const qs = requireFeishuApproval ? "?require_feishu_approval=true" : "";
    return request<{ spec: OntologyInstance }>(`/workflows/spec-from-feature${qs}`, {
      method: "POST",
      body: JSON.stringify({ feature_id: featureId }),
    });
  },
  planFromSpec: (specId: string) =>
    request<{ plan: OntologyInstance }>("/workflows/plan-from-spec", {
      method: "POST",
      body: JSON.stringify({ spec_id: specId }),
    }),
  tasksFromPlan: (planId: string) =>
    request<{ tasks: OntologyInstance[] }>("/workflows/tasks-from-plan", {
      method: "POST",
      body: JSON.stringify({ plan_id: planId }),
    }),
  runChecklist: (rootId: string) =>
    request<{ checklist: OntologyInstance; reflection: OntologyInstance }>("/workflows/run-checklist", {
      method: "POST",
      body: JSON.stringify({ root_id: rootId }),
    }),
  triggerJenkins: (featureId: string, environment = "staging") =>
    request<{ job: OntologyInstance; service_log: OntologyInstance }>("/integrations/jenkins/trigger", {
      method: "POST",
      body: JSON.stringify({ feature_id: featureId, environment }),
    }),
  searchLogs: () =>
    request<{ logs: OntologyInstance[] }>("/integrations/logs/search", {
      method: "POST",
      body: JSON.stringify({ service: "ontology-core-service" }),
    }),
  reportRuns: () => request<ReportRun[]>("/report-runs"),
  reportRun: (runId: string) => request<ReportRun>(`/report-runs/${runId}`),
  createReportRun: (requirement: string, title: string, files: File[]) => {
    const body = new FormData();
    body.append("requirement", requirement);
    body.append("title", title);
    files.forEach((file) => body.append("files", file));
    return request<ReportRun>("/report-runs", { method: "POST", body });
  },
  artifactUrl: (downloadUrl: string) => `${API_BASE}${downloadUrl}`,
};
