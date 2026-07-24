import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  useNodesState,
} from "@xyflow/react";
import {
  Database,
  GitCommitHorizontal,
  Lightbulb,
  ScrollText,
} from "lucide-react";
import { memo, useEffect, useMemo } from "react";
import { useLocale } from "../lib/i18n";
import type { InvestigationGraph as GraphData } from "../lib/types";

type GraphNodeData = {
  title: string;
  body: string;
  meta: string;
  kind: "hypothesis" | "evidence";
  status?: string;
};

const GraphNode = memo(function GraphNode({
  data,
}: NodeProps<Node<GraphNodeData>>) {
  const Icon =
    data.kind === "hypothesis"
      ? Lightbulb
      : data.meta.includes("database")
        ? Database
        : data.meta.includes("git")
          ? GitCommitHorizontal
          : ScrollText;
  return (
    <div
      className={`graph-node graph-node--${data.kind}`}
      data-status={data.status}
    >
      <Handle type="target" position={Position.Left} />
      <div className="graph-node__eyebrow">
        <Icon size={12} />
        <span>{data.meta}</span>
      </div>
      <strong>{data.title}</strong>
      <p>{data.body}</p>
      <Handle type="source" position={Position.Right} />
    </div>
  );
});

const nodeTypes = { investigation: GraphNode };

export default function InvestigationGraphView({
  graph,
}: {
  graph: GraphData;
}) {
  const { isChinese, text } = useLocale();
  const layout = useMemo(() => {
    const evidenceNodes: Node<GraphNodeData>[] = graph.evidence.map(
      (item, index) => ({
        id: `evidence:${item.key}`,
        type: "investigation",
        position: {
          x: 40 + (index % 2) * 320,
          y: 40 + Math.floor(index / 2) * 160,
        },
        data: {
          title: item.key,
          body: item.summary,
          meta: `${item.source_type} · ${text("可信度", "trust")} ${Math.round(item.trust * 100)}%`,
          kind: "evidence",
        },
      }),
    );
    const hypothesisNodes: Node<GraphNodeData>[] = graph.hypotheses.map(
      (item, index) => ({
        id: `hypothesis:${item.key}`,
        type: "investigation",
        position: {
          x: 760 + (index % 2) * 340,
          y: 40 + Math.floor(index / 2) * 180,
        },
        data: {
          title: `${item.key} · ${Math.round(item.confidence * 100)}%`,
          body: item.statement,
          meta: hypothesisStatus(item.status, isChinese),
          status: item.status,
          kind: "hypothesis",
        },
      }),
    );
    const graphEdges: Edge[] = graph.edges.map((item) => ({
      id: item.id,
      source: `${item.source_type}:${item.source_key}`,
      target: `${item.target_type}:${item.target_key}`,
      label: evidenceRelation(item.relation, isChinese),
      animated:
        graph.edges.length <= 80 &&
        (item.relation === "supports" || item.relation === "corroborates"),
      style: {
        stroke: item.relation === "contradicts" ? "#ff5d5d" : "#adff2f",
        strokeWidth: 1.5,
      },
      labelStyle: { fill: "#a8b0a1", fontSize: 10 },
      labelBgStyle: { fill: "#10130f", fillOpacity: 0.9 },
    }));
    return { nodes: [...evidenceNodes, ...hypothesisNodes], edges: graphEdges };
  }, [graph, isChinese, text]);
  const [nodes, setNodes, onNodesChange] = useNodesState(layout.nodes);

  useEffect(() => {
    setNodes((current) => reconcileNodes(current, layout.nodes));
  }, [layout.nodes, setNodes]);

  if (!nodes.length) {
    return (
      <div className="empty-state empty-state--graph">
        <Lightbulb size={32} />
        <h3>{text("尚无调查图谱", "No investigation graph yet")}</h3>
        <p>
          {text(
            "候选模型还没有记录任何假设或证据节点。",
            "The candidate has not recorded a hypothesis or evidence node.",
          )}
        </p>
      </div>
    );
  }

  return (
    <div className="graph-canvas">
      <ReactFlow
        nodes={nodes}
        edges={layout.edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        fitView
        fitViewOptions={{ padding: 0.18, duration: 260 }}
        minZoom={0.2}
        maxZoom={1.6}
        nodeDragThreshold={2}
        nodesConnectable={false}
        elevateNodesOnSelect={false}
        onlyRenderVisibleElements={nodes.length > 80}
        zoomOnDoubleClick={false}
      >
        <Background color="#293124" gap={24} variant={BackgroundVariant.Dots} />
        <MiniMap
          nodeColor={(node) =>
            (node.data as GraphNodeData).kind === "hypothesis"
              ? "#adff2f"
              : "#4cc9f0"
          }
          maskColor="rgba(5, 7, 5, .72)"
        />
        <Controls />
      </ReactFlow>
    </div>
  );
}

function reconcileNodes(
  current: Node<GraphNodeData>[],
  incoming: Node<GraphNodeData>[],
) {
  const currentById = new Map(current.map((node) => [node.id, node]));
  let changed = current.length !== incoming.length;
  const next = incoming.map((candidate) => {
    const existing = currentById.get(candidate.id);
    if (!existing) {
      changed = true;
      return candidate;
    }
    if (sameNodeData(existing.data, candidate.data)) return existing;
    changed = true;
    return {
      ...candidate,
      position: existing.position,
      selected: existing.selected,
      dragging: existing.dragging,
    };
  });
  return changed ? next : current;
}

function sameNodeData(left: GraphNodeData, right: GraphNodeData) {
  return (
    left.title === right.title &&
    left.body === right.body &&
    left.meta === right.meta &&
    left.kind === right.kind &&
    left.status === right.status
  );
}

function hypothesisStatus(status: string, isChinese: boolean) {
  if (!isChinese) return status;
  const labels: Record<string, string> = {
    proposed: "已提出",
    testing: "验证中",
    supported: "有支持",
    rejected: "已否决",
    confirmed: "已确认",
  };
  return labels[status] ?? status;
}

function evidenceRelation(relation: string, isChinese: boolean) {
  if (!isChinese) return relation;
  const labels: Record<string, string> = {
    supports: "支持",
    contradicts: "矛盾",
    derived_from: "源自",
    supersedes: "取代",
    corroborates: "相互印证",
  };
  return labels[relation] ?? relation;
}
