#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from scenario import State

from charm import IstioCoreCharm


def test_tracing_config(istio_core_context, workload_tracing):
    expected = {
        "meshConfig.enableTracing": "true",
        "meshConfig.extensionProviders[0].name": "otel-tracing",
        "meshConfig.extensionProviders[0].opentelemetry.port": 4317,
        "meshConfig.extensionProviders[0].opentelemetry.service": "endpoint.namespace.svc.cluster.local",
        "meshConfig.defaultProviders.tracing[0]": "otel-tracing",
        "meshConfig.defaultConfig.tracing.sampling": 100.0,
    }
    state = State(relations=[workload_tracing])
    with istio_core_context(istio_core_context.on.config_changed(), state) as mgr:
        charm: IstioCoreCharm = mgr.charm
        mgr.run()
        assert charm._workload_tracing_config() == expected
