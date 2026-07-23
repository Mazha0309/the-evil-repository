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
} from "@xyflow/react";
import { Database, GitCommitHorizontal, Lightbulb, ScrollText } from "lucide-react";
import { useMemo } from "react";
import type { InvestigationGraph as GraphData } from "../lib/types";

type GraphNodeData = {
  title: string;
  body: string;
  meta: string;
  kind: "hypothesis" | "evidence";
  status?: string;
};

function GraphNode({ data }: NodeProps<Node<GraphNodeData>>) {
  const Icon =
    data.kind === "hypothesis"
      ? Lightbulb
      : data.meta.includes("database")
        ? Database
        : data.meta.includes("git")
          ? GitCommitHorizontal
          : ScrollText;
  return (
    <div className={`graph-node graph-node--${data.kind}`} data-status={data.status}>
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
}

const nodeTypes = { investigation: GraphNode };

export default function InvestigationGraphView({ graph }: { graph: GraphData }) {
  const { nodes, edges } = useMemo(() => {
    const evidenceNodes: Node<GraphNodeData>[] = graph.evidence.map((item, index) => ({
      id: `evidence:${item.key}`,
      type: "investigation",
      position: { x: 40 + (index % 2) * 320, y: 40 + Math.floor(index / 2) * 160 },
      data: {
        title: item.key,
        body: item.summary,
        meta: `${item.source_type} · trust ${Math.round(item.trust * 100)}%`,
        kind: "evidence",
      },
    }));
    const hypothesisNodes: Node<GraphNodeData>[] = graph.hypotheses.map((item, index) => ({
      id: `hypothesis:${item.key}`,
      type: "investigation",
      position: { x: 760 + (index % 2) * 340, y: 40 + Math.floor(index / 2) * 180 },
      data: {
        title: `${item.key} · ${Math.round(item.confidence * 100)}%`,
        body: item.statement,
        meta: item.status,
        status: item.status,
        kind: "hypothesis",
      },
    }));
    const graphEdges: Edge[] = graph.edges.map((item) => ({
      id: item.id,
      source: `${item.source_type}:${item.source_key}`,
      target: `${item.target_type}:${item.target_key}`,
      label: item.relation,
      animated: item.relation === "supports" || item.relation === "corroborates",
      style: {
        stroke: item.relation === "contradicts" ? "#ff5d5d" : "#adff2f",
        strokeWidth: 1.5,
      },
      labelStyle: { fill: "#a8b0a1", fontSize: 10 },
      labelBgStyle: { fill: "#10130f", fillOpacity: 0.9 },
    }));
    return { nodes: [...evidenceNodes, ...hypothesisNodes], edges: graphEdges };
  }, [graph]);

  if (!nodes.length) {
    return (
      <div className="empty-state empty-state--graph">
        <Lightbulb size={32} />
        <h3>No investigation graph yet</h3>
        <p>The candidate has not recorded a hypothesis or evidence node.</p>
      </div>
    );
  }

  return (
    <div className="graph-canvas">
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView minZoom={0.2}>
        <Background color="#293124" gap={24} variant={BackgroundVariant.Dots} />
        <MiniMap
          nodeColor={(node) =>
            (node.data as GraphNodeData).kind === "hypothesis" ? "#adff2f" : "#4cc9f0"
          }
          maskColor="rgba(5, 7, 5, .72)"
        />
        <Controls />
      </ReactFlow>
    </div>
  );
}
