// Calls the local helper agent running on the user's machine.
const AGENT_URLS = ["http://127.0.0.1:7337", "http://localhost:7337"];

export type ToolCall = {
  id: string;
  name: string;
  args: Record<string, unknown>;
};

export async function checkAgentStatus(): Promise<boolean> {
  for (const agentUrl of AGENT_URLS) {
    try {
      const r = await fetch(`${agentUrl}/health`, { method: "GET", cache: "no-store" });
      if (r.ok) return true;
    } catch {
      // Try the next localhost variant before declaring the agent offline.
    }
  }

  return false;
}

async function fetchAgent(path: string, init: RequestInit) {
  let lastError: unknown;

  for (const agentUrl of AGENT_URLS) {
    try {
      return await fetch(`${agentUrl}${path}`, init);
    } catch (e) {
      lastError = e;
    }
  }

  throw lastError;
}

export async function executeTool(name: string, args: Record<string, unknown>): Promise<string> {
  try {
    const r = await fetchAgent(`/tool/${name}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args),
    });
    const text = await r.text();
    if (!r.ok) return `ERROR (${r.status}): ${text}`;
    return text;
  } catch (e) {
    return `ERROR: Local JARVIS agent unreachable at ${AGENT_URLS.join(" or ")}. Make sure it's running. (${
      e instanceof Error ? e.message : String(e)
    })`;
  }
}
