# Copyright 2024 Canonical Ltd
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import unittest

import ops
import ops.testing
from charm import IstioCoreCharm
from ops.model import ActiveStatus


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = ops.testing.Harness(IstioCoreCharm)
        self.addCleanup(self.harness.cleanup)

    def test_charm_begins_active(self):
        self.harness.begin_with_initial_hooks()
        self.assertTrue(isinstance(self.harness.charm.unit.status, ActiveStatus))
