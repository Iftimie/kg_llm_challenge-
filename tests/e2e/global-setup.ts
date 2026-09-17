// Clean up the run-unique sqlite DBs left by earlier browser runs.
//
// The suite uses `sqlite:///./test-e2e-<pid>.db` (see playwright.config.ts), so
// each run gets a fresh DB and the chat-history restore feature never sees
// stale rows. This teardown-style hook best-effort removes the previous runs'
// files; the current run's DB is locked by the already-started webServer and is
// simply skipped (a later run's setup will remove it).
import { readdirSync, rmSync } from "node:fs";
import path from "node:path";

function rm(entries: string[]) {
  for (const entry of entries) {
    try {
      rmSync(path.join(process.cwd(), entry), { force: true });
    } catch {
      // Ignore: already gone, or (Windows) locked by the running server.
    }
  }
}

export default function globalSetup() {
  // Legacy fixed-name DB from before the run-unique naming.
  rm(["test-e2e.db", "test-e2e.db-journal", "test-e2e.db-wal", "test-e2e.db-shm"]);

  // Orphaned run-unique DBs.
  try {
    const orphans = readdirSync(process.cwd()).filter(
      (entry) => entry.startsWith("test-e2e-") && entry.includes(".db")
    );
    rm(orphans);
  } catch {
    // readdir failed; nothing to clean.
  }
}
