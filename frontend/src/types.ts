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
