export type Target = {
  description: string;
  strategy: "role" | "label" | "text" | "placeholder";
  value: string;
  role: string | null;
};
export type Assertion = {
  type: "visible" | "text" | "url" | "value" | "checked";
  target: Target | null;
  expected: string | null;
};
export type Step = {
  id: string;
  action: "click" | "fill" | "select" | "check" | "press" | "navigate";
  description: string;
  source: { start_ms: number; end_ms: number; frame_ids: string[] };
  target: Target | null;
  value: string | null;
  confidence: number;
  status: "needs_review" | "approved";
  sensitive: boolean;
  verification: Assertion;
};
export type Workflow = {
  schema_version: "0.1";
  title: string;
  start_url: string;
  allowed_origins: string[];
  parameters: Record<string, string>;
  preconditions: string[];
  uncertainties: string[];
  steps: Step[];
  postconditions: Assertion[];
};
export type Frame = { id: string; timestamp_ms: number; path: string };
export type Report = {
  status: string;
  error?: string;
  seconds: number;
  steps: { id: string; status: string; error?: string; screenshot?: string }[];
};
export type Task = {
  id: string;
  source: string;
  status: string;
  error?: string;
  title?: string;
  step_count?: number;
  has_media?: boolean;
  workflow?: Workflow;
  evidence?: { duration_ms: number; frames: Frame[] };
  report?: Report;
  timings?: Record<string, number>;
};
