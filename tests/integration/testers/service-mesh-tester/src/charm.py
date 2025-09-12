#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus
from ops.pebble import Layer

logger = logging.getLogger(__name__)


class ServiceMeshTester(CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        self._ports = [8080, 8081]
        self.unit.set_ports(*self._ports)

        self.framework.observe(self.on.echo_server_pebble_ready, self.on_pebble_ready)

    def on_pebble_ready(self, _):
        container = self.unit.get_container("echo-server")
        if not container.can_connect():
            raise ValueError("container.can_connect() failed during a pebble_ready handler")

        layer = Layer(
            # Start a listener for each defined port
            {
                "summary": "echo server layer",
                "description": "pebble config layer for echo server",
                "services": {
                    f"echo-server-{i}": {
                        "override": "replace",
                        "command": "/bin/echo-server",
                        "startup": "enabled",
                        "environment": {"PORT": str(port)},
                    }
                    for i, port in enumerate(self._ports)
                },
            }
        )

        container.add_layer("echo-server", layer, combine=True)
        container.autostart()
        self.unit.status = ActiveStatus("Echo server running")


if __name__ == "__main__":
    main(ServiceMeshTester)
