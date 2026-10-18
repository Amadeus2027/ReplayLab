import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Background, Controls, ReactFlow, MarkerType } from "@xyflow/react";
import type { Task, Workflow, Frame } from "./types";
import "@xyflow/react/dist/style.css";
import "./style.css";

const labels: Record<string, string> = {
  created: "已创建",
  acquiring: "获取视频",
  extracting: "提取画面",
  compiling: "恢复步骤",
  needs_review: "待审核",
  approved: "已审核",
  executing: "执行中",
  passed: "已通过",
  failed: "失败",
  paused: "已暂停",
};

function App() {
  const [token, setToken] = useState(
    () => sessionStorage.getItem("replaylab-token") || "",
  );
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskId, setTaskId] = useState(
    () => new URLSearchParams(location.hash.slice(1)).get("task") || "",
  );
  const [task, setTask] = useState<Task>();
  const [workflow, setWorkflow] = useState<Workflow>();
  const [selected, setSelected] = useState(0);
  const [draft, setDraft] = useState("");
  const [dirty, setDirty] = useState(false);
  const [source, setSource] = useState("");
  const [startUrl, setStartUrl] = useState("");
  const [params, setParams] = useState("{}");
  const [confirmed, setConfirmed] = useState(false);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function api(path: string, method = "GET", body?: unknown) {
    const response = await fetch(`/api${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    const result = await response.json();
    if (!response.ok)
      throw new Error(
        typeof result.detail === "string"
          ? result.detail
          : JSON.stringify(result.detail),
      );
    return result;
  }

  async function refresh(updateWorkflow = false) {
    const list = await api("/tasks");
    setTasks(list);
    if (taskId) {
      const next: Task = await api(`/tasks/${taskId}`);
      setTask(next);
      if (updateWorkflow || (!dirty && !workflow && next.workflow))
        setWorkflow(next.workflow);
    }
  }

  useEffect(() => {
    sessionStorage.setItem("replaylab-token", token);
  }, [token]);
  useEffect(() => {
    if (!token) return;
    let active = true;
    const poll = async () => {
      try {
        const list = await api("/tasks");
        if (!active) return;
        setTasks(list);
        if (taskId) {
          const next: Task = await api(`/tasks/${taskId}`);
          if (!active) return;
          setTask(next);
          setWorkflow((current) => current || next.workflow);
        }
      } catch (error) {
        if (active) setNotice(String(error));
      }
    };
    void poll();
    const timer = setInterval(poll, 2500);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [taskId, token]);

  useEffect(() => {
    setDraft(
      workflow?.steps[selected]
        ? JSON.stringify(workflow.steps[selected], null, 2)
        : "",
    );
  }, [workflow, selected]);

  function choose(id: string) {
    if (dirty && !window.confirm("放弃尚未保存的修改并切换任务？")) return;
    setTaskId(id);
    setTask(undefined);
    setWorkflow(undefined);
    setSelected(0);
    setDirty(false);
    setConfirmed(false);
    setParams("{}");
    location.hash = `task=${id}`;
  }

  async function act(action: () => Promise<void>) {
    setBusy(true);
    setNotice("");
    try {
      await action();
    } catch (error) {
      setNotice(String(error));
    } finally {
      setBusy(false);
    }
  }

  const step = workflow?.steps[selected];
  const unapplied = !!step && draft !== JSON.stringify(step, null, 2);
  const running =
    busy ||
    ["acquiring", "extracting", "compiling", "executing", "created"].includes(
      task?.status || "",
    );
  const approved = workflow?.steps.every((item) => item.status === "approved");
  const nodes = (workflow?.steps || []).map((item, index) => ({
    id: item.id,
    position: { x: 70, y: index * 115 },
    data: {
      label: `${String(index + 1).padStart(2, "0")} · ${item.description}\n${item.action} · ${labels[item.status]}${item.sensitive ? " · 敏感操作" : ""}`,
    },
    className: `flow-step ${index === selected ? "chosen" : ""}`,
  }));
  const edges = (workflow?.steps.slice(1) || []).map((item, index) => ({
    id: `e-${item.id}`,
    source: workflow!.steps[index].id,
    target: item.id,
    markerEnd: { type: MarkerType.ArrowClosed },
  }));
  const frames =
    task?.evidence?.frames.filter((frame) =>
      step?.source.frame_ids.includes(frame.id),
    ) || [];

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-icon">↻</span> ReplayLab <small>0.1</small>
        </div>
        <p className="muted">从演示到执行</p>
        <label className="token">
          本机访问令牌
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="粘贴 .replaylab/token 内容"
          />
        </label>
        <div className="section-label">
          工作流任务 <span>{tasks.length}</span>
        </div>
        <nav>
          {tasks.map((item) => (
            <button
              className={`task ${taskId === item.id ? "active" : ""}`}
              key={item.id}
              onClick={() => choose(item.id)}
            >
              <strong>{item.id}</strong>
              <span>{labels[item.status] || item.status}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          视频 → 证据 → 工作流 → Skill
          <br />
          本地服务 · 隔离浏览器执行
        </div>
      </aside>
      <main>
        <header>
          <div>
            <div className="eyebrow">VIDEO TO WORKFLOW</div>
            <h1>把演示，变成下一次行动。</h1>
            <p className="muted">
              恢复操作步骤，核对画面证据，再执行你确认的流程。
            </p>
          </div>
          <span className="version">LOCAL / v0.1</span>
        </header>
        <form
          className="source-form"
          onSubmit={(event) => {
            event.preventDefault();
            void act(async () => {
              const result = await api("/tasks", "POST", {
                source,
                start_url: startUrl,
              });
              choose(result.id);
            });
          }}
        >
          <label>
            视频来源
            <input
              required
              value={source}
              onChange={(e) => setSource(e.target.value)}
              placeholder="公开视频链接或服务端本地视频路径"
            />
          </label>
          <label>
            复现网页
            <input
              required
              type="url"
              value={startUrl}
              onChange={(e) => setStartUrl(e.target.value)}
              placeholder="https://example.com"
            />
          </label>
          <button className="primary" disabled={busy || !token}>
            分析视频 ↗
          </button>
        </form>
        {notice && (
          <div className="notice" role="status">
            {notice}
          </div>
        )}
        {task?.error && <div className="notice error">{task.error}</div>}
        <div className="workspace-title">
          <h2>{workflow?.title || "工作流工作台"}</h2>
          <span className={`badge ${task?.status}`}>
            {task ? labels[task.status] || task.status : "等待输入"}
          </span>
        </div>
        {!workflow ? (
          <div className="empty">
            <div className="empty-icon">⌘</div>
            <h2>{task ? "正在准备工作流" : "从一段操作演示开始"}</h2>
            <p>
              {task
                ? `当前阶段：${labels[task.status] || task.status}`
                : "输入视频，或从左侧选择已有任务。模型生成后，操作步骤与画面证据会显示在这里。"}
            </p>
            <p className="muted">
              支持点击、输入、选择、勾选、按键和页面导航。
            </p>
          </div>
        ) : (
          <>
            <div className="toolbar">
              <span>
                {workflow.steps.length} 个步骤 ·{" "}
                {task?.evidence
                  ? `${(task.evidence.duration_ms / 1000).toFixed(1)}s 视频`
                  : "导入流程 · 无视频证据"}
              </span>
              <div>
                <button
                  disabled={running || !dirty || unapplied}
                  onClick={() =>
                    void act(async () => {
                      const updated = await api(
                        `/tasks/${taskId}/workflow`,
                        "PUT",
                        workflow,
                      );
                      setWorkflow(updated);
                      setDirty(false);
                      setConfirmed(false);
                      await refresh();
                      setNotice("已保存；修改后的步骤需要重新审核。");
                    })
                  }
                >
                  保存修改{dirty ? " *" : ""}
                </button>
                <button
                  disabled={
                    running ||
                    dirty ||
                    !!workflow.uncertainties.length ||
                    approved
                  }
                  onClick={() =>
                    void act(async () => {
                      if (
                        !window.confirm(
                          "我已核对所有步骤、证据、前置条件和允许访问的网站，确认审核通过。",
                        )
                      )
                        return;
                      setWorkflow(
                        await api(`/tasks/${taskId}/approve`, "POST"),
                      );
                      await refresh();
                    })
                  }
                >
                  审核通过
                </button>
              </div>
            </div>
            <div className="workspace">
              <section className="graph">
                <ReactFlow
                  nodes={nodes}
                  edges={edges}
                  fitView
                  nodesDraggable={false}
                  nodesConnectable={false}
                  onNodeClick={(_, node) => {
                    if (
                      unapplied &&
                      !window.confirm("放弃尚未应用的步骤编辑？")
                    )
                      return;
                    setSelected(
                      workflow.steps.findIndex((item) => item.id === node.id),
                    );
                  }}
                >
                  <Background gap={20} color="#dce4e1" />
                  <Controls showInteractive={false} />
                </ReactFlow>
              </section>
              <section className="inspector">
                <div className="section-label">
                  步骤 {String(selected + 1).padStart(2, "0")} / 画面证据
                </div>
                <h3>{step?.description}</h3>
                <p className="muted">
                  {step &&
                    `${(step.source.start_ms / 1000).toFixed(1)}–${(step.source.end_ms / 1000).toFixed(1)}s · 模型自评 ${Math.round(step.confidence * 100)}%（未经校准）`}
                </p>
                <div className="frames">
                  {frames.map((frame) => (
                    <EvidenceImage
                      key={frame.id}
                      frame={frame}
                      taskId={taskId}
                      token={token}
                    />
                  ))}
                </div>
                {!frames.length && (
                  <p className="muted">此步骤没有可用的画面文件。</p>
                )}
                <label>
                  步骤数据
                  <textarea
                    spellCheck={false}
                    rows={15}
                    value={draft}
                    onChange={(e) => {
                      setDraft(e.target.value);
                      setDirty(true);
                    }}
                  />
                </label>
                <button
                  disabled={running}
                  onClick={() =>
                    void act(async () => {
                      const edited = JSON.parse(draft);
                      const next = structuredClone(workflow);
                      next.steps[selected] = edited;
                      const validated = await api("/validate", "POST", next);
                      setWorkflow(validated);
                      setDirty(true);
                      setNotice("步骤校验通过，已应用到本地流程。请保存修改。");
                    })
                  }
                >
                  应用步骤编辑
                </button>
                {unapplied && (
                  <p className="muted">请先应用步骤编辑，再保存流程。</p>
                )}
              </section>
            </div>
            <section className="details">
              <div>
                <h3>运行条件与待确认项</h3>
                <p className="muted">
                  允许网站：{workflow.allowed_origins.join(", ")}
                </p>
                {workflow.preconditions.map((text, i) => (
                  <p key={i}>□ {text}</p>
                ))}
                <label>
                  待确认项（解决后删除对应行）
                  <textarea
                    rows={3}
                    value={workflow.uncertainties.join("\n")}
                    onChange={(e) => {
                      setWorkflow({
                        ...workflow,
                        uncertainties: e.target.value
                          .split("\n")
                          .filter(Boolean),
                      });
                      setDirty(true);
                    }}
                  />
                </label>
                <details>
                  <summary>编辑完整工作流（顺序、断言、参数与目标）</summary>
                  <FullEditor
                    workflow={workflow}
                    onApply={(next) =>
                      void act(async () => {
                        const validated = await api("/validate", "POST", next);
                        setWorkflow(validated);
                        setSelected(0);
                        setDirty(true);
                      })
                    }
                  />
                </details>
              </div>
              <div>
                <h3>执行与导出</h3>
                {Object.entries(workflow.parameters).map(([key, value]) => (
                  <p className="muted" key={key}>
                    {key}：{value}
                  </p>
                ))}
                <label>
                  本次参数（JSON 字符串映射）
                  <textarea
                    rows={3}
                    value={params}
                    onChange={(e) => setParams(e.target.value)}
                  />
                </label>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                  />{" "}
                  本次执行已获授权的敏感步骤
                </label>
                <div className="actions">
                  <button
                    className="primary"
                    disabled={running || dirty || !approved}
                    onClick={() =>
                      void act(async () => {
                        await api(`/tasks/${taskId}/execute`, "POST", {
                          parameters: JSON.parse(params),
                          confirm_sensitive: confirmed,
                        });
                        await refresh();
                      })
                    }
                  >
                    在新浏览器中执行 ↗
                  </button>
                  <button
                    disabled={
                      running || dirty || task?.report?.status !== "passed"
                    }
                    onClick={() =>
                      void act(async () => {
                        const result = await api(
                          `/tasks/${taskId}/export`,
                          "POST",
                        );
                        setNotice(`Skill 已导出至本机：${result.path}`);
                      })
                    }
                  >
                    导出 Skill
                  </button>
                </div>
                {task?.report && (
                  <div className="report">
                    <strong>执行结果：{labels[task.report.status]}</strong>
                    <p>
                      {task.report.seconds}s ·{" "}
                      {
                        task.report.steps.filter(
                          (item) => item.status === "passed",
                        ).length
                      }
                      /{workflow.steps.length} 步通过
                    </p>
                    {task.report.error && <pre>{task.report.error}</pre>}
                  </div>
                )}
              </div>
            </section>
          </>
        )}
        <footer>
          ReplayLab · 开源演示复用实验室{" "}
          <span>流程审核后执行 / 失败即停止</span>
        </footer>
      </main>
    </div>
  );
}

function FullEditor({
  workflow,
  onApply,
}: {
  workflow: Workflow;
  onApply: (workflow: Workflow) => void;
}) {
  const [value, setValue] = useState(JSON.stringify(workflow, null, 2));
  const [error, setError] = useState("");
  useEffect(() => {
    setValue(JSON.stringify(workflow, null, 2));
  }, [workflow]);
  return (
    <>
      <textarea
        rows={14}
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
      <button
        onClick={() => {
          try {
            const next = JSON.parse(value);
            if (
              !next.steps?.length ||
              !Array.isArray(next.uncertainties) ||
              !Array.isArray(next.allowed_origins) ||
              !Array.isArray(next.preconditions) ||
              !next.parameters ||
              !Array.isArray(next.postconditions)
            )
              throw new Error();
            onApply(next);
            setError("");
          } catch {
            setError("请检查工作流 JSON 和必要字段。");
          }
        }}
      >
        应用完整流程
      </button>
      {error && <p>{error}</p>}
    </>
  );
}

function EvidenceImage({
  frame,
  taskId,
  token,
}: {
  frame: Frame;
  taskId: string;
  token: string;
}) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    let objectUrl = "";
    let active = true;
    void fetch(
      `/api/tasks/${taskId}/assets/frames/${frame.path.split("/").pop()}`,
      { headers: { Authorization: `Bearer ${token}` } },
    )
      .then((response) => {
        if (!response.ok) throw new Error("Frame unavailable");
        return response.blob();
      })
      .then((blob) => {
        if (active) {
          objectUrl = URL.createObjectURL(blob);
          setUrl(objectUrl);
        }
      })
      .catch(() => setUrl(""));
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [taskId, token, frame.path]);
  return (
    <figure>
      {url && (
        <a href={url} target="_blank" rel="noreferrer">
          <img src={url} alt={`${frame.id} 的视频证据`} />
        </a>
      )}
      <figcaption>
        {frame.id} · {(frame.timestamp_ms / 1000).toFixed(2)}s
      </figcaption>
    </figure>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
