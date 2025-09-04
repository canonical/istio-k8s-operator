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
    bookinfo_details_k8s,
    bookinfo_productpage_k8s,
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
async def test_deploy_dependencies(ops_test: OpsTest):
    """Deploy the required dependencies to test the auth policies from istio-k8s charm."""
    assert ops_test.model

    # deploy the dependency charms
    await ops_test.model.deploy(**asdict(istio_beacon_k8s))
    await ops_test.model.deploy(**asdict(bookinfo_productpage_k8s))
    await ops_test.model.deploy(**asdict(bookinfo_details_k8s))

    # put the dependency charms on the mesh
    await ops_test.model.add_relation(bookinfo_productpage_k8s.application_name, istio_beacon_k8s.application_name)
    await ops_test.model.add_relation(bookinfo_details_k8s.application_name, istio_beacon_k8s.application_name)

    await ops_test.model.wait_for_idle(
        [
            istio_beacon_k8s.application_name,
            bookinfo_details_k8s.application_name,
        ],
        status="active",
        raise_on_error=False,
        timeout=1000,
    )

    await ops_test.model.wait_for_idle(
        [
            bookinfo_productpage_k8s.application_name,
        ],
        status="waiting",
        raise_on_error=False,
        timeout=1000,
    )


@pytest.mark.abort_on_fail
async def test_hardened_mode(ops_test: OpsTest):
    """Test if the hardened-mode is applied correctly.

    Currently this tests the following, when the hardened-mode is enabled, the charms on the mesh wont be able
    to talk to each other unless there is an explicit ALLOW policy.
    """
    assert ops_test.model
    istio_system_model = ops_test.models.get("istio-system")
    assert istio_system_model

    # enable hardened mode
    await istio_system_model.model.applications[APP_NAME].set_config({"hardened-mode": "true"})
    await istio_system_model.model.wait_for_idle([APP_NAME], raise_on_error=False, timeout=1000)

    # check if traffic restriction have been applied
    assert_request_returns_http_code(
        ops_test.model.name,
        f"{bookinfo_productpage_k8s.application_name}/0",
        f"http://{bookinfo_details_k8s.application_name}.{ops_test.model.name}.svc.cluster.local:9080/health",
        code=403,  # connection to service forbidden
    )

    assert_request_returns_http_code(
        ops_test.model.name,
        f"{bookinfo_productpage_k8s.application_name}/0",
        f"http://{bookinfo_details_k8s.application_name}-0.{bookinfo_details_k8s.application_name}-endpoints.{ops_test.model.name}.svc.cluster.local:9080/health",
        code=1,  # connection to worload refused
    )

    # integrate the tester charms to create auth explicit allow auth policies
    await ops_test.model.add_relation(
        f"{bookinfo_productpage_k8s.application_name}:details",
        f"{bookinfo_details_k8s.application_name}:details",
    )

    await ops_test.model.wait_for_idle(
        [
            istio_beacon_k8s.application_name,
            bookinfo_productpage_k8s.application_name,
            bookinfo_details_k8s.application_name,
        ],
        status="active",
        raise_on_error=False,
        timeout=1000,
    )

    assert_request_returns_http_code(
        ops_test.model.name,
        f"{bookinfo_productpage_k8s.application_name}/0",
        f"http://{bookinfo_details_k8s.application_name}.{ops_test.model.name}.svc.cluster.local:9080/health",
        code=200,  # the explicit allow policy should allow this traffic
    )


@pytest.mark.abort_on_fail
async def test_auto_allow_waypoint_policy(ops_test: OpsTest):
    """Test if the auto-allow-waypoint-policy is applied correctly.

    Currently this tests the following, when the auto-allow-waypoint-policy is disabled, the charms on the mesh wont be able
    to talk to each other via the waypoint even with the existence of explicit ALLOW policies.
    """
    assert ops_test.model
    istio_system_model = ops_test.models.get("istio-system")
    assert istio_system_model

    # disable auto-allow-waypoint-policy
    await istio_system_model.model.applications[APP_NAME].set_config({"auto-allow-waypoint-policy": "false"})
    await istio_system_model.model.wait_for_idle([APP_NAME], raise_on_error=False, timeout=1000)

    assert_request_returns_http_code(
        ops_test.model.name,
        f"{bookinfo_productpage_k8s.application_name}/0",
        f"http://{bookinfo_details_k8s.application_name}.{ops_test.model.name}.svc.cluster.local:9080/health",
        code=503,  # traffic dropped at ztunnel as allow waypoint policy does not exist
    )
