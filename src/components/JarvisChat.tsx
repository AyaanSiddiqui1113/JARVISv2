import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { ArcReactor } from "@/components/ArcReactor";
import { checkAgentStatus, executeTool } from "@/lib/jarvis-agent";
import { Send, Power, Terminal, Cpu, Wifi, WifiOff } from "lucide-react";

type ToolCallRecord = { name: string; args: any; result: string };
type Msg = {
  role: "user" | "assistant" | "tool" | "system";
  content: string;
  tool_calls?: any[];
  tool_call_id?: string;
  display?: { tools?: ToolCallRecord[] };
};

const MAX_TOOL_LOOPS = 8;

export function JarvisChat() {
  const [messages, setMessages] = useState<Msg[]>([
    {
      role: "assistant",
      content:
        "**Online.** All systems nominal, sir. Local agent link initializing — say the word and I'll get to work.",
    },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [agentOnline, setAgentOnline] = useState(false);
  const [thinking, setThinking] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const tick = async () => setAgentOnline(await checkAgentStatus());
    tick();
    const i = setInterval(tick, 5000);
    return () => clearInterval(i);
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, thinking]);

  async function callModel(history: Msg[]): Promise<any> {
    const apiMsgs = history
      .filter((m) => m.role !== "system")
      .map((m) => {
        const base: any = { role: m.role, content: m.content };
        if (m.tool_calls) base.tool_calls = m.tool_calls;
        if (m.tool_call_id) base.tool_call_id = m.tool_call_id;
        return base;
      });
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: apiMsgs }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ error: "Unknown" }));
      throw new Error(err.error || `HTTP ${r.status}`);
    }
    return r.json();
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);

    let history: Msg[] = [...messages, { role: "user", content: text }];
    setMessages(history);

    try {
      for (let i = 0; i < MAX_TOOL_LOOPS; i++) {
        setThinking("Processing...");
        const data = await callModel(history);
        const choice = data.choices?.[0];
        const msg = choice?.message;
        if (!msg) throw new Error("No response from model");

        const toolCalls = msg.tool_calls;
        if (toolCalls && toolCalls.length > 0) {
          const toolRecords: ToolCallRecord[] = [];
          history = [
            ...history,
            { role: "assistant", content: msg.content || "", tool_calls: toolCalls },
          ];
          setMessages([
            ...history,
            { role: "assistant", content: "*Executing tools...*", display: { tools: [] } },
          ]);

          for (const tc of toolCalls) {
            const fname = tc.function.name;
            let args: any = {};
            try { args = JSON.parse(tc.function.arguments || "{}"); } catch {}
            setThinking(`Running: ${fname}`);
            const result = await executeTool(fname, args);

            // If the tool returned a screenshot, strip the giant base64 from the
            // text result the AI sees, but ALSO push it as a vision message so
            // the model can literally see the screen like a human.
            let textResult = result;
            let screenshotB64: string | null = null;
            let screenshotMime = "image/jpeg";
            try {
              const parsed = JSON.parse(result);
              if (parsed && typeof parsed === "object" && parsed.screenshot_b64) {
                screenshotB64 = parsed.screenshot_b64;
                screenshotMime = parsed.screenshot_mime || "image/jpeg";
                const { screenshot_b64: _drop, ...rest } = parsed;
                textResult = JSON.stringify({ ...rest, screenshot: "[attached as image to next message]" });
              }
            } catch {}

            toolRecords.push({ name: fname, args, result: textResult });
            history = [
              ...history,
              { role: "tool", tool_call_id: tc.id, content: textResult },
            ];
            if (screenshotB64) {
              history = [
                ...history,
                {
                  role: "user",
                  content: [
                    { type: "text", text: `Screen capture from ${fname}. Identify targets visually and click by x/y coordinates from the screen size in the previous tool result.` },
                    { type: "image_url", image_url: { url: `data:${screenshotMime};base64,${screenshotB64}` } },
                  ] as any,
                },
              ];
            }
          }
          // Show tools in chat
          setMessages([
            ...history.slice(0, -toolCalls.length - 1),
            history[history.length - toolCalls.length - 1],
            ...history.slice(-toolCalls.length),
            { role: "assistant", content: "", display: { tools: toolRecords } },
          ]);
          continue;
        }

        // Final assistant message
        history = [...history, { role: "assistant", content: msg.content || "" }];
        setMessages(history);
        break;
      }
    } catch (e) {
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: `**System error:** ${e instanceof Error ? e.message : String(e)}`,
        },
      ]);
    } finally {
      setThinking("");
      setBusy(false);
    }
  }

  return (
    <div className="flex h-screen flex-col">
      {/* Top HUD */}
      <header className="panel flex items-center justify-between px-6 py-3 rounded-none border-x-0 border-t-0">
        <div className="flex items-center gap-4">
          <ArcReactor active={busy} size={48} />
          <div>
            <h1 className="font-display text-xl text-glow text-primary">J.A.R.V.I.S.</h1>
            <p className="text-xs text-muted-foreground tracking-widest">
              JUST A RATHER VERY INTELLIGENT SYSTEM
            </p>
          </div>
        </div>
        <div className="flex items-center gap-6 text-xs font-mono">
          <Stat icon={<Cpu size={14} />} label="AI" value="ONLINE" ok />
          <Stat
            icon={agentOnline ? <Wifi size={14} /> : <WifiOff size={14} />}
            label="LOCAL AGENT"
            value={agentOnline ? "LINKED" : "OFFLINE"}
            ok={agentOnline}
          />
          <Stat icon={<Power size={14} />} label="STATUS" value={busy ? "WORKING" : "READY"} ok />
        </div>
      </header>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto max-w-4xl space-y-4">
          {messages.map((m, i) => (
            <MessageBubble key={i} msg={m} />
          ))}
          {thinking && (
            <div className="flex items-center gap-2 text-primary text-sm">
              <span className="animate-blink">●</span>
              <span className="text-glow">{thinking}</span>
            </div>
          )}
        </div>
      </div>

      {/* Composer */}
      <footer className="panel rounded-none border-x-0 border-b-0 px-6 py-4">
        <div className="mx-auto max-w-4xl flex gap-3 items-end">
          <div className="flex-1 relative">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder={agentOnline ? "Issue a command, sir..." : "Local agent offline — chat will work, but I can't act on your machine yet."}
              rows={2}
              className="w-full resize-none rounded-md bg-input/60 border border-border px-4 py-3 font-mono text-sm text-foreground placeholder:text-muted-foreground/70 focus:outline-none focus:border-primary focus:shadow-[0_0_0_3px_var(--jarvis-glow-soft)] transition"
            />
          </div>
          <button
            onClick={send}
            disabled={busy || !input.trim()}
            className="h-12 px-5 rounded-md bg-primary text-primary-foreground font-display tracking-wider text-sm hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed glow-ring transition"
          >
            <Send size={16} className="inline mr-2" />
            SEND
          </button>
        </div>
      </footer>
    </div>
  );
}

