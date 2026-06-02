/**
 * build-nodes-json.mjs — produce the `nodes.json` that powers `node-types`
 * (the exact-parameters / get_node_types equivalent), from a local n8n's node
 * packages. n8n ships a PRE-GENERATED descriptions array per package at
 * `<pkg>/dist/types/nodes.json`; we merge n8n-nodes-base + n8n-nodes-langchain
 * and prefix each node name with its package (the canonical `n8n-nodes-base.X`
 * form n8n uses at load time, which is what agents reference).
 *
 * Source: any node_modules dir that has the n8n node packages — e.g. the npx
 * cache from `npx n8n` (…/npm-cache/_npx/<hash>/node_modules), a global/Docker
 * install, or a local `npm i n8n-nodes-base`.
 *
 *   node scripts/build-nodes-json.mjs "<node_modules-dir>" [out=nodes.json]
 *
 * NOTE on versions: the resulting params track the n8n version of that source.
 * Match it to your target instance for exact fidelity (close minor versions are
 * fine for common nodes).
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const srcDir = process.argv[2];
const outPath = process.argv[3] || "nodes.json";
if (!srcDir) {
  console.error('usage: node scripts/build-nodes-json.mjs "<node_modules-dir>" [out]');
  process.exit(2);
}

const PACKAGES = [
  { dir: "n8n-nodes-base", prefix: "n8n-nodes-base" },
  { dir: join("@n8n", "n8n-nodes-langchain"), prefix: "@n8n/n8n-nodes-langchain" },
];

const merged = [];
for (const { dir, prefix } of PACKAGES) {
  const p = join(srcDir, dir, "dist", "types", "nodes.json");
  if (!existsSync(p)) {
    console.warn(`skip ${prefix}: no nodes.json at ${p}`);
    continue;
  }
  const arr = JSON.parse(readFileSync(p, "utf8"));
  for (const node of arr) {
    if (node.name && !node.name.includes(".")) node.name = `${prefix}.${node.name}`;
    merged.push(node);
  }
  console.log(`+ ${prefix}: ${arr.length} nodes`);
}

writeFileSync(outPath, JSON.stringify(merged));
console.log(`Wrote ${outPath}: ${merged.length} nodes`);
