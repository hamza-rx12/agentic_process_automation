"""Query logs (LogQL) and metrics (PromQL) through the Grafana datasource proxy.

Grafana proxy endpoints (v11+):
  Loki:       GET /api/datasources/proxy/uid/<uid>/loki/api/v1/query_range
  Prometheus: GET /api/datasources/proxy/uid/<uid>/api/v1/query_range
"""
from __future__ import annotations

import time
from typing import Any

import httpx
from claude_agent_sdk import tool

from app.common.utils import get_logger
from app.config import AppConfig

logger = get_logger(__name__)


def _grafana_headers() -> dict[str, str]:
    obs = AppConfig.get_observability_config()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if obs.GRAFANA_API_KEY:
        headers["Authorization"] = f"Bearer {obs.GRAFANA_API_KEY}"
    else:
        # Fall back to basic auth with default admin creds (dev only).
        import base64
        creds = base64.b64encode(b"admin:admin").decode()
        headers["Authorization"] = f"Basic {creds}"
    return headers


def _parse_loki_response(data: dict) -> list[dict]:
    results = []
    for stream in data.get("data", {}).get("result", []):
        for ts, line in stream.get("values", []):
            results.append({"timestamp": ts, "labels": stream.get("stream", {}), "line": line})
    return results


def _parse_prometheus_response(data: dict) -> list[dict]:
    results = []
    for series in data.get("data", {}).get("result", []):
        for ts, val in series.get("values", []):
            results.append({"timestamp": ts, "metric": series.get("metric", {}), "value": val})
    return results


async def _grafana_query(
    query: str,
    query_type: str,
    start: str,
    end: str,
    step: str,
) -> dict[str, Any]:
    obs = AppConfig.get_observability_config()
    base = obs.GRAFANA_URL.rstrip("/")
    headers = _grafana_headers()

    if query_type == "logs":
        uid = obs.LOKI_DATASOURCE_UID
        url = f"{base}/api/datasources/proxy/uid/{uid}/loki/api/v1/query_range"
        params = {"query": query, "start": start, "end": end, "limit": 100}
    else:
        uid = obs.PROMETHEUS_DATASOURCE_UID
        url = f"{base}/api/datasources/proxy/uid/{uid}/api/v1/query_range"
        params = {"query": query, "start": start, "end": end, "step": step}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

    if query_type == "logs":
        return {"query_type": "logs", "results": _parse_loki_response(data)}
    else:
        return {"query_type": "metrics", "results": _parse_prometheus_response(data)}


@tool(
    name="grafana_query",
    description=(
        "Query logs or metrics from Grafana via the datasource proxy. "
        "Use query_type='logs' for LogQL (Loki) and query_type='metrics' for PromQL (Prometheus). "
        "start/end are Unix timestamps (seconds). step is a Prometheus duration string like '60s'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The LogQL or PromQL query string.",
            },
            "query_type": {
                "type": "string",
                "enum": ["logs", "metrics"],
                "description": "Type of query: 'logs' for LogQL, 'metrics' for PromQL.",
            },
            "start": {
                "type": "string",
                "description": "Start time as Unix timestamp in seconds. Defaults to 1 hour ago.",
            },
            "end": {
                "type": "string",
                "description": "End time as Unix timestamp in seconds. Defaults to now.",
            },
            "step": {
                "type": "string",
                "description": "Step interval for metrics queries, e.g. '60s'. Ignored for logs.",
                "default": "60s",
            },
        },
        "required": ["query", "query_type"],
    },
)
async def grafana_query_mcp(args: dict[str, Any]) -> dict[str, Any]:
    query = args["query"]
    query_type = args["query_type"]
    now = int(time.time())
    start = args.get("start", str(now - 3600))
    end = args.get("end", str(now))
    step = args.get("step", "60s")

    logger.info("grafana_query type=%s query=%s", query_type, query[:120])
    try:
        result = await _grafana_query(query, query_type, start, end, step)
        return {"content": [{"type": "text", "text": str(result)}]}
    except Exception as e:
        logger.exception("grafana_query failed")
        return {"content": [{"type": "text", "text": f"FAILED: {e}"}], "is_error": True}


__all__ = ["grafana_query_mcp"]
