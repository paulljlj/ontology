import type { SatelliteCase, SatelliteMcpStatus, SatelliteRun, SatelliteRunInput } from "./satellite-types";

const API_BASE = (import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api").replace(/\/$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
      signal: controller.signal,
    });
    const body = await response.text();
    let data: unknown;
    try { data = body ? JSON.parse(body) : null; } catch { data = body; }
    if (!response.ok) {
      const detail = data && typeof data === "object" && "detail" in data ? data.detail : data;
      throw new Error(`请求失败（${response.status}）：${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
    }
    if (!data || typeof data !== "object") throw new Error("服务返回了无法识别的数据，请检查后端接口。");
    return data as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw new Error("请求超时，尚未获得结果，请检查后端服务后刷新。");
    if (error instanceof TypeError) throw new Error("无法连接卫星分析服务。请确认后端已启动，并检查 API 地址和跨域配置。");
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

export const satelliteApi = {
  cases: () => request<SatelliteCase[]>("/satellite/cases"),
  runs: () => request<SatelliteRun[]>("/satellite/runs"),
  run: (id: string) => request<SatelliteRun>(`/satellite/runs/${encodeURIComponent(id)}`),
  createRun: (input: SatelliteRunInput) => request<SatelliteRun>("/satellite/runs", { method: "POST", body: JSON.stringify(input) }),
  mcpStatus: () => request<SatelliteMcpStatus>("/satellite/mcp/status"),
  artifactUrl: (path: string) => `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`,
};
