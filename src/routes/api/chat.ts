import { createFileRoute } from "@tanstack/react-router";

const SYSTEM_PROMPT = `You are JARVIS — the AI assistant from Iron Man, now serving the user as their personal computer assistant. You are sophisticated, witty, calmly confident, and address the user as "sir" or "ma'am" sparingly.

You have access to tools that let you control the user's computer through a local helper agent running on their machine. Use these tools naturally when the user asks you to do something. NEVER fabricate tool results — only state outcomes after a tool returns.

Tools available:
- run_command(command, cwd?): Execute any shell command. This is your most powerful tool — use it for installing software (winget/brew/apt/pip/npm), launching apps, running scripts, system tasks. ALWAYS prefer this for anything actionable.
- open_path(path): Open a file/folder/app in its default handler.
- open_url(url): Open a URL in the default browser.
- list_dir(path): List files in a directory.
- search_files(root, query): Recursively search for files by name.
- read_file(path): Read a text file's contents.
- write_file(path, content): Write/overwrite a text file.
- system_info(): Get OS, CPU, RAM, disk info.

Style:
- Be concise. Brief status lines, then results.
- Use markdown code blocks for commands and outputs.
- If a command might be destructive (rm -rf, format, shutdown), confirm first.
- If the local agent is unreachable, calmly tell the user to start it.

You are running in a web UI. The browser calls the local agent at http://127.0.0.1:7337 directly after each tool call you request.`;

export const Route = createFileRoute("/api/chat")({
  server: {
    handlers: {
      POST: async ({ request }) => {
        try {
          const { messages } = (await request.json()) as { messages: any[] };
          const LOVABLE_API_KEY = process.env.LOVABLE_API_KEY;
          if (!LOVABLE_API_KEY) {
            return new Response(JSON.stringify({ error: "LOVABLE_API_KEY missing" }), {
              status: 500,
              headers: { "Content-Type": "application/json" },
            });
          }

          const tools = [
            {
              type: "function",
              function: {
                name: "run_command",
                description: "Execute a shell command on the user's local machine. Use for installing apps, running CLIs, system tasks.",
                parameters: {
                  type: "object",
                  properties: {
                    command: { type: "string", description: "The shell command to execute" },
                    cwd: { type: "string", description: "Optional working directory" },
                  },
                  required: ["command"],
                },
              },
            },
            {
              type: "function",
              function: {
                name: "open_path",
                description: "Open a file, folder, or application using the OS default handler.",
                parameters: {
                  type: "object",
                  properties: { path: { type: "string" } },
                  required: ["path"],
                },
              },
            },
            {
              type: "function",
              function: {
                name: "open_url",
                description: "Open a URL in the default browser.",
                parameters: {
                  type: "object",
                  properties: { url: { type: "string" } },
                  required: ["url"],
                },
              },
            },
            {
              type: "function",
              function: {
                name: "list_dir",
                description: "List files in a directory.",
                parameters: {
                  type: "object",
                  properties: { path: { type: "string" } },
                  required: ["path"],
                },
              },
            },
            {
              type: "function",
              function: {
                name: "search_files",
                description: "Recursively search for files by name pattern.",
                parameters: {
                  type: "object",
                  properties: {
                    root: { type: "string" },
                    query: { type: "string" },
                  },
                  required: ["root", "query"],
                },
              },
            },
            {
              type: "function",
              function: {
                name: "read_file",
                description: "Read a text file's contents.",
                parameters: {
                  type: "object",
                  properties: { path: { type: "string" } },
                  required: ["path"],
                },
              },
            },
            {
              type: "function",
              function: {
                name: "write_file",
                description: "Write or overwrite a text file.",
                parameters: {
                  type: "object",
                  properties: {
                    path: { type: "string" },
                    content: { type: "string" },
                  },
                  required: ["path", "content"],
                },
              },
            },
            {
              type: "function",
              function: {
                name: "system_info",
                description: "Get OS, CPU, RAM, and disk info from the local machine.",
                parameters: { type: "object", properties: {} },
              },
            },
          ];

          const resp = await fetch("https://ai.gateway.lovable.dev/v1/chat/completions", {
            method: "POST",
            headers: {
              Authorization: `Bearer ${LOVABLE_API_KEY}`,
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              model: "google/gemini-2.5-flash",
              messages: [{ role: "system", content: SYSTEM_PROMPT }, ...messages],
              tools,
              tool_choice: "auto",
            }),
          });

          if (!resp.ok) {
            if (resp.status === 429) {
              return new Response(JSON.stringify({ error: "Rate limit exceeded. Please try again shortly." }), {
                status: 429,
                headers: { "Content-Type": "application/json" },
              });
            }
            if (resp.status === 402) {
              return new Response(JSON.stringify({ error: "AI credits exhausted. Add funds in Settings → Workspace → Usage." }), {
                status: 402,
                headers: { "Content-Type": "application/json" },
              });
            }
            const t = await resp.text();
            console.error("AI gateway error:", resp.status, t);
            return new Response(JSON.stringify({ error: "AI gateway error" }), {
              status: 500,
              headers: { "Content-Type": "application/json" },
            });
          }

          const data = await resp.json();
          return new Response(JSON.stringify(data), {
            headers: { "Content-Type": "application/json" },
          });
        } catch (e) {
          console.error(e);
          return new Response(JSON.stringify({ error: e instanceof Error ? e.message : "Unknown" }), {
            status: 500,
            headers: { "Content-Type": "application/json" },
          });
        }
      },
    },
  },
});
