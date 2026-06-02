#!/usr/bin/env node
/**
 * n8n-skill — reproduce the core of n8n's 25-tool MCP using only:
 *   - @n8n/workflow-sdk (local: parse code -> JSON, validate)   [no server]
 *   - the n8n public REST API (create)                          [X-N8N-API-KEY]
 *
 * The n8n MCP server is, in essence, a server wrapper around this SDK + REST.
 * This CLI is the local primitive a published llms.txt skill tells an agent to
 * call — instead of loading 25 MCP tool schemas into context.
 *
 * MCP tool            -> here
 * ------------------------------------------------------------------
 * get_sdk_reference   -> `reference [section]`   (from the SDK's own prompts)
 * validate_workflow   -> `validate`  (stdin = SDK code)   uses validateWorkflow()
 * create_workflow...  -> `create`    (stdin = SDK code)   parse + validate + POST
 *
 * Usage:
 *   node src/n8n-skill.mjs reference [patterns|rules|expressions|functions]
 *   echo "<sdk code>" | node src/n8n-skill.mjs validate
 *   echo "<sdk code>" | node src/n8n-skill.mjs create
 *
 * Env (create only):
 *   N8N_API_BASE   default https://ardf.dev/api/v1
 *   N8N_API_KEY    n8n REST API key (X-N8N-API-KEY)   [never commit]
 */
import { parseWorkflowCode, validateWorkflow } from "@n8n/workflow-sdk";
import * as sdkRef from "@n8n/workflow-sdk/prompts/sdk-reference";

const API_BASE = process.env.N8N_API_BASE || "https://ardf.dev/api/v1";
const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36";

function readStdin() {
  return new Promise((resolve) => {
    let d = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (c) => (d += c));
    process.stdin.on("end", () => resolve(d));
  });
}

function out(obj) {
  process.stdout.write(JSON.stringify(obj, null, 2) + "\n");
}

const REFERENCE_SECTIONS = {
  patterns: "WORKFLOW_SDK_PATTERNS",
  rules: "WORKFLOW_RULES",
  expressions: "EXPRESSION_REFERENCE",
  functions: "ADDITIONAL_FUNCTIONS",
  detailed: "WORKFLOW_PATTERNS_DETAILED",
};

function cmdReference(section) {
  if (!section) {
    out({ sections: Object.keys(REFERENCE_SECTIONS) });
    return 0;
  }
  const key = REFERENCE_SECTIONS[section];
  const text = key ? sdkRef[key] : undefined;
  if (!text) {
    out({ error: `unknown section '${section}'`, sections: Object.keys(REFERENCE_SECTIONS) });
    return 2;
  }
  process.stdout.write(text + "\n");
  return 0;
}

function parseAndValidate(code) {
  const json = parseWorkflowCode(code); // throws SyntaxError on bad code
  const res = validateWorkflow(json);
  return { json, res };
}

function cmdValidate(code) {
  try {
    const { json, res } = parseAndValidate(code);
    out({
      valid: res.valid,
      nodeCount: json.nodes.length,
      errors: res.errors || [],
      warnings: res.warnings || [],
    });
    return res.valid ? 0 : 1;
  } catch (e) {
    out({ valid: false, parseError: String(e.message || e) });
    return 1;
  }
}

async function cmdCreate(code) {
  let json, res;
  try {
    ({ json, res } = parseAndValidate(code));
  } catch (e) {
    out({ created: false, parseError: String(e.message || e) });
    return 1;
  }
  if (!res.valid) {
    out({ created: false, valid: false, errors: res.errors || [] });
    return 1;
  }
  const key = process.env.N8N_API_KEY;
  if (!key) {
    out({ created: false, error: "set N8N_API_KEY (X-N8N-API-KEY) to create" });
    return 2;
  }
  // REST workflowCreate accepts name, nodes, connections, settings. Drop the
  // SDK's placeholder id and let n8n assign one.
  const body = {
    name: json.name,
    nodes: json.nodes,
    connections: json.connections,
    settings: json.settings || {},
  };
  const r = await fetch(`${API_BASE}/workflows`, {
    method: "POST",
    headers: {
      "X-N8N-API-KEY": key,
      "Content-Type": "application/json",
      Accept: "application/json",
      "User-Agent": UA,
    },
    body: JSON.stringify(body),
  });
  const text = await r.text();
  if (!r.ok) {
    out({ created: false, status: r.status, response: text.slice(0, 800) });
    return 1;
  }
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    parsed = { raw: text.slice(0, 400) };
  }
  out({ created: true, id: parsed.id, name: parsed.name, nodeCount: json.nodes.length });
  return 0;
}

async function main() {
  const [cmd, arg] = process.argv.slice(2);
  switch (cmd) {
    case "reference":
      return cmdReference(arg);
    case "validate":
      return cmdValidate(await readStdin());
    case "create":
      return cmdCreate(await readStdin());
    default:
      out({
        error: "usage: n8n-skill <reference|validate|create>",
        reference: "reference [patterns|rules|expressions|functions|detailed]",
        validate: "echo '<sdk code>' | n8n-skill validate",
        create: "echo '<sdk code>' | n8n-skill create   (needs N8N_API_KEY)",
      });
      return 2;
  }
}

main().then((code) => process.exit(code || 0));
