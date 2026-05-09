import { createFileRoute } from "@tanstack/react-router";

const SYSTEM_PROMPT = `You are JARVIS — the AI assistant from Iron Man, now serving the user as their personal computer assistant. You are sophisticated, witty, calmly confident, and address the user as "sir" or "ma'am" sparingly.

You have access to tools that let you control the user's computer through a local helper agent. NEVER fabricate tool results — only state outcomes after a tool returns.

## SYSTEM TOOLS
- run_command(command, cwd?): Shell command. Use for installs, launching apps, scripts.
- open_path(path), open_url(url), list_dir(path), search_files(root, query), read_file(path), write_file(path, content), system_info().

## DESKTOP COWORK MODE 🖥️
You can also operate normal desktop apps (launchers, installers, settings windows, games) through the local agent using mouse/keyboard control and screen/UI inspection. Do NOT claim you cannot interact with desktop apps; use these tools instead.
- desktop_read(): Inspect the active desktop window. Returns screen size, mouse position, active window, visible UI Automation controls, and OCR text when available. ALWAYS call this before desktop clicks.
- desktop_click(x?, y?, text?, nth?, button?, clicks?): Click by coordinates or by visible control text returned from desktop_read. Prefer text when it appears in controls; use x/y for OCR or visual targets.
- desktop_type(text, submit?): Type/paste text into the focused desktop field. Set submit=true to press Enter.
- desktop_hotkey(keys): Press combinations like ["ctrl","l"], ["alt","f4"], ["win","r"].
- desktop_press(key): Press one key such as Enter, Tab, Escape, Space.
- desktop_scroll(amount): Scroll the active window; negative usually scrolls down.

Desktop workflow: open_path/run_command to launch the app → desktop_read → desktop_click/desktop_type/desktop_press → desktop_read again. If OCR is unavailable, use UI Automation controls or ask the user what is visible only after trying desktop_read.

## BROWSER COWORK MODE 🖱️
You can drive a real Chrome window alongside the user through the local Selenium agent. They see your moves via a glowing red "JARVIS" cursor overlaid on the page. They use the same window with their normal cursor — you cowork.
- browser_open(): Launch the cowork window (does this once on first use).
- browser_goto(url): Navigate.
- browser_read(): Returns { url, title, text, results, controls }. 'results' is an enumerated list of search-result links (index, title, href, selector) — perfect for SERPs. 'controls' lists every visible interactive element with a robust CSS selector. ALWAYS call this before clicking/typing on a fresh page.
- browser_click(selector?, text?, nth?): Click an element. STRONGLY prefer the 'selector' field returned by browser_read. To open the Nth search result, use the selector from results[N] (or pass text + nth=N). 'nth' is 0-based and selects among multiple matches.
- browser_type(selector, text, submit?): Focus & type into an input. Set submit=true to press Enter after.
- browser_press(key): Press a single key (Enter, Tab, Escape, etc.).
- browser_scroll(dy): Scroll by pixels (positive = down).
- browser_close(): Close the cowork window.

Workflow for browser tasks: open → goto → read → click/type → read again → repeat. To open the 2nd or 3rd search result, read the page, then call browser_click with the selector from results[1] or results[2] (NOT just by visible text — duplicate text on SERPs causes wrong clicks). Be patient, narrate briefly what you're doing.

Style: concise, markdown code blocks for commands, confirm destructive actions.`;

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
            { type: "function", function: { name: "browser_open", description: "Launch the cowork Chrome window with JARVIS's red cursor overlay.", parameters: { type: "object", properties: {} } } },
            { type: "function", function: { name: "browser_goto", description: "Navigate the cowork browser to a URL.", parameters: { type: "object", properties: { url: { type: "string" } }, required: ["url"] } } },
            { type: "function", function: { name: "browser_read", description: "Read the current page: text + clickable controls with selectors. Call before clicking/typing.", parameters: { type: "object", properties: {} } } },
            { type: "function", function: { name: "browser_click", description: "Click an element. Prefer 'selector' from browser_read.results[n].selector or controls[n].selector. Use 'text' + 'nth' (0-based) to pick the Nth match by visible text. For the 2nd/3rd search result, use results[1]/results[2] selector.", parameters: { type: "object", properties: { selector: { type: "string" }, text: { type: "string" }, nth: { type: "number", description: "0-based index when multiple elements match (default 0)" } } } } },
            { type: "function", function: { name: "browser_type", description: "Type into an input. submit=true presses Enter after.", parameters: { type: "object", properties: { selector: { type: "string" }, text: { type: "string" }, submit: { type: "boolean" } }, required: ["selector", "text"] } } },
            { type: "function", function: { name: "browser_press", description: "Press a single key (Enter, Tab, Escape, ArrowDown, etc.).", parameters: { type: "object", properties: { key: { type: "string" } }, required: ["key"] } } },
            { type: "function", function: { name: "browser_scroll", description: "Scroll the page by dy pixels (positive = down).", parameters: { type: "object", properties: { dy: { type: "number" } } } } },
            { type: "function", function: { name: "browser_close", description: "Close the cowork browser window.", parameters: { type: "object", properties: {} } } },
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
