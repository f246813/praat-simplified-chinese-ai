// SPDX-License-Identifier: LGPL-3.0
// Exact folderNameFromPath extraction from PI-Desktop 0d47d267,
// apps/desktop/src/lib/project-name.ts; original is shipped with the source notice.
export function folderNameFromPath(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.at(-1) ?? path.trim();
}
