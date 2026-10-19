import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  Check,
  ChevronRight,
  FileVideo,
  Globe,
  Link2,
  Loader2,
  Play,
  ShieldCheck,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import type { Workflow } from "./types";

export function Dialog({
  title,
  eyebrow,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  eyebrow?: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const element = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    element.current?.focus();
    return () => previous?.focus();
  }, []);
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <section
        ref={element}
        tabIndex={-1}
        className={`dialog rl-glass ${wide ? "wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => {
          if (event.key === "Escape") onClose();
          if (event.key === "Tab") {
            const items = Array.from(
              element.current?.querySelectorAll<HTMLElement>(
                "button:not(:disabled), input:not(:disabled), a[href], summary, video",
              ) || [],
            );
            const first = items[0],
              last = items[items.length - 1];
            if (
              event.shiftKey &&
              (document.activeElement === first ||
                document.activeElement === element.current)
            ) {
              event.preventDefault();
              last?.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
              event.preventDefault();
              first?.focus();
            }
          }
        }}
      >
        <header>
          {eyebrow && <span className="eyebrow">{eyebrow}</span>}
          <button
            className="icon-button close-dialog"
            aria-label="关闭"
            onClick={onClose}
          >
            <X size={18} />
          </button>
          <h2>{title}</h2>
        </header>
        {children}
      </section>
    </div>
  );
}

export function CreateDialog({
  connected,
  busy,
  onClose,
  onCreate,
  onConnect,
}: {
  connected: boolean;
  busy: boolean;
  onClose: () => void;
  onCreate: (source: string | File, url: string) => Promise<void>;
  onConnect: () => void;
}) {
  const [mode, setMode] = useState<"link" | "file">("link");
  const [source, setSource] = useState("");
  const [file, setFile] = useState<File>();
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!connected) {
      onConnect();
      return;
    }
    const input = mode === "link" ? source : file;
    if (!input) {
      setError("请先选择一段视频。");
      return;
    }
    if (file && mode === "file" && file.size > 200 * 1024 * 1024) {
      setError("请选择不超过 200 MB 的视频。");
      return;
    }
    try {
      setError("");
      await onCreate(input, url);
    } catch (error) {
      setError(String(error));
    }
  }
  return (
    <Dialog
      title="让 Agent 学会视频里的操作"
      eyebrow="NEW WORKFLOW"
      onClose={onClose}
    >
      <p className="dialog-description">
        提供一段演示，ReplayLab 会整理操作流程。确认后，交给 Agent 为你完成。
      </p>
      <form onSubmit={submit}>
        <div className="source-tabs">
          <button
            type="button"
            className={mode === "link" ? "active" : ""}
            onClick={() => setMode("link")}
          >
            <Link2 size={15} />
            视频链接
          </button>
          <button
            type="button"
            className={mode === "file" ? "active" : ""}
            onClick={() => setMode("file")}
          >
            <Upload size={15} />
            上传视频
          </button>
        </div>
        {mode === "link" ? (
          <label>
            视频链接
            <input
              autoFocus
              required
              type="url"
              placeholder="粘贴公开视频的链接"
              value={source}
              onChange={(event) => setSource(event.target.value)}
            />
          </label>
        ) : (
          <label className="upload-zone">
            <FileVideo size={28} />
            <strong>{file?.name || "点击选择一段操作视频"}</strong>
            <span>MP4、MOV、WebM 等 · 最大 200 MB</span>
            <input
              aria-label="选择操作视频"
              type="file"
              accept=".mp4,.mov,.webm,.mkv,.avi,.m4v"
              required
              onChange={(event) => setFile(event.target.files?.[0])}
            />
          </label>
        )}
        <label>
          你希望 Agent 在哪里操作？
          <div className="input-icon">
            <Globe size={16} />
            <input
              required
              type="url"
              placeholder="输入目标网站地址"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
            />
          </div>
          <small>Agent 会在独立的浏览器会话中打开这个网站。</small>
        </label>
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-footer">
          <span>
            <ShieldCheck size={13} />
            确认流程后才会执行
          </span>
          <button className="primary" disabled={busy}>
            {busy ? (
              <Loader2 size={15} className="spin" />
            ) : (
              <Sparkles size={15} />
            )}
            生成操作流程
            <ChevronRight size={15} />
          </button>
        </div>
      </form>
    </Dialog>
  );
}

export function RunDialog({
  workflow,
  busy,
  onClose,
  onRun,
}: {
  workflow: Workflow;
  busy: boolean;
  onClose: () => void;
  onRun: (
    parameters: Record<string, string>,
    sensitive: boolean,
  ) => Promise<void>;
}) {
  const [parameters, setParameters] = useState<Record<string, string>>({});
  const [authorized, setAuthorized] = useState(false);
  const [error, setError] = useState("");
  const sensitive = workflow.steps.filter((step) => step.sensitive);
  // Include placeholders even when a hand-edited workflow omitted their descriptions.
  const placeholders = [
    ...JSON.stringify({
      steps: workflow.steps,
      postconditions: workflow.postconditions,
    }).matchAll(/\$\{([a-zA-Z0-9_]+)\}/g),
  ].map((match) => match[1]);
  const keys = [
    ...new Set([...Object.keys(workflow.parameters), ...placeholders]),
  ];
  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      setError("");
      await onRun(parameters, sensitive.length > 0 && authorized);
    } catch (error) {
      setError(String(error));
    }
  }
  return (
    <Dialog
      title="接下来，交给 Agent"
      eyebrow="READY TO REPLAY"
      onClose={onClose}
    >
      <p className="dialog-description">
        Agent 将按你确认的 {workflow.steps.length} 个步骤操作，并检查最终结果。
      </p>
      <div className="destination">
        <span className="destination-icon">
          <Globe size={20} />
        </span>
        <div>
          <small>执行网站</small>
          <strong>{workflow.start_url}</strong>
        </div>
        <span className="subtle-badge">独立会话</span>
      </div>
      <form onSubmit={submit}>
        {workflow.preconditions.length > 0 && (
          <div className="requirements">
            <h3>开始前请确认</h3>
            {workflow.preconditions.map((text, index) => (
              <p key={index}>
                <Check size={14} />
                {text}
              </p>
            ))}
          </div>
        )}
        {keys.map((key) => (
          <label key={key}>
            {workflow.parameters[key] || key}
            <input
              required
              value={parameters[key] || ""}
              onChange={(event) =>
                setParameters((current) => ({
                  ...current,
                  [key]: event.target.value,
                }))
              }
              placeholder={`填写${workflow.parameters[key] || key}`}
            />
          </label>
        ))}
        {sensitive.length > 0 && (
          <div className="sensitive-note">
            <ShieldCheck size={17} />
            <div>
              <strong>以下操作需要你的授权</strong>
              {sensitive.map((step) => (
                <p key={step.id}>{step.description}</p>
              ))}
            </div>
          </div>
        )}
        <label className="check-label">
          <input
            type="checkbox"
            required
            checked={authorized}
            onChange={(event) => setAuthorized(event.target.checked)}
          />
          <span>
            我已核对操作流程与运行条件，授权 Agent 执行本次任务
            {sensitive.length ? "及上述操作" : ""}。
          </span>
        </label>
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-footer">
          <span>遇到问题会停止并通知你</span>
          <button className="primary" disabled={!authorized || busy}>
            {busy ? (
              <Loader2 size={15} className="spin" />
            ) : (
              <Play size={14} fill="currentColor" />
            )}
            确认并开始执行
          </button>
        </div>
      </form>
    </Dialog>
  );
}
