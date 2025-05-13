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
    # TODO: Python 3.10 lets you have multiple context managers in a single with statement
    with patch.object(IstioCoreCharm, "_reconcile_control_plane"):
        with patch.object(IstioCoreCharm, "_reconcile_istio_crds"):
            with patch.object(IstioCoreCharm, "_reconcile_gateway_api_crds"):
                with patch.object(IstioCoreCharm, "_setup_proxy_pebble_service"):
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
        },
        local_app_data={},
    )
