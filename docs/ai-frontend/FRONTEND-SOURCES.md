# Modern frontend: sources and adaptation boundaries

## Actual dependencies

Versions are pinned in [`ai/frontend/package.json`](../../ai/frontend/package.json) and its `package-lock.json` (resolved URLs and integrity hashes). Host dependencies are in [`ai/requirements.txt`](../../ai/requirements.txt).

| Capability | Mature implementation / version | Project adaptation | License / source |
| --- | --- | --- | --- |
| Chat runtime, message list, composer state, attachments, scroll following | `@assistant-ui/react` 0.15.23 | `Chat.tsx` external-store runtime; `store.ts` owns host state; no second Agent runtime | MIT; https://github.com/assistant-ui/assistant-ui |
| UI | React / React DOM 19.1.1 | Session sidebar, settings dashboard and task-specific actions | MIT; https://github.com/facebook/react |
| Rich editor / IME / document model | Tiptap core/pm 3.31.4, react/starter-kit 3.6.6; ProseMirror Markdown 1.13.2 | `Composer.tsx`, `editor.ts`: Markdown serialization, IME commit guard, shortcuts, input history, attachment tags | MIT; https://github.com/ueberdosis/tiptap and https://github.com/ProseMirror/prosemirror-markdown |
| Markdown / tables / math | react-markdown 10.1.0, remark-gfm 4.0.1, remark-math 6.0.0 | Safe host-mediated links; external images and raw HTML blocked | MIT; https://github.com/remarkjs/react-markdown |
| Sanitization | rehype-sanitize 6.0.0, DOMPurify 3.2.7 | Sanitize Markdown tree and Mermaid SVG; no executable attachments | MIT (rehype); Apache-2.0 OR MPL-2.0 (DOMPurify); https://github.com/cure53/DOMPurify |
| Math / code | KaTeX 0.16.22, rehype-katex 7.0.1; highlight.js 11.11.1, rehype-highlight 7.0.2 | Offline fonts/styles; trust disabled; copy actions | MIT (KaTeX/rehype); BSD-3-Clause (highlight.js) |
| Diagrams | Mermaid 11.12.0 | Copy official browser ESM and lazy chunks into `public/vendor/mermaid`; load from host origin; strict mode and SVG sanitization | MIT; https://github.com/mermaid-js/mermaid |
| Icons | lucide-react 0.468.0 | Local SVG icons | ISC; https://github.com/lucide-icons/lucide |
| Desktop shell / .NET bridge | pywebview 6.2.1; pythonnet 3.2.0 | WebView2, loopback assets, source-checked single RPC facade | BSD-3-Clause (pywebview); MIT (pythonnet) |
| Build / tests | Vite 6.3.6, TypeScript 5.9.3, Vitest 3.2.4, Playwright 1.56.1 | Offline production output; bounded fixtures and desktop acceptance | MIT (Vite/Vitest); Apache-2.0 (TypeScript/Playwright) |

The dependency notices generator preserves package-root LICENSE/NOTICE/COPYING texts and KaTeX font notices in `ai/frontend/public/THIRD-PARTY-NOTICES.txt`, also shipped in `dist`. It includes installed non-development dependencies, not a precise tree-shaken bundle inventory. Packages lacking a root license text are explicitly identified with their source URLs; it does not claim to resolve all redistribution obligations automatically.

## PI-Desktop: local source extraction; no bundled application runtime

PI-Desktop research baseline: https://github.com/vastsa/PI-Desktop/tree/0d47d26769ecbeca1c3ab56fa83b58a91de8190e (desktop package 0.16.0, LGPL-3.0). Referenced composer/editor, activity/tool details, transcript scrolling, Markdown and style entry points are recorded in [architecture section 10](CHAT-UI-ARCHITECTURE.zh-CN.md#10-开源来源版本与复用边界).

Initially these interactions were project-local adaptations using assistant-ui/Tiptap/Markdown. The history-menu follow-up directly extracts/adapts `ContextMenu.tsx`, `context-menu.ts`, `scrollbar-reveal.ts`, and context-menu/6px-scrollbar CSS from the fixed PI-Desktop revision. Their LGPL-3.0 sources, originals, full license texts, modification/rebuild notice and replaceable frontend build inputs are retained in [`ai/third_party/pi-desktop/NOTICE.md`](../../ai/third_party/pi-desktop/NOTICE.md) and shipped under `dist/pi-desktop-source`. Session CRUD/pin host integration remains project-local. No global app-store, Electron IPC, plugins, work panels or Agent runtime is bundled. `useSmooth` and the earlier composer status remain project-local adapters, not copied Pi modules. Upstream tests were not run here; local checks are recorded in [SESSION-MENU-RESULTS.zh-CN.md](SESSION-MENU-RESULTS.zh-CN.md).

SillyTavern (AGPL-3.0) and its official screenshot were interaction references for numeric sampling/token controls, not copied source or bundled assets. The project does not include its runtime or stylesheets.

## Pi model data only

Four official OpenAI model window/output records and a local budget policy are adapted from the pinned `@mariozechner/pi-ai` 0.73.1 publication. Exact publication hash, gitHead, license-text provenance and endpoint restrictions are in [PI-MODEL-SOURCES.md](PI-MODEL-SOURCES.md); retained MIT text is [`ai/third_party/pi-ai-LICENSE`](../../ai/third_party/pi-ai-LICENSE).

No Pi package or Pi Agent core is a production dependency. The Python Pydantic AI/Graph and local client remain the executors. Unknown models and gateways with same-named models do not inherit official endpoint metadata.
