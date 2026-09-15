// UI pure-logic tests, run with: node --test tests/ui.test.mjs
//
// The inline <script> in ui/index.html is an IIFE that immediately queries a
// full DOM and wires up fetch/event handlers. Rather than stub the entire
// document (which would fight back), we extract ONLY the pure functions and
// the short-name regex literal from the script text and evaluate them here.
// index.html itself is not modified for testability.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const html = readFileSync(new URL("../ui/index.html", import.meta.url), "utf8");
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (!scriptMatch) {
  throw new Error("could not find an inline <script> in ui/index.html");
}
const script = scriptMatch[1];

// Pull a top-level `function name(...) { ... }` out of the IIFE by matching up
// to the first closing brace at the function's own two-space indentation.
function extractFunction(name) {
  const re = new RegExp(`function ${name}\\([^)]*\\) \\{[\\s\\S]*?\\n  \\}`);
  const match = script.match(re);
  if (!match) {
    throw new Error(`could not extract function ${name}() from ui/index.html`);
  }
  return match[0];
}

const functionNames = ["gdbBase", "shortIri", "friendlyLabel", "formatSparql"];
const functions = functionNames.map(extractFunction).join("\n\n");

// SHORT_NAME_RE is a `var` inside renderMarkdown; lift the literal verbatim.
const reLine = script
  .split("\n")
  .find((line) => line.includes("var SHORT_NAME_RE ="));
if (!reLine) {
  throw new Error("could not find SHORT_NAME_RE in ui/index.html");
}
const reLiteral = reLine.match(/var SHORT_NAME_RE = (.*);/)[1];

// `window` is the only host object the extracted functions touch.
const windowStub = { location: { hostname: "myhost" } };
const factory = new Function(
  "window",
  `${functions}

var SHORT_NAME_RE = ${reLiteral};
return { gdbBase: gdbBase, shortIri: shortIri, friendlyLabel: friendlyLabel, formatSparql: formatSparql, SHORT_NAME_RE: SHORT_NAME_RE };`
);
const ui = factory(windowStub);

test("friendlyLabel renders a resource IRI as a human label", () => {
  assert.equal(
    ui.friendlyLabel("https://example.org/sales-kg/resource/Deal_D007"),
    "Deal D007"
  );
});

test("formatSparql turns a single-line query into multiple lines", () => {
  const single =
    "PREFIX crm: <https://example.org/crm/> SELECT ?s WHERE { ?s crm:name ?o } LIMIT 5";
  const out = ui.formatSparql(single);

  assert.ok(out.includes("\n"), `expected a newline in: ${out}`);
  assert.ok(out.split("\n").length > 3, `expected several lines in: ${out}`);
  assert.match(out, /^PREFIX crm:/m);
  assert.match(out, /^SELECT/m);
  assert.match(out, /^WHERE/m);
});

test("gdbBase rewrites the compose host to the page hostname", () => {
  assert.equal(ui.gdbBase("http://graphdb:7200"), "http://myhost:7200");
});

test("short-name regex matches a bare short name", () => {
  const re = new RegExp(ui.SHORT_NAME_RE.source);
  assert.equal(re.test("Transcript_T007"), true);
});

test("short-name regex does not match inside a full IRI", () => {
  const re = new RegExp(ui.SHORT_NAME_RE.source);
  assert.equal(
    re.test("https://example.org/sales-kg/resource/Transcript_T007"),
    false
  );
});
