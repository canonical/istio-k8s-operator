#!/usr/bin/env python3

# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for managing the Istio service mesh control plane."""

import logging
from pathlib import Path
from typing import List

import ops

# Ignore pyright errors until https://github.com/gtsystem/lightkube/pull/70 is released
from lightkube import Client, codecs  # type: ignore
from lightkube.codecs import AnyResource
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
from lightkube_extensions.batch import KubernetesResourceManager, create_charm_default_labels

from config import CharmConfig
from istioctl import Istioctl

LOGGER = logging.getLogger(__name__)

SOURCE_PATH = Path(__file__).parent

CONTROL_PLANE_COMPONENTS = ["Pilot", "Cni", "Ztunnel"]
CONTROL_PLANE_LABEL = "control-plane"
CONTROL_PLANE_RESOURCE_TYPES = {
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
}
ISTIO_CRDS_COMPONENTS = ["Base"]
ISTIO_CRDS_LABEL = "istio-crds"
ISTIO_CRDS_RESOURCE_TYPES = {CustomResourceDefinition}
GATEWAY_API_CRDS_MANIFEST = [SOURCE_PATH / "manifests" / "gateway-apis-crds.yaml"]
GATEWAY_API_CRDS_LABEL = "gateway-apis-crds"
GATEWAY_API_CRDS_RESOURCE_TYPES = {CustomResourceDefinition}


