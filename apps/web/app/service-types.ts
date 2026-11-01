export type Project = { id: string; name: string };
export type Service = { id: string; project_id: string; name: string; environment: string; probe_name: "demo" | null };
export type Token = { id: string; service_id: string; prefix: string; created_at: string; revoked_at: string | null };
export type CreatedToken = Token & { token: string };
export type Connection = {
  service_id: string; project_id: string; status: "connected" | "waiting" | "stale" | "unavailable";
  checked_at: string; last_seen_at: string | null; detail: string;
};
