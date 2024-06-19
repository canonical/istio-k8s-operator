#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from scenario import Context

from src.charm import IstioCoreCharm


@pytest.fixture()
def istio_core_charm():
    yield IstioCoreCharm


@pytest.fixture()
def istio_core_context(istio_core_charm):
    yield Context(charm_type=istio_core_charm)
