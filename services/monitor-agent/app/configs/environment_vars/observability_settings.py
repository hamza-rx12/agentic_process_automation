"""Observability stack settings loaded from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ObservabilitySettings:
    GRAFANA_URL: str
    GRAFANA_API_KEY: str
    # Fixed UIDs — must match monitoring/grafana/provisioning/datasources/datasources.yml
    LOKI_DATASOURCE_UID: str
    PROMETHEUS_DATASOURCE_UID: str


def load_observability_settings() -> ObservabilitySettings:
    return ObservabilitySettings(
        GRAFANA_URL=os.getenv("GRAFANA_URL", "http://grafana:3000"),
        GRAFANA_API_KEY=os.getenv("GRAFANA_API_KEY", ""),
        LOKI_DATASOURCE_UID=os.getenv("LOKI_DATASOURCE_UID", "loki"),
        PROMETHEUS_DATASOURCE_UID=os.getenv("PROMETHEUS_DATASOURCE_UID", "prometheus"),
    )


observability_settings: ObservabilitySettings = load_observability_settings()
