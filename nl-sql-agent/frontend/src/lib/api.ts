const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface AskResponse {
  answer: string;
  sql_used: string | null;
  row_count: number | null;
  session_id: string;
}

export async function askAgent(
  question: string,
  sessionId?: string
): Promise<AskResponse> {
  const res = await fetch(`${API_BASE}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, session_id: sessionId ?? null }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Request failed");
  }
  return res.json();
}
