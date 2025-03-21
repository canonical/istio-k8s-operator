#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from scenario import State

from charm import IstioCoreCharm

#############################################
# Tests for _build_extension_providers_config
#############################################


@pytest.mark.parametrize(
    "providers, expected",
    [
        # Empty providers list returns an empty configuration.
        ([], {}),
        # Single provider: should be flattened and prefixed correctly.
        (
            [{"name": "test", "config": {"port": "1234"}}],
            {
                "meshConfig.extensionProviders[0].name": "test",
                "meshConfig.extensionProviders[0].config.port": "1234",
            },
        ),
        # Multiple providers: each provider is flattened with its respective prefix.
        (
            [{"name": "prov1", "config": {"a": 1}}, {"name": "prov2", "config": {"b": 2}}],
            {
                "meshConfig.extensionProviders[0].name": "prov1",
                "meshConfig.extensionProviders[0].config.a": 1,
                "meshConfig.extensionProviders[1].name": "prov2",
                "meshConfig.extensionProviders[1].config.b": 2,
            },
        ),
    ],
)
def test_build_extension_providers_config(istio_core_context, providers, expected):
    """Parameterized test for the _build_extension_providers_config method."""
    state = State(relations=[])
    with istio_core_context(istio_core_context.on.update_status(), state) as mgr:
        charm: IstioCoreCharm = mgr.charm
        result = charm._build_extension_providers_config(providers)
        assert result == expected


#############################################
# Tests for _workload_tracing_provider
#############################################


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
    with istio_core_context(istio_core_context.on.update_status(), state) as mgr:
        charm: IstioCoreCharm = mgr.charm
        mgr.run()
        # Retrieve the tuple (providers, global_tracing) from the charm.
        providers, global_tracing = charm._workload_tracing_provider()
        # Merge the flattened extension providers and global tracing settings.
        merged = {}
        merged.update(charm._build_extension_providers_config(providers))
        merged.update(global_tracing)
        assert merged == expected
