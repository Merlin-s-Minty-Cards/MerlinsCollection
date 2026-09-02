#!/usr/bin/env node
// Cross-platform backend test runner for `npm run test:backend` (root package.json).
//
// Why this exists: the previous version of this script was a single hardcoded
// command (`.venv\Scripts\python.exe -m pytest ...`), which only works on a
// Windows clone with the venv at the repo root. It silently broke on WSL/Linux
// clones, where the venv typically lives at `backend/.venv/bin/python` instead.
// A plain shell one-liner can't branch on that in a way that works under both
// cmd.exe (Windows) and sh (Linux/macOS/WSL) — npm picks the shell per-OS — so
// this resolves the interpreter in Node, which npm always has available
// regardless of platform, then spawns pytest with inherited stdio.
//
// Mirrors the interpreter-resolution order in scripts/run-tests.sh: prefer a
// project venv, then whatever `python3`/`python` is on PATH, and fail loudly
// with no interpreter rather than silently reporting zero tests (see CLAUDE.md
// "Use the venv interpreter explicitly, not bare `python`").
"use strict";

const { spawnSync } = require("child_process");
const { existsSync } = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");

const candidates = [
  path.join(ROOT, "backend", ".venv", "bin", "python"), // Linux/WSL/macOS
  path.join(ROOT, ".venv", "Scripts", "python.exe"), // Windows, venv at repo root
  path.join(ROOT, "backend", ".venv", "Scripts", "python.exe"), // Windows, venv under backend/
];

let python = candidates.find(existsSync);

if (!python) {
  for (const name of ["python3", "python"]) {
    const probe = spawnSync(name, ["--version"], { stdio: "ignore" });
    if (probe.status === 0) {
      python = name;
      break;
    }
  }
}

if (!python) {
  console.error(
    "[test:backend] No Python interpreter found. Checked: " +
      candidates.join(", ") +
      ", and python3/python on PATH. See CLAUDE.md > Test Commands."
  );
  process.exit(1);
}

const result = spawnSync(
  python,
  ["-m", "pytest", "backend/tests", "-q", "--tb=short"],
  { cwd: ROOT, stdio: "inherit" }
);

process.exit(result.status === null ? 1 : result.status);
