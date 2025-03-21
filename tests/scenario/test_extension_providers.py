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


##########################################################################
# Tests for _workload_tracing_provider & _external_authorizer_providers
##########################################################################


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


def test_external_authorizer_config(istio_core_context, ingress_config):
    """Test that the external authorizer provider configuration is generated and flattened correctly."""
    state = State(relations=[ingress_config], leader=True)
    with istio_core_context(istio_core_context.on.config_changed(), state) as mgr:
        charm: IstioCoreCharm = mgr.charm

        external_providers = charm._external_authorizer_providers()
        flattened = charm._build_extension_providers_config(external_providers)

        expected = {
            "meshConfig.extensionProviders[0].name": "ext_authz-remote-d5881f05ed37db355557d3ad83ff8d6e0b0a473fc76446d611fd3a42dab9bc87",
            "meshConfig.extensionProviders[0].envoyExtAuthzHttp.service": "oauth-service",
            "meshConfig.extensionProviders[0].envoyExtAuthzHttp.port": "8080",
            "meshConfig.extensionProviders[0].envoyExtAuthzHttp.includeRequestHeadersInCheck[0]": "authorization",
            "meshConfig.extensionProviders[0].envoyExtAuthzHttp.includeRequestHeadersInCheck[1]": "cookie",
            "meshConfig.extensionProviders[0].envoyExtAuthzHttp.headersToUpstreamOnAllow[0]": "authorization",
            "meshConfig.extensionProviders[0].envoyExtAuthzHttp.headersToUpstreamOnAllow[1]": "path",
            "meshConfig.extensionProviders[0].envoyExtAuthzHttp.headersToUpstreamOnAllow[2]": "x-auth-request-user",
            "meshConfig.extensionProviders[0].envoyExtAuthzHttp.headersToUpstreamOnAllow[3]": "x-auth-request-email",
            "meshConfig.extensionProviders[0].envoyExtAuthzHttp.headersToUpstreamOnAllow[4]": "x-auth-request-access-token",
            "meshConfig.extensionProviders[0].envoyExtAuthzHttp.headersToDownstreamOnAllow[0]": "set-cookie",
            "meshConfig.extensionProviders[0].envoyExtAuthzHttp.headersToDownstreamOnDeny[0]": "content-type",
            "meshConfig.extensionProviders[0].envoyExtAuthzHttp.headersToDownstreamOnDeny[1]": "set-cookie",
        }
        assert flattened == expected


def test_combined_extension_providers_config(istio_core_context, workload_tracing, ingress_config):
    """Test that the combined configuration includes both tracing and external authorizer providers."""
    state = State(relations=[workload_tracing, ingress_config], leader=True)
    with istio_core_context(istio_core_context.on.config_changed(), state) as mgr:
        charm: IstioCoreCharm = mgr.charm
        mgr.run()

        # Retrieve providers.
        tracing_providers, global_tracing = charm._workload_tracing_provider()
        external_providers = charm._external_authorizer_providers()
        all_providers = tracing_providers + external_providers

        # Merge the flattened configuration from all providers with the global tracing settings.
        merged = {}
        merged.update(charm._build_extension_providers_config(all_providers))
        merged.update(global_tracing)

        expected = {
            # Tracing provider (index 0)
            "meshConfig.extensionProviders[0].name": "otel-tracing",
            "meshConfig.extensionProviders[0].opentelemetry.port": 4317,
            "meshConfig.extensionProviders[0].opentelemetry.service": "endpoint.namespace.svc.cluster.local",
            # External authorizer provider (index 1)
            "meshConfig.extensionProviders[1].name": "ext_authz-remote-d5881f05ed37db355557d3ad83ff8d6e0b0a473fc76446d611fd3a42dab9bc87",
            "meshConfig.extensionProviders[1].envoyExtAuthzHttp.service": "oauth-service",
            "meshConfig.extensionProviders[1].envoyExtAuthzHttp.port": "8080",
            "meshConfig.extensionProviders[1].envoyExtAuthzHttp.includeRequestHeadersInCheck[0]": "authorization",
            "meshConfig.extensionProviders[1].envoyExtAuthzHttp.includeRequestHeadersInCheck[1]": "cookie",
            "meshConfig.extensionProviders[1].envoyExtAuthzHttp.headersToUpstreamOnAllow[0]": "authorization",
            "meshConfig.extensionProviders[1].envoyExtAuthzHttp.headersToUpstreamOnAllow[1]": "path",
            "meshConfig.extensionProviders[1].envoyExtAuthzHttp.headersToUpstreamOnAllow[2]": "x-auth-request-user",
            "meshConfig.extensionProviders[1].envoyExtAuthzHttp.headersToUpstreamOnAllow[3]": "x-auth-request-email",
            "meshConfig.extensionProviders[1].envoyExtAuthzHttp.headersToUpstreamOnAllow[4]": "x-auth-request-access-token",
            "meshConfig.extensionProviders[1].envoyExtAuthzHttp.headersToDownstreamOnAllow[0]": "set-cookie",
            "meshConfig.extensionProviders[1].envoyExtAuthzHttp.headersToDownstreamOnDeny[0]": "content-type",
            "meshConfig.extensionProviders[1].envoyExtAuthzHttp.headersToDownstreamOnDeny[1]": "set-cookie",
            # Global tracing configuration.
            "meshConfig.enableTracing": "true",
            "meshConfig.defaultProviders.tracing[0]": "otel-tracing",
            "meshConfig.defaultConfig.tracing.sampling": 100.0,
        }
        assert merged == expected
