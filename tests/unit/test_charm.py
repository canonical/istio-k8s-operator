# Copyright 2024 Canonical Ltd
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import unittest
from unittest.mock import MagicMock, patch

import ops
import ops.testing
from charm import IstioCoreCharm
from kubernetes_resource_handler import KubernetesResourceHandler
from ops.model import ActiveStatus


class MockKubernetesResourceHandler(KubernetesResourceHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lightkube_client = MagicMock()
        self.apply = MagicMock()


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = ops.testing.Harness(IstioCoreCharm)
        self.harness.set_model_name("istio-system")
        self.addCleanup(self.harness.cleanup)

    @patch.object(IstioCoreCharm, "_get_resource_handler")
    def test_charm_begins_active(self, mock_get_resource_handler):
        self.harness.begin_with_initial_hooks()

        # Assert that we've tried to deploy two sets of manifests
        self.assertTrue(mock_get_resource_handler.call_count == 2)
        self.assertTrue(mock_get_resource_handler.return_value.apply.call_count == 2)

        self.assertTrue(isinstance(self.harness.charm.unit.status, ActiveStatus))
