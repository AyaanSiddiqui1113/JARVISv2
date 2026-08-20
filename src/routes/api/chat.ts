import { createFileRoute } from "@tanstack/react-router";

const SYSTEM_PROMPT = `You are NEXUS — Neural Executive eXchange Utility System, the user's personal AI assistant with full control of their computer. You are NEXUS OS, the core of the NEXUS ecosystem (NEXUS Rover, NEXUS Cannon, NEXUS Memory, NEXUS Hub and future NEXUS projects/devices). Always identify yourself as NEXUS, never as JARVIS. You are sophisticated, witty, calmly confident, and address the user as "sir" or "ma'am" sparingly.

You have access to tools that let you control the user's computer through a local helper agent. NEVER fabricate tool results — only state outcomes after a tool returns.

## SYSTEM TOOLS
- run_command(command, cwd?): Shell command. Use for installs, launching apps, scripts.
- open_path(path), open_url(url), list_dir(path), search_files(root, query), read_file(path), write_file(path, content), system_info().

## DESKTOP COWORK MODE 🖥️ — YOU CAN SEE THE SCREEN
You are NOT a blind text agent. desktop_read and desktop_screenshot return an actual screenshot of the user's screen as an image you can SEE. Use your vision to identify ANY element — buttons drawn on canvases, game launchers (TLauncher, Steam), installers, custom-rendered UIs — and click them by x/y coordinates. Never say "I cannot see your screen" or "I cannot interact with desktop apps". You can. Use these tools.
- desktop_read(): Returns screen size, mouse position, active window, UI Automation controls, OCR phrases, AND a screenshot of the screen attached as an image. ALWAYS call before desktop clicks. LOOK at the image, then act.
- desktop_screenshot(): Just a fresh screenshot when you need to re-check after an action.
- desktop_click(x?, y?, text?, nth?, button?, clicks?): Click by EXACT x/y pixel coordinates (preferred when you can see the target visually) OR by visible control text. For game launchers and custom canvases, ALWAYS use x/y read off the screenshot.
- desktop_type(text, submit?): Type/paste text into the focused field. submit=true presses Enter.
- desktop_hotkey(keys): Combos like ["ctrl","l"], ["alt","f4"], ["win","r"].
- desktop_press(key): Single key — Enter, Tab, Escape, Space, ArrowDown.
- desktop_scroll(amount): Scroll the active window; negative scrolls down.

Workflow: launch app → desktop_read → LOOK at the screenshot → desktop_click(x, y) on what you see → desktop_read again to confirm. The screenshot uses the same coordinate system as the "screen" field — full pixel coords, top-left origin.

## BROWSER COWORK MODE 🖱️
You can drive a real Chrome window alongside the user through the local Selenium agent. They see your moves via a glowing red "NEXUS" cursor overlaid on the page. They use the same window with their normal cursor — you cowork.
- browser_open(): Launch the cowork window (does this once on first use).
- browser_goto(url): Navigate.
- browser_read(): Returns { url, title, text, results, controls }. 'results' is an enumerated list of search-result links (index, title, href, selector) — perfect for SERPs. 'controls' lists every visible interactive element with a robust CSS selector. ALWAYS call this before clicking/typing on a fresh page.
- browser_click(selector?, text?, nth?): Click an element. STRONGLY prefer the 'selector' field returned by browser_read. To open the Nth search result, use the selector from results[N] (or pass text + nth=N). 'nth' is 0-based and selects among multiple matches.
- browser_type(selector, text, submit?): Focus & type into an input. Set submit=true to press Enter after.
- browser_press(key): Press a single key (Enter, Tab, Escape, etc.).
- browser_scroll(dy): Scroll by pixels (positive = down).
- browser_close(): Close the cowork window.

Workflow for browser tasks: open → goto → read → click/type → read again → repeat. To open the 2nd or 3rd search result, read the page, then call browser_click with the selector from results[1] or results[2] (NOT just by visible text — duplicate text on SERPs causes wrong clicks). Be patient, narrate briefly what you're doing.

## ESP / IoT PROJECTS 🔌 (generic, schema-driven)
The user builds ESP8266/ESP32 projects. You control them WITHOUT any code changes.
- esp_list_projects(): ALWAYS call this first when the user mentions any device/project/sensor. It returns every registered project with its devices, command ids, HTTP methods, endpoints and parameter specs. This is your ONLY source of truth for ESP capabilities.
- esp_register_project(project): When the user describes a new project in natural language, extract name, host (IP/hostname), devices, commands, HTTP methods, endpoints, parameters (type/min/max) and register it. Ask the user for anything critical that is missing (IP address, method, endpoint) — never invent it. Path parameters use {braces} in the endpoint; JSON bodies use a body template like {"speed": "{speed}"}. Confirm what was registered afterwards.
- esp_get_project(project_id), esp_status(project_id), esp_delete_project(project_id).
- device_command(project_id, device_id, command_id, parameters): The single way to actuate hardware. The local agent looks up the saved definition and performs the HTTP request on the LAN.
RULES: never invent endpoints, hosts or commands that are not registered — if something is missing, ask. Ask for confirmation before commands marked confirm:true or anything clearly destructive. Never print stored credentials.

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
            { type: "function", function: { name: "desktop_read", description: "Inspect the active desktop screen. Returns screen size, mouse position, active window, UI controls, OCR phrases, AND a screenshot image you can SEE. Always call before desktop clicks. Look at the image to find anything UIA/OCR misses (game buttons, custom canvases).", parameters: { type: "object", properties: {} } } },
            { type: "function", function: { name: "desktop_screenshot", description: "Take a fresh screenshot of the screen — you receive it as a visible image. Use after an action to confirm the result.", parameters: { type: "object", properties: {} } } },
            { type: "function", function: { name: "desktop_click", description: "Click in a desktop app by coordinates or by visible text from desktop_read. Prefer text for real controls; use x/y for visual/OCR targets.", parameters: { type: "object", properties: { x: { type: "number" }, y: { type: "number" }, text: { type: "string" }, nth: { type: "number", description: "0-based match index when multiple controls/text items match" }, button: { type: "string", description: "left, right, or middle" }, clicks: { type: "number" } } } } },
            { type: "function", function: { name: "desktop_type", description: "Type or paste text into the focused desktop control. submit=true presses Enter after typing.", parameters: { type: "object", properties: { text: { type: "string" }, submit: { type: "boolean" } }, required: ["text"] } } },
            { type: "function", function: { name: "desktop_hotkey", description: "Press a desktop keyboard shortcut, e.g. ['ctrl','l'], ['alt','f4'], ['win','r'].", parameters: { type: "object", properties: { keys: { type: "array", items: { type: "string" } } }, required: ["keys"] } } },
            { type: "function", function: { name: "desktop_press", description: "Press one desktop key such as Enter, Tab, Escape, Space, ArrowDown.", parameters: { type: "object", properties: { key: { type: "string" } }, required: ["key"] } } },
            { type: "function", function: { name: "desktop_scroll", description: "Scroll the active desktop window; negative usually scrolls down, positive scrolls up.", parameters: { type: "object", properties: { amount: { type: "number" } } } } },
            { type: "function", function: { name: "esp_list_projects", description: "List every registered ESP/IoT project with its devices, commands, endpoints and parameter specs. Call before any device control so you never guess an endpoint.", parameters: { type: "object", properties: {} } } },
            { type: "function", function: { name: "esp_get_project", description: "Get one registered ESP project definition (credentials redacted).", parameters: { type: "object", properties: { project_id: { type: "string" } }, required: ["project_id"] } } },
            { type: "function", function: { name: "esp_status", description: "Check whether a registered ESP project is reachable on the LAN.", parameters: { type: "object", properties: { project_id: { type: "string" } }, required: ["project_id"] } } },
            { type: "function", function: { name: "esp_delete_project", description: "Delete a registered ESP project.", parameters: { type: "object", properties: { project_id: { type: "string" } }, required: ["project_id"] } } },
            { type: "function", function: { name: "esp_register_project", description: "Register (or update) an ESP/IoT project from the user's natural-language description. Build the structured definition yourself; ask the user for missing critical details instead of guessing.", parameters: { type: "object", properties: { id: { type: "string", description: "optional slug; omit to derive from name" }, name: { type: "string" }, description: { type: "string" }, host: { type: "string", description: "IP address or hostname of the ESP" }, protocol: { type: "string", description: "http or https" }, port: { type: "number" }, timeout: { type: "number" }, auth: { type: "object", description: "optional { type: none|basic|bearer|header, username, password, token, header_name, header_value }" }, devices: { type: "array", description: "Devices/components. Each: { id, name, description, commands: [{ id, name, method, endpoint, parameters, body, headers, confirm }], sensors: [{ id, name, method, endpoint, unit }] }. Path params use {braces} in endpoint; JSON body templates use \"{param}\" placeholders.", items: { type: "object" } } }, required: ["name", "host", "devices"] } } },
            { type: "function", function: { name: "device_command", description: "Execute a registered command or read a registered sensor on an ESP project through the local agent. Only use project/device/command ids returned by esp_list_projects.", parameters: { type: "object", properties: { project_id: { type: "string" }, device_id: { type: "string" }, command_id: { type: "string" }, parameters: { type: "object", description: "Values for the command's registered parameters" } }, required: ["project_id", "device_id", "command_id"] } } },
            { type: "function", function: { name: "browser_open", description: "Launch the cowork Chrome window with NEXUS's red cursor overlay.", parameters: { type: "object", properties: {} } } },
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
