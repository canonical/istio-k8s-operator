#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from scenario import State


def test_start_charm_active(istio_core_context):
    state = State()
    out = istio_core_context.run("config-changed", state)
    assert out.unit_status.name == "active"
