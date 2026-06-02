---
name: build-n8n-workflow
description: Build a workflow in this n8n instance without the n8n MCP — using the @n8n/workflow-sdk (parse + validate, locally) and the n8n REST API (create). Use when the user asks to create/automate an n8n workflow. This skill IS the recipe; the n8n CLI tool is the only primitive you call.
version: 1.0.0
license: MIT
---

# Build an n8n workflow (SDK + REST, no MCP)

n8n ships a 25-tool MCP to build workflows. You don't need it. The same
capability is here as: **one CLI primitive** backed by `@n8n/workflow-sdk`
(parse code → JSON, validate — locally) and the n8n REST API (create). This
skill is the procedure; follow it in order.

The CLI: `node src/n8n-skill.mjs <reference|search-nodes|node-types|validate|create>`.
These map 1:1 onto the MCP's build tools (`get_sdk_reference`, `search_nodes`,
`get_node_types`, `validate_workflow`, `create_workflow_from_code`).

## Recipe

1. **Learn the syntax (once).** Run `node src/n8n-skill.mjs reference patterns`
   (and `reference rules` if needed). This is the SDK reference, straight from
   the package — the equivalent of the MCP's `get_sdk_reference`.

   *Unfamiliar with which node to use, or its parameters?* `search-nodes <need>`
   gives node-selection guidance; `node-types <type,type>` gives exact parameters
   **when a `nodes.json` is configured** (see below). For the common nodes the
   templates above + the `validate` loop are enough — don't over-fetch.

2. **Write the workflow code.** Plain SDK code, **no `import` line** — the
   builder functions (`workflow`, `trigger`, `node`, `ifElse`, `switchCase`,
   `merge`, `splitInBatches`, `expr`, …) are injected. Shape:
   ```js
   const start = trigger({ type: 'n8n-nodes-base.scheduleTrigger', version: 1.2,
     config: { name: 'Schedule', parameters: { rule: { interval: [ { field: 'cronExpression', expression: '0 9 * * *' } ] } } } });
   const slack = node({ type: 'n8n-nodes-base.slack', version: 2.3,
     config: { name: 'Slack', parameters: { resource: 'message', operation: 'post',
       select: 'channel', channelId: { mode: 'name', value: 'general' }, text: 'Hello' } } });
   export default workflow('id', 'My workflow').add(start).to(slack);
   ```
   Compose with `.add(<trigger>)` then `.to(<node>)` in execution order.

3. **Validate before creating.** Pipe the code to the CLI:
   `printf '%s' "<code>" | node src/n8n-skill.mjs validate`
   It returns `{ valid, errors, warnings }` (this runs `validateWorkflow` from the
   SDK locally — the equivalent of the MCP's `validate_workflow`). If not valid,
   fix the code and re-validate. Do not create invalid code. **This local loop is
   how you get parameters right without a live `get_node_types`:** the validator
   names the bad parameter; fix and re-run.

4. **Create.** `printf '%s' "<code>" | node src/n8n-skill.mjs create`
   It parses, validates, and `POST`s to the n8n REST API, returning
   `{ created: true, id }` (the equivalent of `create_workflow_from_code`). Report
   the id. The workflow is created as an inactive draft; do not activate unless asked.

## Common node types

`n8n-nodes-base.scheduleTrigger` (1.2) · `n8n-nodes-base.webhook` (2) ·
`n8n-nodes-base.httpRequest` (4.2) · `n8n-nodes-base.set` (3.4) ·
`n8n-nodes-base.slack` (2.3) · `n8n-nodes-base.if` · `n8n-nodes-base.code`.
For exact parameters, consult `reference patterns`.

## Rules

- No `import` statement in the code; functions are injected.
- Always `validate` until clean before `create`.
- One `create`. Do not poll or list afterwards.
- If validation fails 3× in a row, report the last error instead of looping.

## Done criteria

`create` returned `{ created: true, id }` for a workflow matching the request.
