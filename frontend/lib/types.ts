export type ServiceStatus = "unknown" | "healthy" | "degraded" | "unhealthy";

export interface Membership {
  organization_id: number;
  organization_name: string;
  role: string;
}
export interface Me {
  id: number;
  email: string;
  full_name: string;
  memberships: Membership[];
}
export interface Application {
  id: number;
  organization_id: number;
  name: string;
  description: string | null;
}
export interface Environment {
  id: number;
  application_id: number;
  name: string;
  env_type: string;
  chaos_enabled: boolean;
}
export interface ServiceSummary {
  service_id: number;
  name: string;
  is_active: boolean;
  up: boolean | null;
  request_rate: number | null;
  error_rate: number | null;
  p95_latency_seconds: number | null;
  computed_status: ServiceStatus;
  stored_status: ServiceStatus;
}
export interface EnvironmentSummary {
  environment_id: number;
  environment: string;
  services: ServiceSummary[];
}
export type Point = [number, number | null];
export interface ServiceMetrics {
  service_id: number;
  service_name: string;
  environment: string;
  minutes: number;
  step_seconds: number;
  series: Record<string, Point[]>;
}
export interface IncidentSummary {
  id: number;
  environment_id: number;
  service_id: number | null;
  title: string;
  severity: string;
  category: string;
  status: string;
  assigned_user_id: number | null;
  started_at: string;
  created_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
}
export interface AnomalyRecord {
  id: number;
  service_id: number;
  metric_name: string;
  observed_value: number;
  baseline_value: number;
  severity: string;
  ongoing: boolean;
  started_at: string;
  explanation: string;
}
export interface IncidentEvent {
  id: number;
  event_type: string;
  message: string;
  created_at: string;
}
export interface IncidentComment {
  id: number;
  user_id: number | null;
  body: string;
  created_at: string;
}
export interface IncidentDetail extends IncidentSummary {
  description: string;
  root_cause_hypothesis: string | null;
  recommended_actions: string[];
  resolution_notes: string | null;
  anomalies: AnomalyRecord[];
  events: IncidentEvent[];
  comments: IncidentComment[];
}
export interface IncidentStats {
  total: number;
  open: number;
  by_status: Record<string, number>;
  by_severity: Record<string, number>;
  mttd_seconds: number | null;
  mttr_seconds: number | null;
  per_day: Record<string, number>;
}
export interface DetectionReport {
  results: { service: string; outcome: string; detail: string }[];
  incident_ids: number[];
}

export interface Remediation {
  id: number;
  incident_id: number;
  service_name: string;
  container: string;
  action_type: string;
  status: string;
  reason: string;
  expected_impact: string;
  created_at: string;
  result_message: string | null;
  verified: boolean | null;
  verification: string | null;
}