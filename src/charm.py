#!/usr/bin/env python3

# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for managing the Istio service mesh control plane."""

import logging
from pathlib import Path

import ops
from kubernetes_resource_handler import KubernetesResourceHandler, create_charm_default_labels
from lightkube import Client
from lightkube.resources.admissionregistration_v1 import (
    MutatingWebhookConfiguration,
    ValidatingWebhookConfiguration,
)
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition
from lightkube.resources.apps_v1 import DaemonSet, Deployment
from lightkube.resources.autoscaling_v2 import HorizontalPodAutoscaler
from lightkube.resources.core_v1 import ConfigMap, Service, ServiceAccount
from lightkube.resources.policy_v1 import PodDisruptionBudget
from lightkube.resources.rbac_authorization_v1 import (
    ClusterRole,
    ClusterRoleBinding,
    Role,
    RoleBinding,
)

logger = logging.getLogger(__name__)

source_path = Path(__file__).parent

KUBERNETES_RESOURCE_SPECS = {
    "control-plane": {
        "manifest_templates": [source_path / "manifests" / "control-plane.yaml"],
        "resource_types": {
            ClusterRole,
            ClusterRoleBinding,
            ConfigMap,
            DaemonSet,
            Deployment,
            HorizontalPodAutoscaler,
            MutatingWebhookConfiguration,
            PodDisruptionBudget,
            Role,
            RoleBinding,
            Service,
            ServiceAccount,
            ValidatingWebhookConfiguration,
        },
    },
    "crds": {
        "manifest_templates": [
            source_path / "manifests" / "crds.yaml",
        ],
        "resource_types": {CustomResourceDefinition},
    },
    "gateway-apis": {
        "manifest_templates": [source_path / "manifests" / "gateway-apis.yaml"],
        "resource_types": {CustomResourceDefinition},
    }
}


class IstioCoreCharm(ops.CharmBase):
    """Charm for managing the Istio service mesh control plane."""

    def __init__(self, *args):
        super().__init__(*args)

        self._lightkube_field_manager: str = self.app.name

        self.framework.observe(self.on.config_changed, self._reconcile)
        self.framework.observe(self.on.remove, self._remove)

    def _reconcile(self, _event: ops.ConfigChangedEvent):
        """Reconcile the entire state of the charm."""
        # TODO: make the namespace configurable so we can remove this restriction
        if self.model.name != "istio-system":
            self.unit.status = ops.BlockedStatus(
                "This charm can only be deployed in the istio-system model/namespace."
            )
            return

        # deploy manifests
        for resource_group in KUBERNETES_RESOURCE_SPECS.keys():
            # TODO: Add error handling here that catches auth errors and alerts the user to
            #  how --trust is likely needed
            krh = self._get_resource_handler(resource_group)
            krh.apply()

        # TODO: check if the deployment was successful before setting charm to active
        self.unit.status = ops.ActiveStatus()

    def _remove(self, _event: ops.RemoveEvent):
        """Remove the charm's resources."""
        for resource_group in KUBERNETES_RESOURCE_SPECS.keys():
            krh = self._get_resource_handler(resource_group)
            krh.delete()

    def _get_resource_handler(self, resource_group: str):
        """Return an initialized KubernetesResourceHandler for the given resource group."""
        try:
            kubernetes_spec = KUBERNETES_RESOURCE_SPECS[resource_group]
        except KeyError:
            raise ValueError(
                f"No resources found for resource group: {resource_group}."
                f"  Valid resource groups are: {KUBERNETES_RESOURCE_SPECS.keys()}"
            )

        manifests = kubernetes_spec["manifest_templates"]
        resource_types = kubernetes_spec["resource_types"]

        return KubernetesResourceHandler(
            field_manager=self._lightkube_field_manager,
            template_files=manifests,
            context=None,
            logger=logger,
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=resource_group
            ),
            resource_types=resource_types,
            lightkube_client=Client(),
        )


if __name__ == "__main__":
    ops.main.main(IstioCoreCharm)
