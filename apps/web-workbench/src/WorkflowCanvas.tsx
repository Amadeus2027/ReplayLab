import { useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import {
  ArrowUpRight,
  Check,
  CheckSquare,
  ChevronRight,
  Circle,
  CornerDownLeft,
  Globe,
  List,
  Loader2,
  MousePointer2,
  Network,
  TextCursorInput,
} from "lucide-react";
import type { Step, Workflow, Report } from "./types";

export const actionNames: Record<Step["action"], string> = {
  click: "点击",
  fill: "填写内容",
  select: "选择选项",
  check: "勾选",
  press: "按键",
  navigate: "打开网页",
};
export const actionIcons = {
  click: MousePointer2,
  fill: TextCursorInput,
  select: List,
  check: CheckSquare,
  press: CornerDownLeft,
  navigate: Globe,
};
export function timeLabel(ms: number) {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
}

type Operation = Node<
  {
    step: Step;
    index: number;
    state: string;
    active: boolean;
    input: Position;
    output: Position;
  },
  "operation"
>;
function OperationCard({ data }: NodeProps<Operation>) {
  const Icon = actionIcons[data.step.action];
  return (
    <div
      className={`operation-card ${data.active ? "is-selected" : ""} ${data.state}`}
    >
      <Handle type="target" position={data.input} />
      <div className="operation-top">
        <span className={`action-icon ${data.step.action}`}>
          <Icon size={17} strokeWidth={1.7} />
        </span>
        <span className="operation-index">
          STEP {String(data.index + 1).padStart(2, "0")}
        </span>
        <span className="operation-state">
          {data.state === "passed" ? (
            <Check size={13} />
          ) : data.state === "running" ? (
            <Loader2 size={13} className="spin" />
          ) : (
            <Circle size={9} />
          )}
        </span>
      </div>
      <strong>{data.step.description}</strong>
      <div className="operation-meta">
        <span>{actionNames[data.step.action]}</span>
        <span>
          {timeLabel(data.step.source.start_ms)} <ArrowUpRight size={10} />
        </span>
      </div>
      <Handle type="source" position={data.output} />
    </div>
  );
}
const nodeTypes = { operation: OperationCard };

export function WorkflowCanvas({
  workflow,
  report,
  executing,
  selected,
  onSelect,
}: {
  workflow: Workflow;
  report?: Report;
  executing: boolean;
  selected: number;
  onSelect: (index: number) => void;
}) {
  const [list, setList] = useState(false);
  const states = new Map(report?.steps.map((step) => [step.id, step.status]));
  const nodes: Operation[] = workflow.steps.map((step, index) => {
    const row = Math.floor(index / 3);
    const reversed = row % 2 === 1;
    const column = reversed ? 2 - (index % 3) : index % 3;
    return {
      id: step.id,
      type: "operation",
      selected: index === selected,
      position: { x: column * 285, y: row * 215 },
      data: {
        step,
        index,
        state: states.get(step.id) || "pending",
        active: index === selected,
        input:
          index > 0 && index % 3 === 0
            ? Position.Top
            : reversed
              ? Position.Right
              : Position.Left,
        output:
          index % 3 === 2 && index < workflow.steps.length - 1
            ? Position.Bottom
            : reversed
              ? Position.Left
              : Position.Right,
      },
    };
  });
  const edges = workflow.steps.slice(1).map((step, index) => ({
    id: `edge-${step.id}`,
    source: workflow.steps[index].id,
    target: step.id,
    type: "smoothstep",
    animated: executing && states.get(step.id) === "running",
    markerEnd: {
      type: MarkerType.ArrowClosed,
      width: 13,
      height: 13,
      color: states.get(step.id) === "passed" ? "#82977a" : "#4e4e57",
    },
    style: {
      stroke: states.get(step.id) === "passed" ? "#82977a" : "#46464e",
      strokeWidth: 1.4,
    },
    pathOptions: { borderRadius: 18 },
  }));
  return (
    <section className="canvas-section" aria-label="视频操作流程">
      <div className="canvas-bar">
        <div className="view-switch">
          <button
            className={!list ? "active" : ""}
            onClick={() => setList(false)}
          >
            <Network size={13} />
            流程画布
          </button>
          <button
            className={list ? "active" : ""}
            onClick={() => setList(true)}
          >
            <List size={13} />
            步骤列表
          </button>
        </div>
        <span className="canvas-help">
          {workflow.steps.length} 个步骤 · 按视频顺序还原
        </span>
      </div>
      {list ? (
        <div className="step-list">
          {workflow.steps.map((step, index) => {
            const Icon = actionIcons[step.action];
            return (
              <button
                key={step.id}
                className={index === selected ? "active" : ""}
                onClick={() => onSelect(index)}
              >
                <span className="list-index">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <Icon size={17} />
                <div>
                  <strong>{step.description}</strong>
                  <span>
                    {actionNames[step.action]} ·{" "}
                    {timeLabel(step.source.start_ms)}
                  </span>
                </div>
                {states.get(step.id) === "passed" ? (
                  <Check size={16} className="success-text" />
                ) : (
                  <ChevronRight size={16} />
                )}
              </button>
            );
          })}
        </div>
      ) : (
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.18 }}
          minZoom={0.25}
          maxZoom={1.3}
          nodesDraggable={false}
          nodesConnectable={false}
          onNodeClick={(_, node) =>
            onSelect(workflow.steps.findIndex((step) => step.id === node.id))
          }
          proOptions={{ hideAttribution: false }}
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={22}
            size={1}
            color="#29292f"
          />
          <Controls showInteractive={false} />
        </ReactFlow>
      )}
    </section>
  );
}
