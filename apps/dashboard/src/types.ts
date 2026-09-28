export type Session = {
  user: { email: string };
  account: { id: string; name: string };
  csrf_token: string;
};
export type Application = { id: string; name: string; slug: string };
export type Key = {
  id: string;
  name: string;
  prefix: string;
  revoked_at: string | null;
};
export type Cost = {
  amount: string;
  currency: string;
  cost_basis: string;
  partial: boolean;
  cost_per_accepted_result: string | null;
};
export type Step = {
  step_id: string;
  name: string;
  kind?: string;
  started_at?: string | null;
  attempt_number: number;
  status: string;
  depth: number;
  duration_ms: number | null;
  costs: Cost[];
};
export type Workflow = {
  workflow_id: string;
  status: string;
  accepted: boolean | null;
  duration_ms?: number | null;
  usage_events?: number;
  unknown_cost_events?: number;
  steps: Step[];
  costs: Cost[];
  usage: {
    unit: string;
    value: string;
    provider: string;
    model_or_service: string;
  }[];
};
export type Cohort = {
  application_id: string;
  environment: string;
  configuration_id: string;
  summary: Record<string, number>;
  costs: Cost[];
  workflows: Workflow[];
  findings: { code: string; message: string; evidence: string[] }[];
};
export type Capabilities = {
  mode: string;
  registration_enabled: boolean;
  demo_enabled: boolean;
  dashboard_builder_enabled?: boolean;
  metrics_window_days: number;
  metrics_max_events: number;
};
export type Metrics = {
  scope?: {
    since: string;
    until: string;
    limit: number;
    truncated: boolean;
    returned_events: number;
    max_bytes?: number;
    input_bytes?: number;
    truncation_reasons?: string[];
  };
  report: {
    cohorts: Cohort[];
    input: { valid_events: number };
    assumptions: string[];
  };
  loaded_at: string;
};
