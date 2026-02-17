#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for control plane status checks."""

from unittest.mock import MagicMock, patch

import ops
from scenario import State


def test_status_blocked_cni_not_ready(istio_core_context):
    """CNI not ready shows blocked status with platform mismatch hint."""
    mock_ds = MagicMock()
    mock_ds.status.desiredNumberScheduled = 1
    mock_ds.status.numberReady = 0

    with patch("src.charm.IstioCoreCharm.lightkube_client") as mock_client:
        mock_client.get.return_value = mock_ds
        state = istio_core_context.run(
            istio_core_context.on.collect_unit_status(), State(leader=True)
        )

    assert state.unit_status == ops.WaitingStatus(
        "Istio CNI not ready. Possible platform mismatch. Check charm config."
    )


def test_status_active_all_ready(istio_core_context):
    """All components ready shows active status."""
    mock_ds = MagicMock()
    mock_ds.status.desiredNumberScheduled = 1
    mock_ds.status.numberReady = 1

    mock_deploy = MagicMock()
    mock_deploy.spec.replicas = 1
    mock_deploy.status.readyReplicas = 1

    def mock_get(resource_type, name, namespace):
        return mock_deploy if name == "istiod" else mock_ds

    with patch("src.charm.IstioCoreCharm.lightkube_client") as mock_client:
        mock_client.get.side_effect = mock_get
        state = istio_core_context.run(
            istio_core_context.on.collect_unit_status(), State(leader=True)
        )

    assert state.unit_status == ops.ActiveStatus()
