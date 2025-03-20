#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from scenario import State

from charm import IstioCoreCharm, flatten_config

#############################################
# Tests for flatten_config
#############################################


def test_flatten_config_with_flat_dict():
    """Verify that a flat dictionary is correctly flattened when a prefix is provided."""
    data = {"a": "value1", "b": "value2"}
    prefix = "provider[0]"
    expected = {
        "provider[0].a": "value1",
        "provider[0].b": "value2",
    }
    result = flatten_config(data, prefix)
    assert result == expected


def test_flatten_config_with_nested_dict():
    """Verify that nested dictionaries are recursively flattened with the provided prefix."""
    data = {"a": {"b": 1, "c": {"d": "x"}}, "e": 2}
    prefix = "prefix"
    expected = {
        "prefix.a.b": 1,
        "prefix.a.c.d": "x",
        "prefix.e": 2,
    }
    result = flatten_config(data, prefix)
    assert result == expected


def test_flatten_config_with_empty_dict():
    """Verify that flattening an empty dictionary returns an empty dictionary."""
    data = {}
    prefix = "p"
    expected = {}
    result = flatten_config(data, prefix)
    assert result == expected


def test_flatten_config_with_list_values():
    """Verify that list values are flattened into individual elements with indices when a prefix is provided."""
    data = {"a": 1, "b": ["1", "2", "3"], "c": ["1", "2"]}
    prefix = "provider[1]"
    expected = {
        "provider[1].a": 1,
        "provider[1].b[0]": "1",
        "provider[1].b[1]": "2",
        "provider[1].b[2]": "3",
        "provider[1].c[0]": "1",
        "provider[1].c[1]": "2",
    }
    result = flatten_config(data, prefix)
    assert result == expected


def test_flatten_config_with_tuple_values():
    """Verify that tuple values are flattened into individual elements with indices when a prefix is provided."""
    data = {"x": (10, 20), "y": ("a", "b", "c")}
    prefix = "provider"
    expected = {
        "provider.x[0]": 10,
        "provider.x[1]": 20,
        "provider.y[0]": "a",
        "provider.y[1]": "b",
        "provider.y[2]": "c",
    }
    result = flatten_config(data, prefix)
    assert result == expected


def test_flatten_config_with_empty_prefix_flat_data():
    """Verify that flattening flat data structures with an empty prefix produces keys without a leading dot."""
    data = {"a": 1, "b": ["1", "2", "3"], "c": ["1", "2"]}
    prefix = ""
    expected = {
        "a": 1,
        "b[0]": "1",
        "b[1]": "2",
        "b[2]": "3",
        "c[0]": "1",
        "c[1]": "2",
    }
    result = flatten_config(data, prefix)
    assert result == expected


def test_flatten_config_with_empty_prefix_nested_data():
    """Verify that flattening nested data structures with an empty prefix produces keys without a leading dot."""
    data = {"a": {"b": 1}, "c": ["1", "2", "3"], "d": {"e": ["1", "2", "3"]}}
    prefix = ""
    expected = {
        "a.b": 1,
        "c[0]": "1",
        "c[1]": "2",
        "c[2]": "3",
        "d.e[0]": "1",
        "d.e[1]": "2",
        "d.e[2]": "3",
    }
    result = flatten_config(data, prefix)
    assert result == expected


def test_flatten_config_primitive():
    """Verify that a primitive value (non-dict, non-list, non-tuple) is directly assigned to the prefix key."""
    value = 42
    prefix = "number"
    expected = {"number": 42}
    result = flatten_config(value, prefix)
    assert result == expected


def test_flatten_config_primitive_no_prefix():
    """Verify that a primitive value with an empty prefix is returned with an empty key."""
    value = "primitive"
    prefix = ""
    expected = {"": "primitive"}
    result = flatten_config(value, prefix)
    assert result == expected


#############################################
# Tests for _build_extension_providers_config
#############################################


def test_build_extension_providers_config_empty(istio_core_context):
    """Test that an empty providers list returns an empty configuration."""
    state = State(relations=[])
    with istio_core_context(istio_core_context.on.config_changed(), state) as mgr:
        charm: IstioCoreCharm = mgr.charm
        providers = []
        result = charm._build_extension_providers_config(providers)
        assert result == {}


def test_build_extension_providers_config_single(istio_core_context):
    """Test that a single provider is flattened and prefixed correctly."""
    state = State(relations=[])
    with istio_core_context(istio_core_context.on.config_changed(), state) as mgr:
        charm: IstioCoreCharm = mgr.charm
        provider = {"name": "test", "config": {"port": "1234"}}
        providers = [provider]
        expected = {
            "meshConfig.extensionProviders[0].name": "test",
            "meshConfig.extensionProviders[0].config.port": "1234",
        }
        result = charm._build_extension_providers_config(providers)
        assert result == expected


def test_build_extension_providers_config_multiple(istio_core_context):
    """Test that multiple providers are each flattened with their respective prefixes."""
    state = State(relations=[])
    with istio_core_context(istio_core_context.on.config_changed(), state) as mgr:
        charm: IstioCoreCharm = mgr.charm
        providers = [
            {"name": "prov1", "config": {"a": 1}},
            {"name": "prov2", "config": {"b": 2}},
        ]
        expected = {
            "meshConfig.extensionProviders[0].name": "prov1",
            "meshConfig.extensionProviders[0].config.a": 1,
            "meshConfig.extensionProviders[1].name": "prov2",
            "meshConfig.extensionProviders[1].config.b": 2,
        }
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
    with istio_core_context(istio_core_context.on.config_changed(), state) as mgr:
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