function Stat({ icon, label, value, ok }: { icon: React.ReactNode; label: string; value: string; ok?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <span className={ok ? "text-primary" : "text-destructive"}>{icon}</span>
      <span className="text-muted-foreground">{label}</span>
      <span className={`tracking-wider ${ok ? "text-primary text-glow" : "text-destructive"}`}>
        {value}
      </span>
    </div>
  );
}

function MessageBubble({ msg }: { msg: Msg }) {
  if (msg.role === "tool") return null; // shown via display.tools instead
  if (msg.role === "assistant" && msg.display?.tools) {
    return (
      <div className="space-y-2">
        {msg.display.tools.map((t, idx) => (
          <ToolCard key={idx} record={t} />
        ))}
      </div>
    );
  }

  const isUser = msg.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-lg px-4 py-3 ${
          isUser
            ? "bg-primary/15 border border-primary/40 text-foreground"
            : "panel text-foreground"
        }`}
      >
        <div className="text-[10px] font-display tracking-widest mb-1 text-primary/70">
          {isUser ? "USER" : "JARVIS"}
        </div>
        <div className="prose prose-sm prose-invert max-w-none [&_*]:text-foreground [&_code]:text-accent [&_a]:text-primary">
          <ReactMarkdown>{msg.content || "*…*"}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
}

function ToolCard({ record }: { record: ToolCallRecord }) {
  const failed = record.result.startsWith("ERROR");
  return (
    <details className="panel rounded-md text-xs font-mono group" open>
      <summary className="cursor-pointer px-3 py-2 flex items-center gap-2 list-none">
        <Terminal size={14} className={failed ? "text-destructive" : "text-accent"} />
        <span className="text-accent text-glow">{record.name}</span>
        <span className="text-muted-foreground truncate flex-1">
          {JSON.stringify(record.args)}
        </span>
        <span className={failed ? "text-destructive" : "text-primary"}>
          {failed ? "✕" : "✓"}
        </span>
      </summary>
      <pre className="px-3 pb-3 pt-0 whitespace-pre-wrap break-words text-muted-foreground max-h-64 overflow-auto">
{record.result}
      </pre>
    </details>
  );
}
