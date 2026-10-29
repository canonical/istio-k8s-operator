#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from unittest.mock import patch

import pytest
from charms.tempo_coordinator_k8s.v0 import charm_tracing
from scenario import Context, Relation

from src.charm import IstioCoreCharm


@pytest.fixture(autouse=True)
def charm_tracing_buffer_to_tmp(tmp_path):
    with patch.object(charm_tracing, "BUFFER_DEFAULT_CACHE_FILE_NAME", tmp_path):
        yield


@pytest.fixture()
def istio_core_charm():
    with (
        patch.object(IstioCoreCharm, "_reconcile_control_plane"),
        patch.object(IstioCoreCharm, "_reconcile_authorization_policies"),
        patch.object(IstioCoreCharm, "_reconcile_istio_crds"),
        patch.object(IstioCoreCharm, "_reconcile_gateway_api_crds"),
        patch.object(IstioCoreCharm, "_setup_proxy_pebble_service"),
        patch.object(IstioCoreCharm, "_set_istio_version"),
        patch.object(IstioCoreCharm, "_claim_cni_ownership", return_value=True),
        patch.object(IstioCoreCharm, "_get_cni_ownership_status", return_value=None),
    ):
        yield IstioCoreCharm


@pytest.fixture()
def istio_core_context(istio_core_charm):
    yield Context(charm_type=istio_core_charm)


@pytest.fixture(scope="function")
def workload_tracing():
    return Relation(
        "workload-tracing",
        remote_app_data={
            "receivers": json.dumps(
                [
                    {
                        "protocol": {"name": "otlp_grpc", "type": "grpc"},
                        "url": "endpoint.namespace.svc.cluster.local:4317",
                    }
                ]
            )
        },
        local_app_data={"receivers": json.dumps(["otlp_grpc"])},
    )


@pytest.fixture(scope="function")
def ingress_config():
    return Relation(
        "istio-ingress-config",
        remote_app_data={
            "ext_authz_service_name": "oauth-service",
            "ext_authz_port": "8080",
            "include_headers_in_check": json.dumps(["authorization", "cookie"]),
            "headers_to_upstream_on_allow": json.dumps([
                "authorization",
                "path",
                "x-auth-request-user",
                "x-auth-request-email",
                "x-auth-request-access-token",
            ]),
            "headers_to_downstream_on_allow": json.dumps(["set-cookie"]),
            "headers_to_downstream_on_deny": json.dumps(["content-type", "set-cookie"]),
        },
        local_app_data={},
    )
