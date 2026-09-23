const SESSION_KEY = "akim-ai.session";
let pendingSession: Promise<string> | null = null;

export async function ensureSession(): Promise<string> {
  const cached =
    typeof window === "undefined"
      ? null
      : window.localStorage.getItem(SESSION_KEY);
  if (cached) return cached;
  if (!pendingSession) {
    pendingSession = (async () => {
      const response = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (!response.ok)
        throw new Error("Не удалось открыть сессию. Повторите попытку.");
      const data: { session_id: string } = await response.json();
      if (!data.session_id)
        throw new Error("Сервер не вернул идентификатор сессии.");
      if (typeof window !== "undefined")
        window.localStorage.setItem(SESSION_KEY, data.session_id);
      return data.session_id;
    })().finally(() => {
      pendingSession = null;
    });
  }
  return pendingSession;
}

export function needsSession(path: string): boolean {
  return (
    path.startsWith("sessions/") ||
    path.startsWith("scenarios") ||
    path.startsWith("ai/runs") ||
    path === "ai/config" ||
    path === "ai/usage"
  );
}
