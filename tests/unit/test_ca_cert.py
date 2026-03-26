#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tests for CA certificate trust via the jwks-ca-cert relation."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from scenario import Relation, State

from charm import IstioCoreCharm

SAMPLE_CA_CERT_1 = """-----BEGIN CERTIFICATE-----
MIIBdTCCARqgAwIBAgIRAMPx/GDYAt1V3FdGMOjANOYwCgYIKoZIzj0EAwIwHDEa
MBgGA1UEAxMRdGVzdC1jYS1jZXJ0LW9uZTAeFw0yNDA1MDEwMDAwMDBaFw0yNTA1
MDEwMDAwMDBaMBwxGjAYBgNVBAMTEXRlc3QtY2EtY2VydC1vbmUwWTATBgcqhkjO
PQIBBggqhkjOPQMBBwNCAAR0test1AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAo0IwQDAOBgNVHQ8BAf8EBAMCAQYwDwYDVR0TAQH/BAUwAwEB
/zAdBgNVHQ4EFgQU0test1AAAAAAAAAAAAAAAAAAAAAwCgYIKoZIzj0EAwIDSQAw
RgIhANtest1AAAAAAAAAAAAAAAAAAAAAAAAAAAIhANtest1AAAAAAAAAAAAAAAA
-----END CERTIFICATE-----"""

SAMPLE_CA_CERT_2 = """-----BEGIN CERTIFICATE-----
MIIBdTCCARqgAwIBAgIRAMPx/GDYAt1V3FdGMOjANOYwCgYIKoZIzj0EAwIwHDEa
MBgGA1UEAxMRdGVzdC1jYS1jZXJ0LXR3bzAeFw0yNDA1MDEwMDAwMDBaFw0yNTA1
MDEwMDAwMDBaMBwxGjAYBgNVBAMTEXRlc3QtY2EtY2VydC10d28wWTATBgcqhkjO
PQIBBggqhkjOPQMBBwNCAAR0test2AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAo0IwQDAOBgNVHQ8BAf8EBAMCAQYwDwYDVR0TAQH/BAUwAwEB
/zAdBgNVHQ4EFgQU0test2AAAAAAAAAAAAAAAAAAAAAwCgYIKoZIzj0EAwIDSQAw
RgIhANtest2AAAAAAAAAAAAAAAAAAAAAAAAAAAIhANtest2AAAAAAAAAAAAAAAA
-----END CERTIFICATE-----"""


@pytest.fixture(scope="function")
def jwks_ca_cert_relation():
    """Return a jwks-ca-cert relation with two CA certificates."""
    return Relation(
        "jwks-ca-cert",
        remote_app_data={
            "certificates": json.dumps(sorted([SAMPLE_CA_CERT_1, SAMPLE_CA_CERT_2])),
            "version": json.dumps(1),
        },
    )


@pytest.fixture(scope="function")
def jwks_ca_cert_relation_single():
    """Return a jwks-ca-cert relation with a single CA certificate."""
    return Relation(
        "jwks-ca-cert",
        remote_app_data={
            "certificates": json.dumps([SAMPLE_CA_CERT_1]),
            "version": json.dumps(1),
        },
    )


def test_get_ca_certificates_empty(istio_core_context):
    """No jwks-ca-cert relation returns empty string."""
    state = State(relations=[], leader=True)
    with istio_core_context(istio_core_context.on.update_status(), state) as mgr:
        charm: IstioCoreCharm = mgr.charm
        assert charm._get_ca_certificates() == ""


def test_get_ca_certificates_with_certs(istio_core_context, jwks_ca_cert_relation):
    """jwks-ca-cert relation with certs returns sorted PEM bundle."""
    state = State(relations=[jwks_ca_cert_relation], leader=True)
    with istio_core_context(istio_core_context.on.update_status(), state) as mgr:
        charm: IstioCoreCharm = mgr.charm
        result = charm._get_ca_certificates()
        assert SAMPLE_CA_CERT_1 in result
        assert SAMPLE_CA_CERT_2 in result
        # Verify it's a sorted bundle
        certs = result.split("\n-----BEGIN CERTIFICATE-----")
        assert len(certs) >= 2


def test_write_jwks_ca_overlay(istio_core_context):
    """Verify overlay YAML is written correctly with the PEM content."""
    state = State(relations=[], leader=True)
    with istio_core_context(istio_core_context.on.update_status(), state) as mgr:
        charm: IstioCoreCharm = mgr.charm
        overlay_path = charm._write_jwks_ca_overlay(SAMPLE_CA_CERT_1)

        content = Path(overlay_path).read_text()
        overlay = yaml.safe_load(content)

        assert overlay["apiVersion"] == "install.istio.io/v1alpha1"
        assert overlay["kind"] == "IstioOperator"
        assert overlay["spec"]["values"]["pilot"]["jwksResolverExtraRootCA"] == SAMPLE_CA_CERT_1


def test_get_istioctl_without_ca(istio_core_context):
    """No CA relation means Istioctl has no overlay files."""
    state = State(relations=[], leader=True)
    with istio_core_context(istio_core_context.on.update_status(), state) as mgr:
        charm: IstioCoreCharm = mgr.charm
        with patch.object(type(charm), "parsed_config", new_callable=lambda: property(lambda self: {
            "platform": "microk8s",
            "cniBinDir": "",
            "cniConfDir": "",
            "auto-allow-waypoint-policy": True,
        })):
            ictl = charm._get_istioctl()
            # No -f flags should be present in args
            assert "-f" not in ictl._args


def test_get_istioctl_with_ca(istio_core_context, jwks_ca_cert_relation_single):
    """CA relation present means Istioctl has overlay file with correct content."""
    state = State(relations=[jwks_ca_cert_relation_single], leader=True)
    with istio_core_context(istio_core_context.on.update_status(), state) as mgr:
        charm: IstioCoreCharm = mgr.charm
        with patch.object(type(charm), "parsed_config", new_callable=lambda: property(lambda self: {
            "platform": "microk8s",
            "cniBinDir": "",
            "cniConfDir": "",
            "auto-allow-waypoint-policy": True,
        })):
            ictl = charm._get_istioctl()
            args = ictl._args
            assert "-f" in args
            overlay_index = args.index("-f")
            overlay_path = args[overlay_index + 1]

            # Verify overlay file content
            content = yaml.safe_load(Path(overlay_path).read_text())
            assert content["spec"]["values"]["pilot"]["jwksResolverExtraRootCA"] == SAMPLE_CA_CERT_1
