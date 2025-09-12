#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import subprocess
from dataclasses import dataclass
from typing import Optional

from lightkube.core.client import Client
from lightkube.resources.autoscaling_v2 import HorizontalPodAutoscaler
from tenacity import (
    retry,
    stop_after_delay,
    wait_exponential,
)

logger = logging.getLogger(__name__)


@dataclass
class CharmDeploymentConfiguration:
    entity_url: str  # aka charm name or local path to charm
    application_name: str
    channel: str
    trust: bool
    config: Optional[dict] = None


istio_beacon_k8s = CharmDeploymentConfiguration(
    entity_url="istio-beacon-k8s", application_name="istio-beacon-k8s", channel="2/edge", trust=True
)


async def get_hpa(namespace: str, hpa_name: str) -> Optional[HorizontalPodAutoscaler]:
    """Retrieve the HPA resource so we can inspect .spec and .status directly.

    Args:
        namespace: Namespace of the HPA resource.
        hpa_name: Name of the HPA resource.

    Returns:
        The HorizontalPodAutoscaler object or None if not found / on error.
    """
    try:
        c = Client()
        return c.get(HorizontalPodAutoscaler, namespace=namespace, name=hpa_name)
    except Exception as e:
        logger.error("Error retrieving HPA %s: %s", hpa_name, e, exc_info=True)
        return None


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_delay(120), reraise=True
)
def assert_request_returns_http_code(
    model: str, source_unit: str, target_url: str, method: str = "get", code: int = 200
):
    """Get the status code for a request from a source unit to a target URL on a given method.

    Note that if the request fails (ex: python script raises an exception) the exit code will be returned.
    """
    logger.info(f"Checking {source_unit} -> {target_url} on {method}")
    try:
        result = subprocess.run(
            ["juju", "ssh", "-m", model, source_unit,
             f'curl -X {method.upper()} -s -o /dev/null -w "%{{http_code}}" {target_url}'],
            capture_output=True,
            text=True,
            check=True
        )
        returned_code = int(result.stdout.strip())
    except subprocess.CalledProcessError as e:
        logger.warning(f"Got exit code {e.returncode} executing juju ssh")
        logger.warning(f"STDOUT: {e.stdout}")
        logger.warning(f"STDERR: {e.stderr}")
        returned_code = e.returncode

    logger.info(
        f"Got {returned_code} for {source_unit} -> {target_url} on {method} - expected {code}"
    )

    assert (
        returned_code == code
    ), f"Expected {code} but got {returned_code} for {source_unit} -> {target_url} on {method}"
