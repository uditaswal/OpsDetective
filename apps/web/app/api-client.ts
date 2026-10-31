export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

export function csrfToken(): string {
  const item = document.cookie.split("; ").find((part) => part.startsWith("csrf_token="));
  return item ? decodeURIComponent(item.split("=")[1]) : "";
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    credentials: "same-origin", cache: "no-store", ...init,
    signal: init?.signal ?? AbortSignal.timeout(10000),
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`, response.status);
  }
  return response.json();
}
