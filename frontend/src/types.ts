export type OntologyClass = {
  id: string;
  name: string;
  description: string;
  schema: Record<string, unknown>;
  created_at: string;
};

export type OntologyInstance = {
  id: string;
  class_id: string;
  class_name: string;
  title: string;
  status: string;
  properties: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type OntologyRelation = {
  id: string;
  source_id: string;
  target_id: string;
  type: string;
  properties: Record<string, unknown>;
  inferred?: boolean;
  reason?: string;
  created_at: string;
};

export type Graph = {
  nodes: OntologyInstance[];
  edges: OntologyRelation[];
};

export type ExecutionTask = {
  id: string;
  task_key: string;
  order_index: number;
  title: string;
  description: string;
  status: "pending" | "running" | "succeeded" | "failed";
  skill_spec: {
    name?: string;
    required_capabilities?: string[];
    mcp_bindings?: string[];
    permission_policy?: string;
    ontology_rule?: string;
    depends_on?: string[];
  };
  inputs: unknown[];
  outputs: unknown[];
  evidence: Record<string, unknown>;
  error: string;
  started_at?: string | null;
  completed_at?: string | null;
};

export type ReportArtifact = {
  id: string;
  task_id?: string | null;
  name: string;
  kind: string;
  mime_type: string;
  size: number;
  metadata: Record<string, unknown>;
  created_at: string;
  download_url: string;
};

export type ReportRun = {
  id: string;
  workflow_type: string;
  title: string;
  requirement: string;
  status: "planning" | "running" | "succeeded" | "failed";
  result_contract: {
    goal?: string;
    inputs?: string[];
    operations?: string[];
    dimensions?: string[];
    metrics?: string[];
    deliverables?: string[];
    acceptance_criteria?: string[];
  };
  input_files: Array<{ name: string; size: number }>;
  summary: Record<string, number | string>;
  error: string;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  updated_at: string;
  tasks: ExecutionTask[];
  artifacts: ReportArtifact[];
};
