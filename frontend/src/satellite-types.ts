import type { ReportRun } from "./types";

export type SatelliteCase = {
  case_id: string;
  dataset_kind: string;
  sample_start: string;
  sample_end_exclusive: string;
  analysis_start: string;
  analysis_end_exclusive: string;
  initial_diagnosis_cutoff: string;
  sampling_seconds?: number | string;
  satellites: number | string[];
  ground_stations: number | string[];
  links: number | string[];
  services: number | string[];
};

export type SatelliteSection = {
  status?: string;
  items?: Record<string, unknown>[];
  note?: string;
};

export type SatelliteReport = {
  dataset_kind: string;
  case_id: string;
  at: string;
  as_of: string;
  diagnosis_status: "pending" | "provided";
  overview: {
    summary?: string;
    metrics?: Array<{ label: string; value: unknown; unit?: string }>;
    observations?: Record<string, unknown>[];
  };
  causes: SatelliteSection;
  watch_items: SatelliteSection;
  route_options: {
    status?: string;
    proposals?: Record<string, unknown>[];
    limitations?: string[];
    unresolved_risks?: unknown[];
  };
  impact: SatelliteSection;
  conclusions: { items?: string[]; missing_evidence?: string[] };
  provenance: {
    input_source: "manual" | "diagnosis_json";
    diagnosis_is_fixture: boolean;
  };
  topology?: {
    nodes: Array<{ id: string; type: string; label?: string }>;
    edges: Array<{ id: string; source: string; target: string }>;
  };
};

export type SatelliteRun = Omit<ReportRun, "summary" | "result_contract"> & {
  result_contract: ReportRun["result_contract"] & {
    case_id?: string;
    avoid_objects?: string[];
    at?: string;
    as_of?: string;
  };
  summary: Record<string, unknown> & { satellite_report?: SatelliteReport };
};

export type SatelliteRunInput = {
  case_id: string;
  avoid_objects: string[];
  at?: string;
  as_of?: string;
  requirement?: string;
  diagnosis?: Record<string, unknown>;
};

export type SatelliteMcpStatus = {
  servers: Array<{ name: string; enabled: boolean; transport: string; tools?: string[]; status?: string }>;
  default_mode: "file" | "mcp";
  note?: string;
};
