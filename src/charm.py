#!/usr/bin/env python3

# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for managing the Istio service mesh control plane."""

import logging

import ops

logger = logging.getLogger(__name__)


class IstioCoreCharm(ops.CharmBase):
    """Charm for managing the Istio service mesh control plane."""

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.config_changed, self._reconcile)

    def _reconcile(self, event: ops.ConfigChangedEvent):
        """Reconcile the entire state of the charm."""
        self.unit.status = ops.BlockedStatus("Not yet implemented")


if __name__ == "__main__":
    ops.main.main(IstioCoreCharm)
