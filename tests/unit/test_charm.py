# Copyright 2024 Canonical Ltd
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

from unittest.mock import MagicMock, patch

import ops
import ops.testing
import pytest
from lightkube_extensions.batch import KubernetesResourceManager
from ops.model import ActiveStatus

from charm import IstioCoreCharm


class MockKubernetesResourceManager(KubernetesResourceManager):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lightkube_client = MagicMock()
        self.apply = MagicMock()


@pytest.fixture()
def harness():
    harness = ops.testing.Harness(IstioCoreCharm)
    harness.set_model_name("istio-system")
    yield harness
    harness.cleanup()


class TestCharm:
    @patch.object(IstioCoreCharm, "_reconcile_gateway_api_crds")
    @patch.object(IstioCoreCharm, "_reconcile_istio_crds")
    @patch.object(IstioCoreCharm, "_reconcile_control_plane")
    def test_charm_begins_active(
        self,
        _reconcile_control_plane,
        _reconcile_istio_crds,
        _reconcile_gateway_api_crds,
        harness,
    ):
        harness.begin_with_initial_hooks()

        assert isinstance(harness.charm.unit.status, ActiveStatus)

    def test_charm_config_parsing(self, harness):
        """Assert that the default configuration can be validated and is accessible."""
        harness.begin()

        parsed_config = harness.charm.parsed_config
        # Assert an example config is as expected
        assert parsed_config["ambient"]
