"""Create or update Grafana dashboards and alert rules.

Every artifact authored by this agent is stamped with the label
`created_by: monitor-agent` so Alertmanager can route alerts from
agent-created rules to the null receiver (loop guard #1).
"""
from __future__ import annotations

import json
from typing import Any

import httpx
from claude_agent_sdk import tool

from app.common.utils import get_logger
from app.config import AppConfig

logger = get_logger(__name__)

_AGENT_LABEL = "monitor-agent"


def _grafana_headers() -> dict[str, str]:
    obs = AppConfig.get_observability_config()
    headers = {"Content-Type": "application/json"}
    if obs.GRAFANA_API_KEY:
        headers["Authorization"] = f"Bearer {obs.GRAFANA_API_KEY}"
    else:
        import base64
        creds = base64.b64encode(b"admin:admin").decode()
        headers["Authorization"] = f"Basic {creds}"
    return headers


async def _create_dashboard(spec: dict) -> dict:
    obs = AppConfig.get_observability_config()
    base = obs.GRAFANA_URL.rstrip("/")

    # Stamp the agent label in dashboard tags.
    spec.setdefault("tags", [])
    if _AGENT_LABEL not in spec["tags"]:
        spec["tags"].append(_AGENT_LABEL)

    payload = {"dashboard": spec, "overwrite": True, "message": "created by monitor-agent"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{base}/api/dashboards/db",
            headers=_grafana_headers(),
            content=json.dumps(payload),
        )
        resp.raise_for_status()
        return resp.json()


async def _create_alert_rule(spec: dict) -> dict:
    obs = AppConfig.get_observability_config()
    base = obs.GRAFANA_URL.rstrip("/")

    # Stamp the loop-guard label.
    spec.setdefault("labels", {})
    spec["labels"]["created_by"] = _AGENT_LABEL

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{base}/api/v1/provisioning/alert-rules",
            headers=_grafana_headers(),
            content=json.dumps(spec),
        )
        resp.raise_for_status()
        return resp.json()


@tool(
    name="grafana_artifact",
    description=(
        "Create or update a Grafana dashboard or alert rule. "
        "Set kind='dashboard' to create a dashboard (spec is a Grafana dashboard JSON object). "
        "Set kind='alert_rule' to create an alert rule (spec is a Grafana alert rule object). "
        "The agent label 'created_by: monitor-agent' is stamped on every artifact automatically."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["dashboard", "alert_rule"],
                "description": "The type of artifact to create.",
            },
            "spec": {
                "type": "object",
                "description": "The Grafana JSON spec for the dashboard or alert rule.",
            },
        },
        "required": ["kind", "spec"],
    },
)
async def grafana_artifact_mcp(args: dict[str, Any]) -> dict[str, Any]:
    kind = args["kind"]
    spec = args["spec"]

    logger.info("grafana_artifact kind=%s", kind)
    try:
        if kind == "dashboard":
            result = await _create_dashboard(spec)
        else:
            result = await _create_alert_rule(spec)
        return {"content": [{"type": "text", "text": json.dumps(result)}]}
    except Exception as e:
        logger.exception("grafana_artifact failed")
        return {"content": [{"type": "text", "text": f"FAILED: {e}"}], "is_error": True}


__all__ = ["grafana_artifact_mcp"]
