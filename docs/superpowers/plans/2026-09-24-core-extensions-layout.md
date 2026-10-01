# Core / Extensions Directory Layout Implementation Plan

> **For agentic workers:** Follow tasks in order. Preserve existing staged and unstaged changes; do not reset or commit user work.

**Goal:** Move the Python application to root-level `core/`, Spider to `extensions/spider/`, tests to root `tests/`, and project metadata to root while retaining runtime behavior.

**Architecture:** Keep the importable app package name `jingxu`; configure setuptools to discover it below `core/`. Keep Spider as a standalone CLI source tree copied into `runtime/spider` at packaging time. Update all path consumers as one migration.

**Tech Stack:** Python 3.10+, setuptools, pytest, PyInstaller, PowerShell, FFmpeg.

---

### Task 1: Relocate source, tests, and project metadata

- Move `src/JingXu.Workbench.Py/jingxu/` to `core/jingxu/`.
- Move `src/JingXu.Workbench.Py/JingXu.Spider/` to `extensions/spider/`.
- Move main tests to root `tests/`; move Spider's own tests to `tests/spider/`.
- Move `pyproject.toml` to root and configure package discovery (`where = ["core"]`), root pytest paths, and `core` import path.

### Task 2: Update runtime, build, and tooling paths

- Update app source discovery in `jingxu.infrastructure.spider`, PyInstaller spec, PowerShell scripts, sync/audit tools, test path constants, package/resource lookup, and ignore rules.
- Preserve frozen layout (`runtime/spider`, `runtime/python`, `runtime/ffmpeg`, etc.) and executable names.
- Search the repository for obsolete source paths and replace only active references; retain historical references that explicitly document old layouts where useful.

### Task 3: Update docs and verify

- Update root README and developer/test/release docs to describe the actual layout and commands.
- Run import smoke, pytest, ruff if available, Spider tests, and packaging/runtime path checks as feasible; report unavailable Windows-only checks explicitly.
- Review final diff and git status to confirm pre-existing staged/unstaged changes remain untouched.
