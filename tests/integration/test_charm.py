#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import dataclasses
import json
import logging
from collections import namedtuple
from pathlib import Path
from typing import List

import pytest
import yaml
from lightkube import ApiError, Client
from lightkube.models.core_v1 import EnvVar
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition
from lightkube.resources.apps_v1 import DaemonSet, Deployment
from lightkube.resources.core_v1 import ConfigMap
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
    await asyncio.gather(
        ops_test.model.deploy(
            istio_core_charm, resources=resources, application_name=APP_NAME, trust=True
        ),
        ops_test.model.wait_for_idle(
            apps=[APP_NAME], status="active", raise_on_blocked=True, timeout=1000
        ),
    )


@pytest.mark.abort_on_fail
async def test_istio_is_deployed(ops_test: OpsTest):
    """Assert that the Istio control plane is deployed."""
    is_istiod_up_result = is_istiod_up(namespace=ops_test.model.name)
    assert is_istiod_up_result.success, is_istiod_up_result.message

    do_istio_crds_exist_result = do_istio_crds_exist()
    assert do_istio_crds_exist_result.success, do_istio_crds_exist_result.message


@pytest.mark.abort_on_fail
async def test_ambient_mode_enabled(ops_test: OpsTest):
    is_ambient_mode_enabled_result = is_ambient_mode_enabled(namespace=ops_test.model.name)
    assert is_ambient_mode_enabled_result.success, is_ambient_mode_enabled_result.message

    is_ztunnel_up_result = is_ztunnel_up(namespace=ops_test.model.name)
    assert is_ztunnel_up_result.success, is_ztunnel_up_result.message


@pytest.mark.abort_on_fail
async def test_gateway_api_crds(ops_test: OpsTest):
    """Assert that the Gateway-API CRDs are deployed."""
    do_gateway_api_crds_exist_result = do_gateway_api_crds_exist()
    assert do_gateway_api_crds_exist_result.success, do_gateway_api_crds_exist_result.message


async def test_istio_metadata_relation(ops_test: OpsTest, istio_metadata_requirer_charm):
    """Test the IstioMetadata relation works as expected in attachment and removal."""
    metadata_requirer_application = "istio-metadata-requirer"
    await ops_test.model.deploy(
        istio_metadata_requirer_charm, application_name=metadata_requirer_application
    )
    tester_application = ops_test.model.applications[metadata_requirer_application]
    await ops_test.model.add_relation(APP_NAME, metadata_requirer_application)

    # Wait for the relation to be established
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", raise_on_blocked=True, timeout=60
    )

    await check_tester_data(tester_application, {"root_namespace": ops_test.model.name})

    # Remove the relation and confirm the data is gone
    await ops_test.model.applications[APP_NAME].remove_relation(
        f"{APP_NAME}:istio-metadata", metadata_requirer_application
    )
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", raise_on_blocked=True, timeout=60
    )

    await check_tester_data(tester_application, {})


async def check_tester_data(tester_application, expected_data):
    # Check the relation data
    action = await tester_application.units[0].run_action(
        "get-metadata",
    )
    action_result = await action.wait()
    assert action_result.status == "completed"
    assert action_result.results["relation-data"] == json.dumps(expected_data)


async def test_removal(ops_test: OpsTest):
    """Test the istio-operators can be removed without errors."""
    # NOTE: the istio-gateway charm has to be removed before istio-pilot since
    # the latter contains all the CRDs that istio-gateway depends on.
    await ops_test.model.remove_application(APP_NAME, block_until_done=True)

    is_istiod_up_result = is_istiod_up(namespace=ops_test.model.name)
    assert is_istiod_up_result.success is False, "istiod is still running"

    do_istio_crds_exist_result = do_istio_crds_exist()
    assert do_istio_crds_exist_result.success is False, "istio CRDs still exist"


@dataclasses.dataclass
class BoolTestResult:
    def __init__(self, success: bool, message: str = ""):
        self.success = success
        self.message = message

    def __bool__(self):
        """Bool of this object depends on the success of the test."""
        return self.success


