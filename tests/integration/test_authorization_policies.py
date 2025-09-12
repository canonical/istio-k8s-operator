#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml
from helpers import (
    assert_request_returns_http_code,
    istio_beacon_k8s,
)
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
resources = {
    "metrics-proxy-image": METADATA["resources"]["metrics-proxy-image"]["upstream-source"],
}


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, istio_core_charm):
    """Build the charm-under-test and deploy it."""
    # Deploy the charm and wait for active/idle status
    await ops_test.track_model("istio-system", model_name=f"{ops_test.model.name}-istio-system")
    istio_system_model = ops_test.models.get("istio-system")
    assert istio_system_model

    await asyncio.gather(
        istio_system_model.model.deploy(
            istio_core_charm,
            resources=resources,
            application_name=APP_NAME,
            trust=True,
        ),
        istio_system_model.model.wait_for_idle(
            apps=[APP_NAME], status="active", raise_on_blocked=True, timeout=1000
        ),
    )


@pytest.mark.abort_on_fail
async def test_deploy_dependencies(ops_test: OpsTest, service_mesh_tester):
    """Deploy the required dependencies to test the auth policies from istio-k8s charm."""
    assert ops_test.model

    # deploy the dependency charms
    resources = {"echo-server-image": "jmalloc/echo-server:v0.3.7"}

    await ops_test.model.deploy(**asdict(istio_beacon_k8s))
    await ops_test.model.deploy(
        service_mesh_tester,
        application_name="receiver",
        resources=resources,
        trust=True,
    )
    await ops_test.model.deploy(
        service_mesh_tester,
        application_name="sender",
        resources=resources,
        trust=True,
    )
    # put the dependency charms on the mesh
    await ops_test.model.applications[istio_beacon_k8s.application_name].set_config({"model-on-mesh": "true"})
    await ops_test.model.wait_for_idle(
        [
            istio_beacon_k8s.application_name,
            "sender",
            "receiver",
        ],
        status="active",
        raise_on_error=False,
        timeout=1000,
    )


@pytest.mark.abort_on_fail
@pytest.mark.parametrize("hardened_mode", [True, False])
async def test_hardened_mode(ops_test: OpsTest, hardened_mode):
    """Test if the hardened-mode is applied correctly.

    Currently this tests the following, when the `hardened-mode=true`, the charms on the mesh wont be able to talk to each other unless there is an explicit ALLOW policy.
    """
    assert ops_test.model
    istio_system_model = ops_test.models.get("istio-system")
    assert istio_system_model

    # toggle hardened mode
    await istio_system_model.model.applications[APP_NAME].set_config({"hardened-mode": str(hardened_mode).lower()})
    await istio_system_model.model.wait_for_idle([APP_NAME], raise_on_error=False, timeout=1000)

    # check if traffic restriction have been applied
    assert_request_returns_http_code(
        ops_test.model.name,
        "sender/0",
        f"http://receiver.{ops_test.model.name}.svc.cluster.local:8080/foo",
        code=403 if hardened_mode else 200,  # connection to service forbidden in hardened-mode
    )


@pytest.mark.abort_on_fail
@pytest.mark.parametrize("auto_allow_waypoint_policy", [True, False])
async def test_auto_allow_waypoint_policy(ops_test: OpsTest, auto_allow_waypoint_policy):
    """Test if the auto-allow-waypoint-policy is applied correctly.

    Tests that, when `auto-allow-waypoint-policy=False` tests the charms on the mesh wont be able to talk to each other via the waypoint even with the existence of explicit ALLOW policies.
    """
    assert ops_test.model
    istio_system_model = ops_test.models.get("istio-system")
    assert istio_system_model

    # explicitly disable hardened-mode as this test would not pass under hardened-mode without additional policies
    await istio_system_model.model.applications[APP_NAME].set_config({"hardened-mode": "false"})

    # toggle auto-allow-waypoint-policy
    await istio_system_model.model.applications[APP_NAME].set_config({"auto-allow-waypoint-policy": str(auto_allow_waypoint_policy).lower()})
    await istio_system_model.model.wait_for_idle([APP_NAME], raise_on_error=False, timeout=1000)

    assert_request_returns_http_code(
        ops_test.model.name,
        "sender/0",
        f"http://receiver-0.receiver-endpoints.{ops_test.model.name}.svc.cluster.local:8080/foo",
        code=1 if auto_allow_waypoint_policy else 200,  # when the synthetic allow waypoint policy is in place, other workload connections will be rejected wihtout explicit allow policies
    )
