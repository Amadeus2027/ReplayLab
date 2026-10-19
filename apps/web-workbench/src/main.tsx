import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleCheck,
  CircleHelp,
  Clock3,
  ExternalLink,
  FileVideo,
  Film,
  Loader2,
  Monitor,
  Pencil,
  Play,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Workflow as WorkflowIcon,
  X,
} from "lucide-react";
import { Dialog, CreateDialog, RunDialog } from "./dialogs";
import { LiquidSurface } from "./LiquidSurface";
import {
  WorkflowCanvas,
  actionIcons,
  actionNames,
  timeLabel,
} from "./WorkflowCanvas";
import type { Task, Workflow, Frame, Step } from "./types";
import "@xyflow/react/dist/style.css";
import "../../../examples/demo/theme.css";
import "./style.css";

const statusNames: Record<string, string> = {
  created: "准备中",
  acquiring: "正在读取视频",
  extracting: "正在提取关键画面",
  compiling: "正在整理操作流程",
  needs_review: "等待你的确认",
  approved: "可以执行",
  executing: "Agent 执行中",
  passed: "执行完成",
  failed: "需要处理",
  paused: "等待补充信息",
};
const processingStates = ["created", "acquiring", "extracting", "compiling"];
function cleanTitle(title?: string) {
  return (
    title
      ?.replace(
        /（(?:手工|非模型|示例)[^）]*）|\((?:hand-authored|manual)[^)]*\)/gi,
        "",
      )
      .trim() || "未命名流程"
  );
}
function sourceName(source?: string) {
  if (!source) return "操作演示视频";
  try {
    return new URL(source).hostname;
  } catch {
    return source.split(/[\\/]/).pop() || "操作演示视频";
  }
}
function verificationText(step: Step) {
  const check = step.verification;
  if (check.type === "url") return `页面跳转至 ${check.expected}`;
  if (check.type === "checked")
    return `${check.target?.description || "对应选项"}已勾选`;
  if (check.type === "value")
    return `${check.target?.description || "输入内容"}与预期一致`;
  if (check.type === "text") return `页面显示“${check.expected}”`;
  return `确认${check.target?.description || "目标元素"}已出现`;
}

