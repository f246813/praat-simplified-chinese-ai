// Use Mermaid's official browser build without re-bundling its diagram engines.
import { copyFileSync, mkdirSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
const source = 'node_modules/mermaid/dist';
const target = 'public/vendor/mermaid';
mkdirSync(target, {recursive: true});
copyFileSync(join(source, 'mermaid.esm.min.mjs'), join(target, 'mermaid.esm.min.mjs'));
function copyModules(from, to) {
  mkdirSync(to, {recursive: true});
  for (const name of readdirSync(from)) {
    const file = join(from, name);
    if (statSync(file).isDirectory()) copyModules(file, join(to, name));
    else if (name.endsWith('.mjs')) copyFileSync(file, join(to, name));
  }
}
copyModules(join(source, 'chunks/mermaid.esm.min'), join(target, 'chunks/mermaid.esm.min'));
console.log('Copied official Mermaid browser ESM and lazy diagram chunks for offline use.');
