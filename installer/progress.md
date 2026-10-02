# SDD ledger — plan: docs/superpowers/plans/2026-09-29-aipraat-installer.md

User approved the design and authorized self-review of further spec/plan stages and direct implementation.
Spec and plan self-review: requirements covered; no unresolved placeholders.
Pre-flight: Task 1 InstallRequest/PathValidation/Configuration/InstallEngine interfaces consumed by wizard, launcher and final tests; consistent.
Ruling: Exported source snapshot has no .git; implement in installer/ and do not create another checkout — preserves the authoritative current exe.
Ruling: User requires low-priority tests at final batch; write behavioral contracts first, defer their execution and broad regression until Task 4.
Ruling: Python probe must include Pillow because ui_widgets imports PIL at startup; Python/Tk/NumPy alone cannot start the actual UI.
Task 1: services and contracts implemented. Existing data/configuration preservation, rollback, safe extraction and path validation covered by final contracts.
Task 2: wizard, launcher and optional elevation implemented. Live UI covered manual/browse selection, skip/configure, gray/black Next, actual byte progress and completion. Installed Praat and AI windows both opened through the launcher without changing existing user preferences.
Task 3: root AIPraat-install.exe built with 59 curated resource files (58 hashed application files plus manifest); development credentials/config/logs excluded. Original Praat SHA-256 unchanged.
Task 4: complete. Final batch: 21 installer contracts and 555 AI tests passed (80.967 seconds). Configured and fresh skip installations completed with real progress and completion text. All 58 application hashes match both installed targets; package credential/configuration audit passed. Root release exe opens directly. Audit: installer/verification/acceptance-report.md.
Fresh reviewer installer_review read 11/11 production files and identified redirected-user-folder validation, elevation retry selection loss, preset replacement and stale asynchronous Python probes. All four addressed with regression contracts; installation button now says 安装中 while work is running.
UI capture helper timed out twice. Accessibility observations remain available; actual WinForms controls are also rendered by the isolated test host with DrawToBitmap for visual inspection. These images are form-rendered acceptance artifacts, not OS screenshots.
UAC secure desktop is not automated. Original-user destination validation and resume/retry behavior are covered directly; actual UAC interaction remains a release-environment check.