function App() {
  const [token, setToken] = useState(
    () => sessionStorage.getItem("replaylab-token") || "",
  );
  const [connected, setConnected] = useState(false);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskId, setTaskId] = useState(
    () => new URLSearchParams(location.hash.slice(1)).get("task") || "",
  );
  const [task, setTask] = useState<Task>();
  const [workflow, setWorkflow] = useState<Workflow>();
  const [workflowDigest, setWorkflowDigest] = useState("");
  const [workflowOrigin, setWorkflowOrigin] =
    useState<Task["workflow_origin"]>("unknown");
  const [conflict, setConflict] = useState(false);
  const [selected, setSelected] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [modal, setModal] = useState<
    "create" | "run" | "settings" | "edit" | "video" | null
  >(null);
  const [mediaUrl, setMediaUrl] = useState("");
  const mediaRef = useRef("");
  const videoRef = useRef<HTMLVideoElement>(null);
  const viewRef = useRef({
    digest: "",
    dirty: false,
    busy: false,
    reviewing: false,
    conflict: false,
  });
  viewRef.current = {
    digest: workflowDigest,
    dirty,
    busy,
    reviewing: modal === "run" || modal === "edit",
    conflict,
  };

  async function request(path: string, init?: RequestInit) {
    const response = await fetch(
      path.startsWith("/api") ? path : `/api${path}`,
      {
        ...init,
        headers: { Authorization: `Bearer ${token}`, ...init?.headers },
      },
    );
    if (!response.ok) {
      const result = await response.json().catch(() => null);
      if (response.status === 401)
        throw new Error("请先在设置中连接本机服务。");
      if (response.status === 409) {
        if (result?.code === "workflow_conflict") {
          setConflict(true);
          setModal(null);
          setNotice(result.detail);
        }
        throw new Error(
          typeof result?.detail === "string"
            ? result.detail
            : "请先完成流程确认，或等待当前任务结束。",
        );
      }
      throw new Error(
        typeof result?.detail === "string"
          ? result.detail
          : "操作未完成，请检查输入或本机服务。",
      );
    }
    return response;
  }
  async function api(path: string, method = "GET", body?: unknown) {
    return (
      await request(path, {
        method,
        ...(body !== undefined
          ? {
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body),
            }
          : {}),
      })
    ).json();
  }
  function choose(id: string) {
    if (busy) return;
    if (dirty && !window.confirm("切换后将放弃尚未保存的步骤修改，继续吗？"))
      return;
    setTaskId(id);
    setTask(undefined);
    setWorkflow(undefined);
    setWorkflowDigest("");
    setWorkflowOrigin("unknown");
    setConflict(false);
    setSelected(0);
    setDirty(false);
    setNotice("");
    location.hash = id ? `task=${id}` : "";
  }
  async function act(action: () => Promise<void>) {
    setBusy(true);
    setNotice("");
    try {
      await action();
    } catch (error) {
      setNotice(String(error).replace(/^Error: /, ""));
    } finally {
      setBusy(false);
    }
  }
  function acceptTask(next: Task, force = false) {
    setTask(next);
    const view = viewRef.current;
    if (!force && next.workflow_digest === view.digest) {
      setWorkflowOrigin(next.workflow_origin || "unknown");
      return;
    }
    if (!force && view.busy) return;
    if (
      !force &&
      view.digest &&
      (view.dirty || view.reviewing || view.conflict)
    ) {
      setConflict(true);
      setModal(null);
      setNotice("流程已在其他位置更新。请加载最新流程，重新核对后执行。");
      return;
    }
    if (!force && view.digest)
      setNotice("流程已更新，请重新核对步骤与运行条件。");
    setWorkflow(next.workflow);
    setWorkflowDigest(next.workflow_digest || "");
    setWorkflowOrigin(next.workflow_origin || "unknown");
    setSelected(0);
    setDirty(false);
    setConflict(false);
  }
  async function refresh() {
    setTasks(await api("/tasks"));
    if (taskId) acceptTask(await api(`/tasks/${taskId}`), true);
  }
  async function reloadWorkflow() {
    if (dirty && !window.confirm("加载后将放弃尚未保存的修改，继续吗？"))
      return;
    await act(refresh);
  }
  useEffect(() => {
    sessionStorage.setItem("replaylab-token", token);
  }, [token]);
  useEffect(() => {
    if (!token) {
      setConnected(false);
      return;
    }
    let active = true;
    const poll = async () => {
      try {
        const list: Task[] = await api("/tasks");
        if (!active) return;
        setConnected(true);
        setTasks(list);
        if (taskId) {
          const next: Task = await api(`/tasks/${taskId}`);
          if (!active) return;
          acceptTask(next);
        }
      } catch {
        if (active) setConnected(false);
      }
    };
    void poll();
    const timer = setInterval(poll, 1500);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [token, taskId]);
  useEffect(() => {
    if (mediaRef.current) URL.revokeObjectURL(mediaRef.current);
    mediaRef.current = "";
    setMediaUrl("");
    return () => {
      if (mediaRef.current) URL.revokeObjectURL(mediaRef.current);
    };
  }, [taskId]);

  const step = workflow?.steps[selected];
  const executing = task?.status === "executing";
  const processing = processingStates.includes(task?.status || "");
  const blocked = busy || executing || processing || conflict;
  const manual = workflowOrigin === "manual";
  const originLabel = {
    manual: "人工导入流程",
    video: "视频分析生成",
    video_edited: "视频分析生成 · 已人工修改",
    unknown: "流程来源未核验",
  }[
    dirty && workflowOrigin === "video"
      ? "video_edited"
      : workflowOrigin || "unknown"
  ];
  const report =
    dirty ||
    conflict ||
    task?.report?.workflow_digest !== workflowDigest ||
    ["needs_review", "approved"].includes(task?.status || "") ||
    (executing && task?.report?.status !== "running")
      ? undefined
      : task?.report;
  const passed =
    report?.steps.filter((item) => item.status === "passed").length || 0;
  const activeExecution = report?.steps.find(
    (item) => item.status === "running",
  );
  const frames =
    task?.evidence?.frames.filter((frame) =>
      step?.source.frame_ids.includes(frame.id),
    ) || [];
  const currentResult = report?.steps.find((item) => item.id === step?.id);
  const screenshotFrame = frames[frames.length - 1];
  const workflowReady = !!workflow && !workflow.uncertainties.length;

  async function create(source: string | File, startUrl: string) {
    setBusy(true);
    try {
      let result;
      if (typeof source === "string")
        result = await api("/tasks", "POST", { source, start_url: startUrl });
      else {
        const data = new FormData();
        data.append("video", source);
        data.append("start_url", startUrl);
        result = await (
          await request("/tasks/upload", { method: "POST", body: data })
        ).json();
      }
      choose(result.id);
      setModal(null);
    } finally {
      setBusy(false);
    }
  }
  async function run(parameters: Record<string, string>, sensitive: boolean) {
    if (!workflow || !workflowDigest || conflict) return;
    setBusy(true);
    try {
      let version = workflowDigest;
      if (dirty) {
        const saved = await api(`/tasks/${taskId}/workflow`, "PUT", {
          workflow,
          expected_digest: version,
        });
        setWorkflow(saved.workflow);
        setWorkflowDigest(saved.workflow_digest);
        version = saved.workflow_digest;
        setDirty(false);
      }
      const approved = await api(`/tasks/${taskId}/approve`, "POST", {
        expected_digest: version,
      });
      setWorkflow(approved.workflow);
      setWorkflowDigest(approved.workflow_digest);
      await api(`/tasks/${taskId}/execute`, "POST", {
        expected_digest: approved.workflow_digest,
        parameters,
        confirm_sensitive: sensitive,
      });
      setTask((current) =>
        current
          ? { ...current, status: "executing", report: undefined }
          : current,
      );
      setModal(null);
      await refresh();
    } finally {
      setBusy(false);
    }
  }
  async function downloadSkill() {
    const result = await api(`/tasks/${taskId}/export`, "POST");
    const blob = await (await request(result.download_url)).blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `replaylab-skill-${taskId}.zip`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice("Skill 已下载。下次可以直接复用这份操作流程。");
  }
  async function showVideo() {
    if (!task?.has_media) {
      setNotice("这份流程没有可播放的原视频，可以查看已有画面证据。");
      return;
    }
    if (!mediaUrl) {
      const url = URL.createObjectURL(
        await (await request(`/tasks/${taskId}/media`)).blob(),
      );
      mediaRef.current = url;
      setMediaUrl(url);
    }
    setModal("video");
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button
          className="brand"
          onClick={() => choose("")}
          aria-label="ReplayLab 首页"
        >
          <span className="brand-mark">
            <Play size={15} fill="currentColor" />
            <span />
          </span>
          <strong>
            replaylab<span>0.1.1</span>
          </strong>
        </button>
        <div className="workspace-picker">
          <span className="avatar">R</span>
          <div>
            我的工作空间<small>个人空间</small>
          </div>
          <ChevronDown size={13} />
        </div>
        <button className="new-workflow" onClick={() => setModal("create")}>
          <Plus size={16} />
          新建视频流程<span>＋</span>
        </button>
        <div className="sidebar-section">
          <span>我的流程</span>
          <span>{tasks.length.toString().padStart(2, "0")}</span>
        </div>
        <div className="sidebar-search">
          <Search size={13} />
          <input
            aria-label="搜索流程"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索流程"
          />
        </div>
        <nav className="task-navigation" aria-label="我的视频流程">
          {tasks
            .filter((item) =>
              `${item.title || ""} ${item.source}`.includes(search),
            )
            .map((item) => (
              <button
                key={item.id}
                className={`task-link ${taskId === item.id ? "active" : ""}`}
                onClick={() => choose(item.id)}
              >
                <WorkflowIcon size={14} />
                <div>
                  <strong>
                    {item.title
                      ? cleanTitle(item.title)
                      : sourceName(item.source)}
                  </strong>
                  <small>
                    <span className={`status-dot ${item.status}`} />
                    {statusNames[item.status] || "视频流程"}
                  </small>
                </div>
                {taskId === item.id && <span className="active-mark" />}
              </button>
            ))}
          {!tasks.length && (
            <p className="sidebar-empty">
              你的第一份视频流程
              <br />
              会出现在这里。
            </p>
          )}
        </nav>
        <div className="sidebar-bottom">
          <a
            href="https://github.com/Amadeus2027/ReplayLab/blob/main/docs/quickstart.md"
            target="_blank"
            rel="noreferrer"
          >
            <CircleHelp size={15} />
            使用指南
            <ArrowUpRight size={12} />
          </a>
          <button onClick={() => setModal("settings")}>
            <Settings2 size={15} />
            设置
            <span
              className={`connection-dot ${connected ? "connected" : ""}`}
            />
          </button>
          <div className="profile">
            <span className="avatar">Y</span>
            <div>
              个人工作空间
              <small>{connected ? "本机服务已连接" : "等待连接本机服务"}</small>
            </div>
            <span className="version">v0.1.1</span>
          </div>
        </div>
      </aside>
      <main className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <span>我的工作空间</span>
            <ChevronRight size={12} />
            <span>{workflow ? "视频工作流" : "概览"}</span>
          </div>
          <div className="topbar-right">
            <span className="private-label">
              <ShieldCheck size={12} />
              仅自己可见
            </span>
            <a
              className="icon-button"
              href="https://github.com/Amadeus2027/ReplayLab"
              target="_blank"
              rel="noreferrer"
              aria-label="查看开源项目"
            >
              <ExternalLink size={15} />
            </a>
          </div>
        </header>
        {notice && (
          <div className="toast" role="status">
            <CircleCheck size={16} />
            <span>{notice}</span>
            <button
              className="icon-button"
              onClick={() => setNotice("")}
              aria-label="关闭提示"
            >
              <X size={14} />
            </button>
          </div>
        )}
        {!workflow ? (
          <div className="home-screen">
            {task ? (
              <div className="processing-view">
                <span className="hero-symbol">
                  {processing ? (
                    <Loader2 size={30} className="spin" />
                  ) : (
                    <Film size={30} />
                  )}
                </span>
                <span className="eyebrow">VIDEO TO ACTION</span>
                <h1>
                  {processing
                    ? "正在读懂你的操作演示"
                    : "这段演示还需要一点处理"}
                </h1>
                <p>{statusNames[task.status] || "准备中"}</p>
                {processing ? (
                  <div className="analysis-stages">
                    {["acquiring", "extracting", "compiling"].map(
                      (state, index) => (
                        <span
                          className={
                            processingStates.indexOf(task.status) >= index + 1
                              ? "current"
                              : ""
                          }
                          key={state}
                        >
                          {index + 1}
                          <small>
                            {["读取视频", "提取画面", "还原流程"][index]}
                          </small>
                        </span>
                      ),
                    )}
                  </div>
                ) : (
                  <>
                    <p className="inline-error">
                      {task.error || "请检查视频来源和模型配置后重试。"}
                    </p>
                    <button
                      className="secondary"
                      onClick={() => setModal("create")}
                    >
                      重新提供视频
                      <ArrowRight size={14} />
                    </button>
                  </>
                )}
              </div>
            ) : (
              <div className="welcome">
                <div className="welcome-kicker">
                  <span />
                  <span>WATCH. UNDERSTAND. REPLAY.</span>
                </div>
                <h1>
                  视频里的操作，
                  <br />
                  <em>交给 Agent 来做。</em>
                </h1>
                <p>
                  把演示变成清晰的操作流程。
                  <br />
                  看懂每一步，然后让 Agent 为你完成。
                </p>
                <button
                  className="primary large"
                  onClick={() => setModal("create")}
                >
                  <Plus size={17} />
                  从一段视频开始
                  <ArrowUpRight size={17} />
                </button>
                <div className="welcome-flow">
                  <span>
                    <FileVideo size={17} />
                    提供视频
                  </span>
                  <i />
                  <span>
                    <WorkflowIcon size={17} />
                    查看操作流程
                  </span>
                  <i />
                  <span>
                    <Sparkles size={17} />
                    Agent 代操作
                  </span>
                </div>
              </div>
            )}
            <div className="home-footnote">
              <ShieldCheck size={13} />
              流程经你确认后执行 · 关键操作需要授权
            </div>
          </div>
        ) : (
          <>
            <div className="project-header">
              <div>
                <div className="project-eyebrow">
                  <span className="mini-icon">
                    <WorkflowIcon size={12} />
                  </span>
                  视频工作流
                  <span className="divider" />
                  {originLabel}
                  {dirty && <span className="unsaved">有未保存修改</span>}
                </div>
                <h1>{cleanTitle(workflow.title)}</h1>
                <div className="project-meta">
                  <span>
                    <Film size={12} />
                    {sourceName(task?.source)}
                  </span>
                  <span>
                    <Clock3 size={12} />
                    {task?.evidence
                      ? timeLabel(task.evidence.duration_ms)
                      : "无原视频"}
                  </span>
                  <span>{workflow.steps.length} 个操作步骤</span>
                </div>
              </div>
              <div className="project-actions">
                <span className={`run-status ${dirty ? "" : task?.status}`}>
                  <span className={`status-dot ${dirty ? "" : task?.status}`} />
                  {dirty
                    ? "流程已修改"
                    : statusNames[task?.status || "needs_review"]}
                </span>
                <button
                  className="secondary small"
                  disabled={
                    busy || executing || dirty || report?.status !== "passed"
                  }
                  onClick={() => void act(downloadSkill)}
                >
                  <ArrowDownToLine size={14} />
                  保存为 Skill
                </button>
              </div>
            </div>
            {conflict && (
              <div className="workflow-conflict" role="alert">
                <span>
                  流程已在其他位置更新。为避免执行旧版本，请加载最新流程后重新核对。
                </span>
                <button
                  className="secondary small"
                  disabled={busy}
                  onClick={() => void reloadWorkflow()}
                >
                  加载最新流程
                </button>
              </div>
            )}
            <div className="work-area">
              <div className="canvas-column">
                <WorkflowCanvas
                  key={taskId}
                  workflow={workflow}
                  report={report}
                  executing={executing}
                  selected={selected}
                  onSelect={setSelected}
                />
                <LiquidSurface
                  className={`agent-dock ${executing ? "executing" : ""}`}
                >
                  <span className="agent-avatar">
                    <Sparkles size={19} />
                  </span>
                  <div className="agent-dock-copy">
                    <strong>
                      {executing
                        ? "Agent 正在为你操作"
                        : report?.status === "passed"
                          ? "任务已完成，每一步都有验证"
                          : report?.status === "failed" ||
                              report?.status === "paused"
                            ? "Agent 已停止，等待你处理"
                            : "流程已就绪，剩下的交给 Agent"}
                    </strong>
                    <p>
                      {executing
                        ? activeExecution
                          ? workflow.steps.find(
                              (step) => step.id === activeExecution.id,
                            )?.description
                          : "正在准备独立浏览器会话…"
                        : report?.status === "passed"
                          ? `${passed} 个步骤全部完成 · 用时 ${report.seconds.toFixed(1)} 秒`
                          : workflow.uncertainties.length
                            ? `${workflow.uncertainties.length} 处内容需要你确认后再继续`
                            : "按视频步骤代操作，并为你检查最终结果。"}
                    </p>
                    {executing && (
                      <div className="execution-progress">
                        <span
                          style={{
                            width: `${(passed / workflow.steps.length) * 100}%`,
                          }}
                        />
                      </div>
                    )}
                  </div>
                  <button
                    className="primary"
                    disabled={blocked || !workflowReady || !connected}
                    onClick={() => setModal("run")}
                  >
                    {executing ? (
                      <Loader2 size={15} className="spin" />
                    ) : (
                      <Play size={13} fill="currentColor" />
                    )}
                    {executing
                      ? `${passed}/${workflow.steps.length}`
                      : report?.status === "passed"
                        ? "再次执行"
                        : "让 Agent 执行"}
                  </button>
                </LiquidSurface>
                {(report?.status === "failed" ||
                  report?.status === "paused") && (
                  <div className="execution-issue">
                    <ShieldCheck size={14} />
                    <div>
                      本次操作未完成，Agent 已停止。
                      <details>
                        <summary>查看原因</summary>
                        <pre>{report.error}</pre>
                      </details>
                      <small>
                        重新执行将从第一步开始，请先核对是否已有操作生效。
                      </small>
                    </div>
                  </div>
                )}
              </div>
              <aside className="inspector" aria-label="步骤详情">
                <div className="inspector-tabs">
                  <span>步骤详情</span>
                  <span>
                    {String(selected + 1).padStart(2, "0")}
                    <small>
                      {" "}
                      / {String(workflow.steps.length).padStart(2, "0")}
                    </small>
                  </span>
                </div>
                {step && (
                  <>
                    <div className="inspector-content">
                      <div className="detail-heading">
                        <span className={`detail-icon ${step.action}`}>
                          {React.createElement(actionIcons[step.action], {
                            size: 21,
                            strokeWidth: 1.5,
                          })}
                        </span>
                        <span className="subtle-badge">
                          {actionNames[step.action]}
                        </span>
                        <button
                          className="icon-button"
                          aria-label="编辑当前步骤"
                          disabled={blocked}
                          onClick={() => setModal("edit")}
                        >
                          <Pencil size={14} />
                        </button>
                      </div>
                      <h2>{step.description}</h2>
                      <p className="detail-subtitle">
                        {step.target?.description || "在目标网站中打开指定页面"}
                      </p>
                      <div className="evidence-heading">
                        <span>视频对应画面</span>
                        <span>
                          <Clock3 size={11} />
                          {timeLabel(step.source.start_ms)} –{" "}
                          {timeLabel(step.source.end_ms)}
                        </span>
                      </div>
                      <div className="evidence-preview">
                        {screenshotFrame ? (
                          <EvidenceImage
                            taskId={taskId}
                            token={token}
                            frame={screenshotFrame}
                          />
                        ) : (
                          <div className="no-evidence">
                            <Film size={25} />
                            <span>
                              {manual
                                ? "人工导入流程，没有关联的视频画面"
                                : "这一步暂没有可用画面"}
                            </span>
                          </div>
                        )}
                        {task?.has_media && (
                          <button
                            className="video-play"
                            aria-label="播放对应视频"
                            disabled={busy}
                            onClick={() => void act(showVideo)}
                          >
                            <Play size={16} fill="currentColor" />
                          </button>
                        )}
                        <span className="evidence-timestamp">
                          {timeLabel(
                            screenshotFrame?.timestamp_ms ||
                              step.source.start_ms,
                          )}
                        </span>
                      </div>
                      {frames.length > 1 && (
                        <div className="evidence-strip">
                          {frames.map((frame) => (
                            <div key={frame.id}>
                              <EvidenceImage
                                taskId={taskId}
                                token={token}
                                frame={frame}
                              />
                              <small>{timeLabel(frame.timestamp_ms)}</small>
                            </div>
                          ))}
                        </div>
                      )}
                      <div className="detail-divider" />
                      <div className="detail-label">Agent 将完成</div>
                      <div className="action-description">
                        <span className="tiny-action-icon">
                          {React.createElement(actionIcons[step.action], {
                            size: 14,
                          })}
                        </span>
                        <div>
                          <strong>{step.description}</strong>
                          {step.value && step.action !== "navigate" && (
                            <span>
                              {step.value.startsWith("${")
                                ? "执行前由你提供内容"
                                : `内容：${step.value}`}
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="verification">
                        <CircleCheck size={15} />
                        <div>
                          <strong>完成后检查</strong>
                          <p>{verificationText(step)}</p>
                        </div>
                      </div>
                      {step.sensitive && (
                        <div className="step-permission">
                          <ShieldCheck size={14} />
                          这一步需要你的执行授权
                        </div>
                      )}
                      {currentResult?.status === "passed" && (
                        <div className="step-result">
                          <Check size={14} />
                          本次执行已完成并验证
                        </div>
                      )}
                      {currentResult?.screenshot && (
                        <details className="result-screenshot">
                          <summary>
                            <Monitor size={13} />
                            查看 Agent 操作后的画面
                          </summary>
                          <ProtectedImage
                            key={`${currentResult.id}-${report?.seconds}`}
                            path={`/api/tasks/${taskId}/assets/execution/${currentResult.screenshot}`}
                            token={token}
                            alt="Agent 执行后的页面截图"
                          />
                        </details>
                      )}
                      {workflow.uncertainties.length > 0 && (
                        <div className="uncertainties">
                          <h3>待你确认</h3>
                          {workflow.uncertainties.map((text, index) => (
                            <div key={index}>
                              <p>{text}</p>
                              <button
                                disabled={blocked}
                                onClick={() => {
                                  if (
                                    window.confirm(
                                      "已核对并补全这处不确定内容？",
                                    )
                                  ) {
                                    setWorkflow({
                                      ...workflow,
                                      uncertainties:
                                        workflow.uncertainties.filter(
                                          (_, i) => i !== index,
                                        ),
                                    });
                                    setDirty(true);
                                  }
                                }}
                              >
                                已核对
                                <Check size={12} />
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="step-pagination">
                      <button
                        className="icon-button"
                        aria-label="上一步"
                        disabled={selected === 0}
                        onClick={() => setSelected((index) => index - 1)}
                      >
                        <ChevronLeft size={16} />
                      </button>
                      <span>
                        步骤 {selected + 1} / {workflow.steps.length}
                      </span>
                      <button
                        className="icon-button"
                        aria-label="下一步"
                        disabled={selected === workflow.steps.length - 1}
                        onClick={() => setSelected((index) => index + 1)}
                      >
                        <ChevronRight size={16} />
                      </button>
                    </div>
                  </>
                )}
              </aside>
            </div>
            <footer className="workspace-footer">
              <span>
                <span
                  className={`connection-dot ${connected ? "connected" : ""}`}
                />
                {connected ? "本机服务已连接" : "连接已断开，请检查设置"}
              </span>
              <span>
                你来确认，Agent 来完成。<span className="footer-dot">·</span>
                ReplayLab 0.1.1
              </span>
            </footer>
          </>
        )}
      </main>
      {modal === "create" && (
        <CreateDialog
          connected={connected}
          busy={busy}
          onClose={() => setModal(null)}
          onCreate={create}
          onConnect={() => setModal("settings")}
        />
      )}
      {modal === "run" && workflow && (
        <RunDialog
          workflow={workflow}
          busy={busy}
          onClose={() => setModal(null)}
          onRun={run}
        />
      )}
      {modal === "settings" && (
        <ConnectionSettings
          token={token}
          connected={connected}
          onSave={setToken}
          onClose={() => setModal(null)}
        />
      )}
      {modal === "edit" && workflow && step && (
        <EditStep
          step={step}
          onClose={() => setModal(null)}
          onSave={async (updated) => {
            const next = structuredClone(workflow);
            next.steps[selected] = updated;
            setBusy(true);
            try {
              const saved = await api(`/tasks/${taskId}/workflow`, "PUT", {
                workflow: next,
                expected_digest: workflowDigest,
              });
              setWorkflow(saved.workflow);
              setWorkflowDigest(saved.workflow_digest);
              setDirty(false);
              await refresh();
              setNotice("步骤已保存，执行前会重新确认流程。");
              setModal(null);
            } finally {
              setBusy(false);
            }
          }}
        />
      )}
      {modal === "video" && (
        <Dialog title="视频中的这一步" onClose={() => setModal(null)} wide>
          <video
            ref={videoRef}
            className="original-video"
            src={mediaUrl}
            controls
            autoPlay
            onLoadedMetadata={() => {
              if (videoRef.current)
                videoRef.current.currentTime =
                  (step?.source.start_ms || 0) / 1000;
            }}
          />
          <p className="dialog-description">
            {step?.description} · {timeLabel(step?.source.start_ms || 0)}
          </p>
        </Dialog>
      )}
    </div>
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
  return (
    <ProtectedImage
      path={`/api/tasks/${taskId}/assets/frames/${frame.path.split("/").pop()}`}
      token={token}
      alt={`视频 ${timeLabel(frame.timestamp_ms)} 的操作画面`}
    />
  );
}
function ProtectedImage({
  path,
  token,
  alt,
}: {
  path: string;
  token: string;
  alt: string;
}) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    let objectUrl = "";
    const controller = new AbortController();
    setUrl("");
    void fetch(path, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error();
        return response.blob();
      })
      .then((blob) => {
        if (!controller.signal.aborted) {
          objectUrl = URL.createObjectURL(blob);
          setUrl(objectUrl);
        }
      })
      .catch(() => {});
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path, token]);
  return url ? (
    <img src={url} alt={alt} />
  ) : (
    <div className="image-loading">
      <Film size={20} />
      <span>画面暂不可用</span>
    </div>
  );
}
function ConnectionSettings({
  token,
  connected,
  onSave,
  onClose,
}: {
  token: string;
  connected: boolean;
  onSave: (value: string) => void;
  onClose: () => void;
}) {
  const [value, setValue] = useState(token);
  return (
    <Dialog title="连接与设置" eyebrow="WORKSPACE SETTINGS" onClose={onClose}>
      <div className="settings-status">
        <span className={`connection-dot ${connected ? "connected" : ""}`} />
        {connected ? "本机服务已连接" : "尚未连接本机服务"}
      </div>
      <p className="dialog-description">
        当前为本地开发版本。首次使用时连接 ReplayLab
        服务，之后即可从视频生成流程并交给 Agent 执行。
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          onSave(value.trim());
          onClose();
        }}
      >
        <label>
          本机连接令牌
          <input
            autoFocus
            type="password"
            autoComplete="off"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="粘贴本机服务的连接令牌"
          />
          <small>
            启动 replaylab serve 后，从终端提示的 token
            文件获取。仅保存于当前浏览器会话。
          </small>
        </label>
        <div className="settings-note">
          <ShieldCheck size={16} />
          <p>
            模型密钥在本机服务配置，界面不会读取或显示。当前版本的真实视频识别仍需配置视觉模型。
          </p>
        </div>
        <div className="dialog-footer">
          <a
            href="https://github.com/Amadeus2027/ReplayLab/blob/main/docs/quickstart.md"
            target="_blank"
            rel="noreferrer"
          >
            查看连接说明
            <ArrowUpRight size={12} />
          </a>
          <button className="primary" type="submit">
            保存连接
            <ArrowRight size={14} />
          </button>
        </div>
      </form>
    </Dialog>
  );
}
function EditStep({
  step,
  onSave,
  onClose,
}: {
  step: Step;
  onSave: (value: Step) => Promise<void>;
  onClose: () => void;
}) {
  const [value, setValue] = useState<Step>(() => structuredClone(step));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <Dialog title="调整这一步" eyebrow="EDIT STEP" onClose={onClose}>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          try {
            await onSave(value);
          } catch {
            setError("这一步的信息不完整，请检查后重试。");
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          这一步要做什么？
          <input
            required
            value={value.description}
            onChange={(event) =>
              setValue({ ...value, description: event.target.value })
            }
          />
        </label>
        {value.target && (
          <label>
            画面中的操作对象
            <input
              required
              value={value.target.description}
              onChange={(event) =>
                setValue({
                  ...value,
                  target: { ...value.target!, description: event.target.value },
                })
              }
            />
          </label>
        )}
        {value.value !== null && (
          <label>
            {value.action === "navigate" ? "打开的网址" : "操作内容"}
            <input
              value={value.value}
              onChange={(event) =>
                setValue({
                  ...value,
                  value: event.target.value,
                  verification:
                    value.verification.type === "value" &&
                    value.verification.expected === value.value
                      ? { ...value.verification, expected: event.target.value }
                      : value.verification,
                })
              }
            />
          </label>
        )}
        <label className="check-label">
          <input
            type="checkbox"
            checked={value.sensitive}
            onChange={(event) =>
              setValue({ ...value, sensitive: event.target.checked })
            }
          />
          <span>执行这一步前需要我的明确授权</span>
        </label>
        {value.target && (
          <details className="advanced-settings">
            <summary>高级：页面元素定位</summary>
            <label>
              界面上显示的文字
              <input
                required
                value={value.target.value}
                onChange={(event) =>
                  setValue({
                    ...value,
                    target: { ...value.target!, value: event.target.value },
                    verification:
                      value.verification.target?.strategy ===
                        value.target!.strategy &&
                      value.verification.target?.value === value.target!.value
                        ? {
                            ...value.verification,
                            target: {
                              ...value.verification.target!,
                              value: event.target.value,
                            },
                          }
                        : value.verification,
                  })
                }
              />
            </label>
            <p>仅在 Agent 找不到正确元素时调整。</p>
          </details>
        )}
        {error && <p className="inline-error">{error}</p>}
        <div className="dialog-footer">
          <span>执行前会保存并重新确认</span>
          <button className="primary" disabled={busy}>
            {busy ? (
              <Loader2 size={15} className="spin" />
            ) : (
              <Check size={15} />
            )}
            保存步骤
          </button>
        </div>
      </form>
    </Dialog>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
