/**
 * OpenCode trace-log plugin.
 *
 * Appends one JSON line per completed tool call to `<cwd>/logs/tool_calls.jsonl`
 * so the Python agent harness can rebuild a single session's retrieval trace.
 *
 * Hook contract (verified against .opencode/node_modules/@opencode-ai/plugin
 * 1.1.48 types and the installed opencode 1.1.48 runtime):
 *   - "tool.execute.before" input  = { tool, sessionID, callID }
 *                           output = { args }               <- args live here
 *   - "tool.execute.after"  input  = { tool, sessionID, callID }
 *                           output = { title, output, metadata }
 *
 * The after hook receives no args, so the before hook stashes the truncated
 * args JSON keyed by callID and the after hook writes the line.
 *
 * opencode discovers this automatically from `.opencode/plugin|plugins/*.{ts,js}`
 * and/or loads it from the opencode.json `"plugin"` array as a `file://` URL.
 *
 * node builtins only; no npm deps.
 */
import { appendFileSync, mkdirSync } from "fs";
import { join } from "path";

const LIMIT = 2000;
const OUTPUT_LIMIT = 20000;

/** Render any value as a JSON-ish string capped at `limit` characters. */
function truncate(value: unknown, limit: number = LIMIT): string {
  let text: string;
  if (typeof value === "string") {
    text = value;
  } else {
    try {
      text = JSON.stringify(value);
    } catch {
      text = String(value);
    }
  }
  if (typeof text !== "string") return "";
  return text.length > limit ? text.slice(0, limit) : text;
}

export const TraceLogPlugin = async (ctx: any) => {
  // callID -> truncated args JSON captured by the before hook.
  const pendingArgs = new Map<string, string>();
  const logDir = join(process.cwd(), "logs");
  const logFile = join(logDir, "tool_calls.jsonl");

  return {
    "tool.execute.before": async (input: any, output: any) => {
      try {
        const callID = input?.callID;
        if (typeof callID === "string" && callID) {
          pendingArgs.set(callID, truncate(output?.args ?? {}));
          if (pendingArgs.size > 512) {
            const oldest = pendingArgs.keys().next().value;
            if (typeof oldest === "string") pendingArgs.delete(oldest);
          }
        }
      } catch {
        // Never let tracing break a tool call.
      }
    },

    "tool.execute.after": async (input: any, output: any) => {
      try {
        const callID = input?.callID;
        const cached = typeof callID === "string" ? pendingArgs.get(callID) : undefined;
        const args = cached ?? truncate(input?.args ?? {});
        if (typeof callID === "string") pendingArgs.delete(callID);

        // Custom tools expose output.output; MCP tools hand the raw
        // CallToolResult ({content: [...]}) straight to this hook, so fall back
        // to serializing the whole result for those.
        const outputText = truncate(output?.output ?? output ?? "", OUTPUT_LIMIT);

        const record = {
          ts: new Date().toISOString(),
          sessionID: input?.sessionID ?? "",
          callID: callID ?? "",
          tool: input?.tool ?? "",
          args,
          output: outputText,
          title: typeof output?.title === "string" ? output.title : "",
        };

        mkdirSync(logDir, { recursive: true });
        appendFileSync(logFile, JSON.stringify(record) + "\n");
      } catch {
        // Never let tracing break a tool call.
      }
    },
  };
};
