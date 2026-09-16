// Lists Playwright trace zips under test-results/ and lets you pick one to open.
//
// Playwright's `show-trace` requires an explicit path, which is awkward because
// trace filenames are generated per test and retry. This helper lists every
// *.zip under test-results/ (recursively, newest first) and prompts for a
// selection. Stdlib only; works on Windows and POSIX.
//
// Usage:
//   npm run test:e2e:trace-open          # interactive picker (defaults to newest)
//   npm run test:e2e:trace-open -- 2     # open entry #2 directly (no prompt)
//   npm run test:e2e:trace-open -- --latest  # old behavior: newest, no prompt
//   node scripts/open-latest-trace.mjs path/to/trace.zip
import { spawnSync } from "node:child_process";
import { readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { createInterface } from "node:readline";

const root = resolve(process.cwd(), "test-results");

function collectZips(dir, out) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }

  for (const entry of entries) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      collectZips(full, out);
    } else if (entry.isFile() && entry.name.toLowerCase().endsWith(".zip")) {
      try {
        const st = statSync(full);
        out.push({ path: full, mtimeMs: st.mtimeMs, size: st.size });
      } catch {
        // Skip unreadable files.
      }
    }
  }
  return out;
}

function fmtSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function fmtAge(mtimeMs) {
  const s = Math.max(0, Math.round((Date.now() - mtimeMs) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

function openTrace(zipPath) {
  console.log(`Opening trace: ${zipPath}`);
  const result = spawnSync("npx", ["playwright", "show-trace", zipPath], {
    stdio: "inherit",
    shell: true,
  });
  if (result.error) {
    console.error(`Failed to launch trace viewer: ${result.error.message}`);
    process.exit(1);
  }
  process.exit(result.status === null ? 1 : result.status);
}

function ask(question) {
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolveQ) => {
    rl.question(question, (answer) => {
      rl.close();
      resolveQ(answer);
    });
  });
}

const zips = collectZips(root, []).sort((a, b) => b.mtimeMs - a.mtimeMs);
if (!zips.length) {
  console.error(
    `No trace .zip found under ${root}.\n` +
      "Generate one with: npm run test:e2e:trace"
  );
  process.exit(1);
}

const args = process.argv.slice(2);

function printList() {
  console.log(`Playwright traces under ${root} (newest first):`);
  zips.forEach((z, i) => {
    const rel = relative(process.cwd(), z.path);
    console.log(
      `  ${i + 1}) ${rel}  (${fmtSize(z.size)}, ${fmtAge(z.mtimeMs)})`
    );
  });
}

if (args.includes("--list")) {
  printList();
  process.exit(0);
}
// Direct path arg: open it as-is.
if (args.length === 1 && !args[0].startsWith("-")) {
  const arg = args[0];
  const asNum = Number.parseInt(arg, 10);
  if (!Number.isNaN(asNum) && String(asNum) === arg.trim()) {
    const pick = zips[asNum - 1];
    if (!pick) {
      console.error(`Choice ${asNum} out of range (1-${zips.length}).`);
      process.exit(1);
    }
    openTrace(pick.path);
  } else {
    openTrace(resolve(process.cwd(), arg));
  }
} else if (args.includes("--latest") || !process.stdin.isTTY) {
  openTrace(zips[0].path);
} else {
  console.log(`Playwright traces under ${root} (newest first):`);
  zips.forEach((z, i) => {
    const rel = relative(process.cwd(), z.path);
    console.log(
      `  ${i + 1}) ${rel}  (${fmtSize(z.size)}, ${fmtAge(z.mtimeMs)})`
    );
  });
  const answer = await ask(`Select trace to open [1-${zips.length}] (default 1): `);
  const trimmed = answer.trim();
  const choice = trimmed === "" ? 1 : Number.parseInt(trimmed, 10);
  if (!Number.isInteger(choice) || choice < 1 || choice > zips.length) {
    console.error(`Invalid choice ${JSON.stringify(answer)} — expected 1-${zips.length}.`);
    process.exit(1);
  }
  openTrace(zips[choice - 1].path);
}