class IstioCoreCharm(ops.CharmBase):
    """Charm for managing the Istio service mesh control plane."""

    def __init__(self, *args):
        super().__init__(*args)
        self._parsed_config = None
        self._resource_manager_factories = {
            CONTROL_PLANE_LABEL: self._get_control_plane_kubernetes_resource_manager,
            ISTIO_CRDS_LABEL: self._get_crds_kubernetes_resource_manager,
            GATEWAY_API_CRDS_LABEL: self._get_gateway_apis_kubernetes_resource_manager,
        }

        self._lightkube_field_manager: str = self.app.name

        self.framework.observe(self.on.config_changed, self._reconcile)
        self.framework.observe(self.on.remove, self._remove)

    # Event handlers

    def _reconcile(self, _event: ops.ConfigChangedEvent):
        """Reconcile the entire state of the charm."""
        self._reconcile_gateway_api_crds()
        self._reconcile_istio_crds()
        self._reconcile_control_plane()
        # TODO: check if the deployment was successful before setting charm to active
        self.unit.status = ops.ActiveStatus()

    def _remove(self, _event: ops.RemoveEvent):
        """Remove the charm's resources."""
        for name in self._resource_manager_factories:
            krh = self._get_resource_manager(name)
            krh.delete()

    # Properties

    @property
    def parsed_config(self):
        """Return a validated and parsed configuration object."""
        if self._parsed_config is None:
            config = dict(self.model.config.items())
            self._parsed_config = CharmConfig(**config)  # pyright: ignore
        return self._parsed_config.dict(by_alias=True)

    @property
    def lightkube_client(self):
        """Returns a lightkube client configured for this charm."""
        return Client(namespace=self.model.name, field_manager=self._lightkube_field_manager)

    # Helpers

    def _get_resource_manager(self, resource_group: str) -> KubernetesResourceManager:
        """Return an initialized KubernetesResourceManager for the given resource group."""
        return self._resource_manager_factories[resource_group]()

    def _reconcile_control_plane(self):
        """Reconcile the control plane resources."""
        ictl = self._get_istioctl()
        manifests = ictl.manifest_generate(components=CONTROL_PLANE_COMPONENTS)
        resources = codecs.load_all_yaml(manifests, create_resources_for_crds=True)

        # Modify the CNI ConfigMap to add AMBIENT_TPROXY_REDIRECTION
        # TODO: Remove after upgrading to istio 1.24
        resources = self._modify_istio_cni_configmap(resources)
        krm = self._get_resource_manager(CONTROL_PLANE_LABEL)
        # TODO: A validating webhook raises a conflict if force=False.  Why?
        krm.reconcile(resources, force=True)  # pyright: ignore

    def _reconcile_istio_crds(self):
        """Reconcile the Istio CRD resources."""
        # istioctl includes a ServiceAccount in the Base manifest that we don't need.  Build the
        # manifests and remove that resource before passing to KubernetesResourceHandler
        ictl = self._get_istioctl()
        manifests = ictl.manifest_generate(components=ISTIO_CRDS_COMPONENTS)
        resources = codecs.load_all_yaml(manifests, create_resources_for_crds=True)
        if resources[-1].kind == "ServiceAccount":
            resources.pop()
        else:
            raise ValueError(
                f"Expected a ServiceAccount as the last resource in the manifest, found {resources[-1]}"
            )
        krm = self._get_resource_manager(ISTIO_CRDS_LABEL)
        krm.reconcile(resources)  # pyright: ignore

    def _reconcile_gateway_api_crds(self):
        """Reconcile the Gateway API CRD resources."""
        manifests = [manifest_file.read_text() for manifest_file in GATEWAY_API_CRDS_MANIFEST]
        manifest = "\n---\n".join(manifests) + "\n"
        resources = codecs.load_all_yaml(manifest, create_resources_for_crds=True)
        krm = self._get_resource_manager(GATEWAY_API_CRDS_LABEL)
        krm.reconcile(resources)  # pyright: ignore

    def _get_control_plane_kubernetes_resource_manager(self):
        return KubernetesResourceManager(
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=CONTROL_PLANE_LABEL
            ),
            resource_types=CONTROL_PLANE_RESOURCE_TYPES,
            lightkube_client=self.lightkube_client,
            logger=LOGGER,
        )

    def _get_crds_kubernetes_resource_manager(self):
        return KubernetesResourceManager(
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=ISTIO_CRDS_LABEL
            ),
            resource_types=ISTIO_CRDS_RESOURCE_TYPES,  # pyright: ignore
            lightkube_client=self.lightkube_client,
            logger=LOGGER,
        )

    def _get_gateway_apis_kubernetes_resource_manager(self):
        return KubernetesResourceManager(
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=GATEWAY_API_CRDS_LABEL
            ),
            resource_types=GATEWAY_API_CRDS_RESOURCE_TYPES,  # pyright: ignore
            lightkube_client=self.lightkube_client,
            logger=LOGGER,
        )

    def _get_istioctl(self) -> Istioctl:
        """Return an initialized Istioctl instance."""
        # Default settings
        setting_overrides = {
            "components.base.enabled": "true",
            "components.pilot.enabled": "true",
        }

        # Enable Envoy access logs
        # (see https://istio.io/latest/docs/tasks/observability/logs/access-log/)
        setting_overrides["meshConfig.accessLogFile"] = "/dev/stdout"

        # Configure CNI
        # (see https://istio.io/latest/docs/setup/additional-setup/cni/#additional-configuration)
        setting_overrides["components.cni.enabled"] = "true"
        setting_overrides["values.cni.cniBinDir"] = self.parsed_config["cni-bin-dir"]
        setting_overrides["values.cni.cniConfDir"] = self.parsed_config["cni-conf-dir"]

        # Configure the sidecar injector to exclude outbound traffic to all IP ranges.  This is a
        # workaround for CNI limitations with init containers
        # (https://istio.io/latest/docs/setup/additional-setup/cni/#compatibility-with-application-init-containers)
        # This can be removed if we drop support for sidecars
        setting_overrides[
            r"values.sidecarInjectorWebhook.injectedAnnotations.traffic\.sidecar\.istio\.io/excludeOutboundIPRanges"
        ] = "0.0.0.0/0"

        if self.parsed_config["ambient"]:
            setting_overrides["components.ztunnel.enabled"] = "true"
            setting_overrides["values.profile"] = "ambient"

        if self.parsed_config["auto-allow-waypoint-policy"]:
            setting_overrides["values.pilot.env.PILOT_AUTO_ALLOW_WAYPOINT_POLICY"] = "true"

        return Istioctl(
            istioctl_path="./istioctl",
            namespace=self.model.name,
            profile="minimal",
            setting_overrides=setting_overrides,
        )

    # This is a hacky way to get istio CNI to use REDIRECTION instead of TPROXY
    # TODO: Remove this once we upgrade to istio 1.24 as REDIRECTION will be used by default
    # Istioctl doesn't yet support adding env vars directly to the CNI component
    def _modify_istio_cni_configmap(self, resources: List[AnyResource]) -> str:
        """Modify the Istio CNI ConfigMap to include the AMBIENT_TPROXY_REDIRECTION key."""
        key = "AMBIENT_TPROXY_REDIRECTION"
        value = "false"

        # Iterate through the resources to find the istio-cni-config ConfigMap
        for resource in resources:
            if (
                resource.kind == "ConfigMap"
                and resource.metadata.name == "istio-cni-config"  # pyright: ignore
            ):
                resource.data[key] = value  # pyright: ignore
        # Convert the modified resources back to a YAML string
        return resources  # pyright: ignore


if __name__ == "__main__":
    ops.main.main(IstioCoreCharm)
