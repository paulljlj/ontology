import { useEffect, useRef, useState } from "react";
import cytoscape, { Core, ElementDefinition, EventObject } from "cytoscape";
import { Maximize2, Minus, Plus } from "lucide-react";
import type { Graph, OntologyInstance } from "../types";

type TopologyProps = {
  graph: Graph;
  selected: OntologyInstance | null;
  onSelect: (instance: OntologyInstance) => void;
};

const CLASS_COLORS: Record<string, string> = {
  Project: "#5b8def",
  Feature: "#f5a524",
  Spec: "#9254de",
  UserStory: "#73d13d",
  Acceptance: "#36cfc9",
  Clarification: "#bfbfbf",
  Plan: "#1677ff",
  DataModel: "#13c2c2",
  Contract: "#fa541c",
  ADR: "#722ed1",
  Task: "#52c41a",
  Bug: "#ff4d4f",
  Checklist: "#faad14",
  Reflection: "#2f54eb",
  ExecutionLog: "#bfbfbf",
  ServiceLog: "#bfbfbf",
  JenkinsJob: "#13a8a8",
  FeishuMessage: "#eb2f96",
  Goal: "#dce7ff",
  ReportSpecification: "#eadcff",
  AnalysisIntent: "#dbe9f5",
  MetricDefinition: "#dceee5",
  Dimension: "#f3e7cf",
  TimeScope: "#e6e3f5",
  ExecutableTask: "#d9f3ec",
  SkillDefinition: "#fff0c9",
  Artifact: "#dff4e4",
  Verification: "#ffe0e7",
  DeliveryBundle: "#e3e1ff",
};

function classColor(name: string): string {
  return CLASS_COLORS[name] ?? "#8c8c8c";
}

function buildElements(graph: Graph, selectedId: string | undefined): ElementDefinition[] {
  const nodes: ElementDefinition[] = graph.nodes.map((node) => ({
    data: {
      id: node.id,
      label: `${node.class_name}\n${node.title.length > 26 ? `${node.title.slice(0, 26)}…` : node.title}`,
      className: node.class_name,
      color: classColor(node.class_name),
      status: node.status,
      instance: node,
    },
    classes: selectedId === node.id ? "selected" : "",
  }));
  const edges: ElementDefinition[] = graph.edges
    .filter((edge) => edge.source_id && edge.target_id && edge.source_id !== edge.target_id)
    .map((edge) => ({
      data: {
        id: edge.id ?? `${edge.source_id}-${edge.type}-${edge.target_id}`,
        source: edge.source_id,
        target: edge.target_id,
        label: edge.type,
        inferred: Boolean(edge.inferred ?? (edge.properties as { inferred?: boolean } | null)?.inferred),
      },
    }));
  return [...nodes, ...edges];
}

export default function Topology({ graph, selected, onSelect }: TopologyProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<Core | null>(null);
  const [zoom, setZoom] = useState(1);
  const [filter, setFilter] = useState<string>("all");

  useEffect(() => {
    if (!containerRef.current) return;
    if (cyRef.current) {
      cyRef.current.destroy();
      cyRef.current = null;
    }
    cyRef.current = cytoscape({
      container: containerRef.current,
      elements: buildElements(graph, selected?.id),
      layout: {
        name: "breadthfirst",
        directed: true,
        spacingFactor: 1.35,
        animate: false,
        fit: true,
        padding: 42,
      },
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)",
            "border-color": "#65736b",
            "border-width": 1.4,
            label: "data(label)",
            color: "#1f1f1f",
            "font-size": 11.5,
            "font-weight": 600,
            "text-wrap": "wrap",
            "text-max-width": "184px",
            "text-valign": "center",
            "text-halign": "center",
            width: 196,
            height: 68,
            shape: "round-rectangle",
          },
        },
        {
          selector: "node.selected",
          style: {
            "border-width": 3,
            "border-color": "#1677ff",
          },
        },
        {
          selector: "edge",
          style: {
            width: 1.9,
            "line-color": "#8c8c8c",
            "target-arrow-color": "#8c8c8c",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            label: "data(label)",
            "font-size": 10,
            color: "#595959",
            "text-background-color": "#ffffff",
            "text-background-opacity": 0.85,
            "text-background-padding": "3px",
          },
        },
        {
          selector: "edge[inferred = 'true']",
          style: {
            "line-style": "dashed",
            "line-color": "#fa541c",
            "target-arrow-color": "#fa541c",
            "text-background-color": "#fff7e6",
          },
        },
      ],
    });
    cyRef.current.on("tap", "node", (event: EventObject) => {
      const instance = event.target.data("instance") as OntologyInstance | undefined;
      if (instance) onSelect(instance);
    });
    cyRef.current.on("zoom", () => {
      setZoom(cyRef.current?.zoom() ?? 1);
    });
    return () => {
      cyRef.current?.destroy();
      cyRef.current = null;
    };
  }, [graph, onSelect]);

  useEffect(() => {
    if (!cyRef.current) return;
    cyRef.current.elements().removeClass("selected");
    if (selected) {
      const node = cyRef.current.getElementById(selected.id);
      if (node && node.length) {
        node.addClass("selected");
      }
    }
  }, [selected]);

  useEffect(() => {
    if (!cyRef.current) return;
    cyRef.current.batch(() => {
      cyRef.current!.nodes().style("display", "element");
      cyRef.current!.edges().style("display", "element");
      if (filter !== "all") {
        cyRef.current!.nodes().filter(`[className != "${filter}"]`).style("display", "none");
        cyRef.current!.edges().forEach((edge: cytoscape.EdgeSingular) => {
          const sourceVisible = edge.source().style("display") !== "none";
          const targetVisible = edge.target().style("display") !== "none";
          if (!(sourceVisible && targetVisible)) edge.style("display", "none");
        });
      }
    });
  }, [filter]);

  function zoomBy(factor: number) {
    if (!cyRef.current) return;
    const next = Math.max(0.3, Math.min(3, cyRef.current.zoom() * factor));
    cyRef.current.zoom({ level: next, renderedPosition: { x: containerRef.current!.clientWidth / 2, y: containerRef.current!.clientHeight / 2 } });
  }

  function resetView() {
    if (!cyRef.current) return;
    cyRef.current.fit(undefined, 24);
    setZoom(cyRef.current.zoom());
  }

  const classOptions = Array.from(new Set(graph.nodes.map((node) => node.class_name))).sort();

  return (
    <div className="topologyScroller">
      <div className="topologyFilters">
        <label>
          过滤
          <select value={filter} onChange={(event) => setFilter(event.target.value)}>
            <option value="all">全部</option>
            {classOptions.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div ref={containerRef} className="topology" aria-label="Ontology graph" />
      <div className="zoomControls">
        <button onClick={() => zoomBy(1.25)} title="放大">
          <Plus size={16} />
        </button>
        <span className="zoomLabel">{Math.round(zoom * 100)}%</span>
        <button onClick={() => zoomBy(1 / 1.25)} title="缩小">
          <Minus size={16} />
        </button>
        <button onClick={resetView} title="重置">
          <Maximize2 size={16} />
        </button>
      </div>
    </div>
  );
}
