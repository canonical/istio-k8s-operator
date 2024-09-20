#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import patch

import pytest
from scenario import Context

from src.charm import IstioCoreCharm


@pytest.fixture()
def istio_core_charm():
    # TODO: Python 3.10 lets you have multiple context managers in a single with statement
    with patch.object(IstioCoreCharm, "_reconcile_control_plane"):
        with patch.object(IstioCoreCharm, "_reconcile_istio_crds"):
            with patch.object(IstioCoreCharm, "_reconcile_gateway_api_crds"):
                with patch.object(IstioCoreCharm, "_patch_istio_cni_daemonset"):
                    yield IstioCoreCharm


@pytest.fixture()
def istio_core_context(istio_core_charm):
    yield Context(charm_type=istio_core_charm)