def is_istiod_up(namespace: str) -> BoolTestResult:
    """Assert that the Istiod deployment is up and running."""
    lc = Client()
    try:
        istiod = lc.get(Deployment, namespace=namespace, name="istiod")
    except ApiError as e:
        if e.status.code == 404:
            return BoolTestResult(success=False, message="istiod deployment not found")
        raise e

    return is_deployment_ready(istiod)


def is_deployment_ready(resource: Deployment) -> BoolTestResult:
    """Return True if the StatefulSet is ready, else raises an Exception."""
    ready_replicas = resource.status.readyReplicas
    replicas_expected = resource.spec.replicas
    if ready_replicas == replicas_expected:
        return BoolTestResult(success=True)

    error_message = (
        f"Deployment {resource.metadata.name} in namespace "
        f"{resource.metadata.namespace} has {ready_replicas} readyReplicas, "
        f"expected {replicas_expected}"
    )
    return BoolTestResult(success=False, message=error_message)


def do_istio_crds_exist() -> BoolTestResult:
    """Assert that the Istio CRDs are deployed by confirming a sample exists."""
    return do_crds_exist(crd_names=["authorizationpolicies.security.istio.io"])


def do_gateway_api_crds_exist() -> BoolTestResult:
    """Assert that the Gateway-API CRDs are deployed by confirming a sample exists."""
    expected_crds = [
        "gateways.gateway.networking.k8s.io",
        "httproutes.gateway.networking.k8s.io",
    ]
    return do_crds_exist(crd_names=expected_crds)


def do_crds_exist(crd_names: List[str]) -> BoolTestResult:
    """Assert that all CRDs of the given names exist."""
    lc = Client()
    for name in crd_names:
        try:
            lc.get(CustomResourceDefinition, name=name)
        except ApiError as e:
            if e.status.code == 404:
                return BoolTestResult(success=False, message=f"CRD {name} not found")
            raise e
    return BoolTestResult(success=True)


def does_env_include_key_value(env: List[EnvVar], key: str, value: str) -> bool:
    """Return True if the envs list includes an env with the given key and value, else False."""
    return any(True for env in env if env.name == key and env.value == value)


def is_ambient_mode_enabled(namespace: str) -> BoolTestResult:
    """Assert that Istio's ambient mode is enabled."""
    lc = Client()

    case = namedtuple("ambient_test_case", ["name", "key", "value", "resource_type"])
    cases = [
        case(name="ztunnel", key="ISTIO_META_ENABLE_HBONE", value="true", resource_type=DaemonSet),
        case(name="istiod", key="PILOT_ENABLE_AMBIENT", value="true", resource_type=Deployment),
    ]

    for case in cases:
        component = lc.get(case.resource_type, namespace=namespace, name=case.name)
        if not does_env_include_key_value(
            component.spec.template.spec.containers[0].env, case.key, case.value
        ):
            return BoolTestResult(
                success=False,
                message=f"Ambient mode is not enabled - {case.name}'s {case.key} env var is not set to {case.value}",
            )

    # Assert istio-cni is configured for ambient mode
    cm = lc.get(ConfigMap, "istio-cni-config", namespace=namespace)
    cni_ambient_enabled = cm.data.get("AMBIENT_ENABLED")
    if cni_ambient_enabled != "true":
        return BoolTestResult(
            success=False,
            message=f"Ambient mode is not enabled - istio-cni-node's ConfigMap does not have AMBIENT_ENABLED=true, found 'AMBIENT_ENABLED={cni_ambient_enabled}",
        )

    return BoolTestResult(success=True)


def is_ztunnel_up(namespace: str) -> BoolTestResult:
    """Assert that Istio's ztunnel mode is enabled."""
    lc = Client()
    ds = lc.get(DaemonSet, namespace=namespace, name="ztunnel")
    return is_daemonset_ready(ds)


def is_daemonset_ready(ds: DaemonSet) -> BoolTestResult:
    """Return True if the DaemonSet is ready, else raises an Exception."""
    desired_scheduled = ds.status.desiredNumberScheduled
    number_ready = ds.status.numberReady
    if desired_scheduled == number_ready:
        return BoolTestResult(success=True)

    error_message = (
        f"DaemonSet {ds.metadata.name} in namespace "
        f"{ds.metadata.namespace} has {number_ready} ready, "
        f"expected {desired_scheduled}"
    )
    return BoolTestResult(success=False, message=error_message)
