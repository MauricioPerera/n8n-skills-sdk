/**
 * demo.mjs — end-to-end proof that the n8n MCP's "build a workflow" capability
 * can be reproduced with NO MCP: @n8n/workflow-sdk (parse + validate, local) +
 * the n8n REST API (create). Creates a workflow, prints the id, then deletes it.
 *
 *   N8N_API_KEY=... node demo.mjs
 */
import { parseWorkflowCode, validateWorkflow } from "@n8n/workflow-sdk";

const API_BASE = process.env.N8N_API_BASE || "https://ardf.dev/api/v1";
const KEY = process.env.N8N_API_KEY;
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36";

const code = `
const start = trigger({ type: 'n8n-nodes-base.scheduleTrigger', version: 1.2,
  config: { name: 'Schedule', parameters: { rule: { interval: [ { field: 'cronExpression', expression: '0 9 * * *' } ] } } } });
const slack = node({ type: 'n8n-nodes-base.slack', version: 2.3,
  config: { name: 'Slack', parameters: { resource: 'message', operation: 'post', select: 'channel',
    channelId: { mode: 'name', value: 'general' }, text: 'Daily standup time' } } });
export default workflow('demo', 'n8n-skills-sdk demo (no MCP)').add(start).to(slack);
`;

function api(method, path, body) {
  return fetch(`${API_BASE}${path}`, {
    method,
    headers: { "X-N8N-API-KEY": KEY, "Content-Type": "application/json", "User-Agent": UA },
    body: body ? JSON.stringify(body) : undefined,
  });
}

async function main() {
  console.log("1. parse SDK code -> workflow JSON (local, = create_workflow_from_code's parse)");
  const json = parseWorkflowCode(code);
  console.log("   nodes:", json.nodes.map((n) => n.name).join(" -> "));

  console.log("2. validate locally (= validate_workflow)");
  const res = validateWorkflow(json);
  console.log("   valid:", res.valid, "errors:", (res.errors || []).length, "warnings:", (res.warnings || []).length);
  if (!res.valid) return console.error("   invalid:", res.errors);

  if (!KEY) return console.log("3. (set N8N_API_KEY to actually create via REST)");

  console.log("3. create via REST POST /workflows (= create_workflow_from_code's save)");
  const r = await api("POST", "/workflows", {
    name: json.name, nodes: json.nodes, connections: json.connections, settings: json.settings || {},
  });
  if (!r.ok) return console.error("   create failed:", r.status, (await r.text()).slice(0, 300));
  const created = await r.json();
  console.log("   created id:", created.id);

  console.log("4. cleanup: DELETE /workflows/" + created.id);
  const d = await api("DELETE", `/workflows/${created.id}`);
  console.log("   delete HTTP", d.status);
  console.log("\nReproduced the MCP's build->validate->create path with 0 MCP tools.");
}

main();
