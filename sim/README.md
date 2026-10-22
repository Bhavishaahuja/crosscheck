# Calling Crosscheck from a Sim workflow

Run the service where your Sim instance can reach it:

```bash
uvicorn crosscheck.api:app --host 0.0.0.0 --port 8008
# env: SIM_BASE_URL, SIM_API_KEY, ANTHROPIC_API_KEY, SLACK_WEBHOOK_URL
```

## Option A: final block of the agent workflow

The run is still in progress while its own last block executes, so its log may not exist yet. Post the
data the block already has instead of a run id:

1. After the Agent block, add an **API** block: `POST http://<host>:8008/check`.
2. Body:
   ```json
   {
     "log": {
       "runId": "<start.executionId>",
       "traceSpans": [{"id": "agent", "type": "agent", "toolCalls": <agent1.toolCalls>}],
       "finalOutput": {"content": "<agent1.content>"}
     }
   }
   ```
3. Optionally add a **Condition** block on `<api1.data.verdict> === "flag"`, and route to a Slack block or a
   Response block with an error so the run itself shows as failed.

## Option B: scheduled audit workflow (recommended)

Checks finished runs through the Logs API, so it needs no change to the agent workflows.

1. **Schedule** trigger, e.g. every 15 minutes.
2. **API** block: `GET {SIM_BASE_URL}/api/v2/logs?workspaceId=<id>&status=completed&startDate=<15 min ago>&limit=50`
   with header `X-API-Key`.
3. **Loop** (forEach) over `<api1.data>`. Inside it, an **API** block: `POST http://<host>:8008/check` with
   `{"run_id": "<loop.currentItem.runId>"}`.
4. Flagged runs post to Slack from the service (`SLACK_WEBHOOK_URL`). To keep alerts inside Sim, set
   `CROSSCHECK_WEBHOOK_URL` to a Sim workflow with a webhook trigger, and send from there.
