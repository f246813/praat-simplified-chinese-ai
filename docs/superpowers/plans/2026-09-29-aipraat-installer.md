# AIPraat Installer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. User authorized self-review of spec/plan and direct construction. Steps use checkbox syntax.

**Goal:** Deliver a standalone AIPraat-install.exe implementing the confirmed three-step Windows installer.

**Architecture:** A WinForms wizard consumes path validation and transactional installer services. A safe embedded ZIP packages the existing application; a small launcher binds user-selected paths to Praat and the AI package.

**Tech Stack:** C# / .NET Framework, WinForms, ZIP resources, PowerShell reproducible build, Python existing AI frontend.

**Spec:** `docs/superpowers/specs/2026-09-29-aipraat-installer-design.md`

## Global Constraints

- Default `C:\AIPraat`; reuse existing directories exactly.
- Configure now or skip; Python 3.10+ with Tk/NumPy >=2/Pillow >=10 required only when configure now.
- llama-server.exe, model GGUF and mmproj GGUF optional.
- Disabled Next has gray border/text; enabled Next has black border/text.
- Actual installation progress and explicit success/failure.
- User requires low-priority test execution deferred until the final batch.
- This directory is an exported Git snapshot; no Git worktree or commits are possible. Work in `installer/`, preserving the existing Praat executable and algorithm sources.

## Review Focus

- Existing files/configuration and API credentials survive reinstall; developer credentials never enter the payload.
- Chinese/spaces/quotes in paths resolve without shell interpretation.
- C:\ destination lacking permissions offers elevation/reselection and preserves originating user destinations.
- Invalid/stale Python checks cannot enable Next; optional empty paths do not block it.
- Partial failure/locked files/reparse points leave no falsely successful installation.

### Task 1: Installer services and contracts

**Files:** `installer/src/InstallModel.cs`, `PathValidation.cs`, `Configuration.cs`, `InstallEngine.cs`, `installer/tests/ContractTests.cs`.

**Interfaces:** InstallRequest carries exact paths and original user profile destinations; PathValidation validates target/prerequisites; InstallEngine.Run(request, payload, progress) performs installation; Configuration prepares JSON/preferences/plugin bindings.

- [x] Write behavioral contracts for reuse, skip, valid/invalid optional files, Unicode paths, profile preservation, safe extraction and rollback.
- [x] Implement path validation, Python capability probe, config merging and transactional file installation.
- [x] Defer routine test execution to Task 4, per user instruction.

### Task 2: Wizard and launcher

**Files:** `installer/src/WizardForm.cs`, `OutlineButton.cs`, `Program.cs`, `Launcher.cs`, `app.manifest`.

**Interfaces:** WizardForm uses Task 1 services; Launcher uses installed settings and Configuration to bind Praat paths for the active user.

- [x] Implement three steps, browse/input controls, asynchronous prerequisite checks and exact button colors.
- [x] Implement background progress, explicit completion/error, permission retry preserving original user context.
- [x] Implement launch entry, user shortcuts and plugin setup without changing core algorithms.

### Task 3: Standalone packaging

**Files:** `installer/build.ps1` (generates sanitized template in installer/build), `installer/README.zh-CN.md`.

**Interfaces:** Build compiles launcher and installer using installed framework compiler and embeds curated ZIP as `AIPraat.Payload.zip`.

- [x] Build sanitized payload with file hashes; exclude local configuration, runtime/logs/cache/tests.
- [x] Produce root `AIPraat-install.exe` and build/hash report; compile without running low-priority tests.

### Task 4: Final batch validation and fresh review

**Files:** `installer/tests/Run-Tests.ps1`, `installer/tests/UiHost.cs`, `installer/verification/*`.

- [x] Run all installer contracts and existing AI unit tests in one final batch; inspect every result.
- [x] Use the real wizard in an isolated UI host to exercise browse/input, gray/black buttons, skip/configured, progress and completion; capture screenshots.
- [x] Check installed executable hash/version and installed Python frontend on actual files, avoiding permanent changes to this computer's existing Praat setup.
- [x] Dispatch one fresh reviewer per executing-plans; resolve material findings and rerun affected checks.
- [x] Audit every spec requirement against evidence, then mark goal complete.
