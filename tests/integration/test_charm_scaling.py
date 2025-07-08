import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from helpers import get_hpa
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
@pytest.mark.parametrize(
    "n_units",
    (
        # Scale up from 1 to 3
        3,
        # Scale down to 2
        2,
    ),
)
async def test_istiod_scaling(ops_test: OpsTest, n_units):
    """Tests that, when the application is scaled, the HPA managing istiod Deployment is scaled too.

    Note: This test is stateful and will leave the deployment at a scale of 2.
    """
    assert ops_test.model
    await ops_test.model.applications[APP_NAME].scale(n_units)
    await ops_test.model.wait_for_idle(
        [APP_NAME],
        status="active",
        timeout=2000,
        raise_on_error=False,
    )


    istiod_hpa = await get_hpa(ops_test.model.name, "istiod")
    assert istiod_hpa is not None
    assert istiod_hpa.spec.minReplicas == n_units  # pyright: ignore
    assert istiod_hpa.spec.maxReplicas == n_units  # pyright: ignore

    assert await wait_for_hpa_current_replicas(
        ops_test.model.name, "istiod", n_units
    ), f"Expected currentReplicas to be {n_units}, got {istiod_hpa.status.currentReplicas}"  # pyright: ignore


@pytest.mark.abort_on_fail
async def wait_for_hpa_current_replicas(
    namespace, hpa_name, expected_replicas, retries=10, delay=10
):
    for _ in range(retries):
        # freshly grab the hpa, but no need to assert its existence as that should be
        # checked by the caller of this method
        istiod_hpa = await get_hpa(namespace, hpa_name)
        if istiod_hpa.status.currentReplicas == expected_replicas:  # pyright: ignore
            return True
        await asyncio.sleep(delay)
    return False
