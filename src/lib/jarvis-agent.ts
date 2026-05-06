// Calls the local helper agent running on the user's machine.
const AGENT_URL = "http://127.0.0.1:7337";

export type ToolCall = {
  id: string;
  name: string;
  args: Record<string, unknown>;
};

export async function checkAgentStatus(): Promise<boolean> {
  try {
    const r = await fetch(`${AGENT_URL}/health`, { method: "GET" });
    return r.ok;
  } catch {
    return false;
  }
}

export async function executeTool(name: string, args: Record<string, unknown>): Promise<string> {
  try {
    const r = await fetch(`${AGENT_URL}/tool/${name}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args),
    });
    const text = await r.text();
    if (!r.ok) return `ERROR (${r.status}): ${text}`;
    return text;
  } catch (e) {
    return `ERROR: Local JARVIS agent unreachable at ${AGENT_URL}. Make sure it's running. (${
      e instanceof Error ? e.message : String(e)
    })`;
  }
}
