#!/usr/bin/env python3

# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for managing the Istio service mesh control plane."""

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

import ops
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.istio_k8s.v0.istio_ingress_config import (
    IngressConfigRequirer,
)
from charms.istio_k8s.v0.istio_metadata import IstioMetadataProvider
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm
from charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer

# Ignore pyright errors until https://github.com/gtsystem/lightkube/pull/70 is released
from lightkube import Client, codecs  # type: ignore
from lightkube.codecs import AnyResource
from lightkube.generic_resource import create_namespaced_resource
from lightkube.models.autoscaling_v2 import (
    CrossVersionObjectReference,
    HorizontalPodAutoscalerSpec,
)
from lightkube.models.meta_v1 import ObjectMeta
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
from ops import StatusBase
from ops.pebble import ChangeError, Layer

from config import CharmConfig
from istioctl import Istioctl

LOGGER = logging.getLogger(__name__)

SOURCE_PATH = Path(__file__).parent

CONTROL_PLANE_COMPONENTS = ["pilot", "cni", "ztunnel"]
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
ISTIO_CRDS_COMPONENTS = ["base"]
ISTIO_CRDS_LABEL = "istio-crds"
ISTIO_CRDS_RESOURCE_TYPES = {CustomResourceDefinition}
GATEWAY_API_CRDS_MANIFEST = [SOURCE_PATH / "manifests" / "gateway-apis-crds.yaml"]
GATEWAY_API_CRDS_LABEL = "gateway-apis-crds"
GATEWAY_API_CRDS_RESOURCE_TYPES = {CustomResourceDefinition}
RESOURCE_TYPES = {
    "AuthorizationPolicy": create_namespaced_resource(
        "security.istio.io",
        "v1",
        "AuthorizationPolicy",
        "authorizationpolicies",
    ),
}
AUTHORIZATION_POLICY_LABEL = "istio-authorization-policy"
AUTHORIZATION_POLICY_RESOURCE_TYPES = {RESOURCE_TYPES["AuthorizationPolicy"]}


@trace_charm(
    tracing_endpoint="_charm_tracing_endpoint",
    extra_types=[
        Istioctl,
        MetricsEndpointProvider,
        GrafanaDashboardProvider,
    ],
    # we don't add a cert because istio does TLS it's way
    # TODO: fix when https://github.com/canonical/istio-beacon-k8s-operator/issues/33 is closed
)
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
        self.telemetry_labels = generate_telemetry_labels(self.app.name, self.model.name)
        self._lightkube_field_manager: str = self.app.name

        # Configure Observability
        self._scraping = MetricsEndpointProvider(
            self,
            jobs=[{"static_configs": [{"targets": ["*:15090"]}]}],
        )
        self.grafana_dashboards = GrafanaDashboardProvider(self)
        self.charm_tracing = TracingEndpointRequirer(
            self, relation_name="charm-tracing", protocols=["otlp_http"]
        )

        self.workload_tracing = TracingEndpointRequirer(
            self, relation_name="workload-tracing", protocols=["otlp_grpc"]
        )
        self._charm_tracing_endpoint = (
            self.charm_tracing.get_endpoint("otlp_http") if self.charm_tracing.relations else None
        )
        self.ingress_config = IngressConfigRequirer(
            relation_mapping=self.model.relations, app=self.app
        )

        self.istio_metadata = IstioMetadataProvider(
            charm=self,
            relation_mapping=self.model.relations,
            app=self.app,
        )

        self.framework.observe(self.on.config_changed, self._reconcile)
        self.framework.observe(self.on.start, self._reconcile)
        self.framework.observe(self.on.remove, self._remove)
        self.framework.observe(self.on.metrics_proxy_pebble_ready, self._reconcile)
        self.framework.observe(self.workload_tracing.on.endpoint_changed, self._reconcile)
        self.framework.observe(self.workload_tracing.on.endpoint_removed, self._reconcile)
        self.framework.observe(self.on.collect_unit_status, self.on_collect_status)
        self.framework.observe(self.on["istio-ingress-config"].relation_changed, self._reconcile)
        self.framework.observe(self.on["istio-ingress-config"].relation_broken, self._reconcile)
        # For istio-metadata
        self.framework.observe(self.on["istio-metadata"].relation_joined, self._reconcile)
        self.framework.observe(self.on.leader_elected, self._reconcile)
        self.framework.observe(self.on["peers"].relation_changed, self._reconcile)
        self.framework.observe(self.on["peers"].relation_departed, self._reconcile)

    def _setup_proxy_pebble_service(self):
        """Define and start the metrics broadcast proxy Pebble service."""
        proxy_container = self.unit.get_container("metrics-proxy")
        if not proxy_container.can_connect():
            return
        proxy_layer = Layer(
            {
                "summary": "Metrics Broadcast Proxy Layer",
                "description": "Pebble layer for the metrics broadcast proxy",
                "services": {
                    "metrics-proxy": {
                        "override": "replace",
                        "summary": "Metrics Broadcast Proxy",
                        "command": f"metrics-proxy --labels {self.format_labels(self.telemetry_labels)}",
                        "startup": "enabled",
                    }
                },
            }
        )

        proxy_container.add_layer("metrics-proxy", proxy_layer, combine=True)

        try:
            proxy_container.replan()
        except ChangeError as e:
            LOGGER.error(f"Error while replanning proxy container: {e}")

    def _reconcile(self, _event: ops.ConfigChangedEvent):
        """Reconcile the entire state of the charm."""
        # Reconciliation can only be attempted by the leader.
        if not self.unit.is_leader():
            return
        # Order here matters, we want to ensure rel data is populated before we reconcile objects/config
        self._publish_ext_authz_provider_names()
        self._publish_istio_metadata()

        self._reconcile_gateway_api_crds()
        self._reconcile_istio_crds()
        self._reconcile_control_plane()
        self._reconcile_authorization_policies()

        # Ensure the Pebble service is up-to-date
        self._setup_proxy_pebble_service()

    def on_collect_status(self, event: ops.CollectStatusEvent):
        """Handle the collect status event, determining the status of the charm."""
        statuses: List[StatusBase] = []

        # Check if istiod is up
        # TODO: Implement a better check for whether the deployment is actually active.  Atm if we get to this stage, we
        #  know everything was attempted properly and we assume it worked.
        active_status_message = ""
        if not self.unit.is_leader():
            active_status_message = "Backup unit; standing by for leader take over"
        statuses.append(ops.ActiveStatus(active_status_message))

        for status in statuses:
            event.add_status(status)

    def _remove(self, _event: ops.RemoveEvent):
        """Remove the charm's resources."""
        if self.unit.is_leader():
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
        resources = []
        unit_count = self.model.app.planned_units()

        # Reconcile an empty resource list if no units are left (unit_count < 1):
        #  - This typically indicates an application removal event; we rely on the remove hook for cleanup.
        #  - Attempting to reconcile with an HPA that sets replicas to zero is invalid.
        #  - This guard exists because some events can call _reconcile before the remove hook runs,
        #    leading to k8s validation webhook errors when planned_units is 0.
        if unit_count > 0:
            # Only the istiod HPA is overridden for scaling it with the charm.
            # Refer this issue for more details: https://github.com/canonical/istio-k8s-operator/issues/22
            hpa_override = self._construct_hpa(unit_count=unit_count)
            manifests = ictl.manifest_generate(
                components=CONTROL_PLANE_COMPONENTS,
                overrides=[
                    hpa_override,
                ]
            )

            resources = codecs.load_all_yaml(manifests, create_resources_for_crds=True)
            resources = self._add_metrics_labels(resources)

        krm = self._get_resource_manager(CONTROL_PLANE_LABEL)
        # TODO: A validating webhook raises a conflict if force=False.  Why?
        krm.reconcile(resources, force=True)  # pyright: ignore

    def _construct_hpa(self, unit_count: int) -> HorizontalPodAutoscaler:
        """Construct a HorizontalPodAutoscaler resource for istiod with required custom specs.

        This HPA is used to scale the istiod workload automatically when the charm scales.
        The scaling is achieved by setting the min and max replica settings in the HPA to be
        the same as the unit count.
        These hpa specs override the default manifest generated by istioctl.
        """
        return HorizontalPodAutoscaler(
            metadata=ObjectMeta(name="istiod", namespace=self.model.name),
            spec=HorizontalPodAutoscalerSpec(
                scaleTargetRef=CrossVersionObjectReference(
                    apiVersion="apps/v1",
                    kind="Deployment",
                    name="istiod",
                ),
                minReplicas=unit_count,
                maxReplicas=unit_count,
            ),
        )

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

    def _publish_ext_authz_provider_names(self):
        """Publish the unique external authorizer provider name for each ready relation.

        This method iterates over all relations and, if a provider is ready,
        it publishes its unique external authorizer provider name.
        """
        for relation in self.ingress_config.relations:
            if self.ingress_config.is_ready(relation):
                unique_name = f"ext_authz-{relation.app.name}"
                self.ingress_config.publish_ext_authz_provider_name(relation, unique_name)

    def _publish_istio_metadata(self):
        """Publish our metadata to all related applications."""
        self.istio_metadata.publish(root_namespace=self.model.name)

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

    def _get_authorization_policy_resource_manager(self):
        return KubernetesResourceManager(
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=AUTHORIZATION_POLICY_LABEL
            ),
            resource_types=AUTHORIZATION_POLICY_RESOURCE_TYPES,  # pyright: ignore
            lightkube_client=self.lightkube_client,
            logger=LOGGER,
        )

    def _workload_tracing_provider(self) -> Tuple[List[Any], Dict[str, Any]]:
        """Return a tuple with the tracing provider and global tracing settings as dictionaries."""
        if not self.workload_tracing.is_ready():
            return [], {}

        if not (endpoint := self.workload_tracing.get_endpoint("otlp_grpc")):
            return [], {}

        parsed = urlparse(f"//{endpoint}")
        provider = {
            "name": "otel-tracing",
            "opentelemetry": {
                "port": parsed.port,
                "service": parsed.hostname,
            },
        }
        global_config = {
            "meshConfig.enableTracing": "true",
            "meshConfig.defaultProviders.tracing[0]": "otel-tracing",
            "meshConfig.defaultConfig.tracing.sampling": 100.0,
        }
        return [provider], global_config

    def _external_authorizer_providers(self) -> List[Dict[str, Any]]:
        """Return a list of external authorizers provider configurations."""
        providers = []
        for relation in self.ingress_config.relations:
            if self.ingress_config.is_ready(relation):
                # TODO: Remove the below when https://github.com/juju/juju/issues/19474 is fixed
                # If fake config is detected, return an empty list immediately.
                if self.ingress_config.is_fake_authz_config(relation):
                    return providers

                ext_authz_info = self.ingress_config.get_provider_ext_authz_info(relation)
                providers.append(
                    {
                        "name": f"ext_authz-{relation.app.name}",
                        "envoyExtAuthzHttp": {
                            "service": ext_authz_info.ext_authz_service_name,  # type: ignore
                            "port": ext_authz_info.ext_authz_port,  # type: ignore
                            "includeRequestHeadersInCheck": ["authorization", "cookie"],
                            "headersToUpstreamOnAllow": [
                                "authorization",
                                "path",
                                "x-auth-request-user",
                                "x-auth-request-email",
                                "x-auth-request-access-token",
                            ],
                            "headersToDownstreamOnAllow": ["set-cookie"],
                            "headersToDownstreamOnDeny": ["content-type", "set-cookie"],
                        },
                    }
                )
        return providers

    def _build_extension_providers_config(self, providers: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build a flat configuration dictionary for all extension providers by flattening provider objects."""
        config: Dict[str, Any] = {}
        for idx, provider in enumerate(providers):
            prefix = f"meshConfig.extensionProviders[{idx}]"
            flat = flatten_config(provider, prefix)
            config.update(flat)
        return config

    def _get_istioctl(self) -> Istioctl:
        """Return an initialized Istioctl instance."""
        # Default settings
        setting_overrides = {}

        # Get tracing providers and global tracing settings.
        # TODO: If Tempo is on mesh, Istio won't be able to send traces to Tempo until https://github.com/canonical/istio-k8s-operator/issues/30 is fixed
        # (see https://istio.io/latest/docs/tasks/observability/distributed-tracing/opentelemetry/)
        tracing_providers, global_tracing = self._workload_tracing_provider()

        # Get external authorizers providers.
        external_providers = self._external_authorizer_providers()

        # Combine all providers (order does not matter).
        all_providers = tracing_providers + external_providers

        setting_overrides.update(self._build_extension_providers_config(all_providers))

        # Merge global tracing settings (if any).
        setting_overrides.update(global_tracing)

        # Enable Envoy access logs
        # (see https://istio.io/latest/docs/tasks/observability/logs/access-log/)
        setting_overrides["meshConfig.accessLogFile"] = "/dev/stdout"

        # Ignore the platform setting if it's not set or is empty
        if self.parsed_config["platform"]:
            setting_overrides["values.global.platform"] = self.parsed_config["platform"]

        # Configure the sidecar injector to exclude outbound traffic to all IP ranges.  This is a
        # workaround for CNI limitations with init containers
        # (https://istio.io/latest/docs/setup/additional-setup/cni/#compatibility-with-application-init-containers)
        # This can be removed if we drop support for sidecars
        setting_overrides[
            r"values.sidecarInjectorWebhook.injectedAnnotations.traffic\.sidecar\.istio\.io/excludeOutboundIPRanges"
        ] = "0.0.0.0/0"

        if self.parsed_config["ambient"]:
            setting_overrides["values.profile"] = "ambient"

        if self.parsed_config["auto-allow-waypoint-policy"]:
            setting_overrides["values.pilot.env.PILOT_AUTO_ALLOW_WAYPOINT_POLICY"] = "true"

        return Istioctl(
            istioctl_path="./istioctl",
            namespace=self.model.name,
            profile="empty",
            setting_overrides=setting_overrides,
        )

    def _add_metrics_labels(self, resources: List[AnyResource]) -> List[AnyResource]:
        """Append extra labels to the ztunnel, istio-cni-node, and istiod pods based on METRICS_LABELS."""
        for resource in resources:
            if resource.kind in [
                "DaemonSet",
                "Deployment",
            ] and resource.metadata.name in [  # pyright: ignore
                "ztunnel",
                "istio-cni-node",
                "istiod",
            ]:
                for key, value in self.telemetry_labels.items():
                    resource.spec.template.metadata.labels[key] = value  # pyright: ignore

        return resources

    @staticmethod
    def format_labels(label_dict: Dict[str, str]) -> str:
        """Format a dictionary into a comma-separated string of key=value pairs."""
        return ",".join(f"{key}={value}" for key, value in label_dict.items())

    def _reconcile_authorization_policies(self) -> None:
        """Sync authorization policies."""
        authorization_policies = self._build_authorization_policies()
        krm = self._get_authorization_policy_resource_manager()
        krm.reconcile(authorization_policies)  # type: ignore

    def _build_authorization_policies(self):
        """Build required globally managed authorization policies."""
        authorization_policies = []
        if self.parsed_config["global-allow-nothing-policy"]:
            authorization_policies.append(
                RESOURCE_TYPES["AuthorizationPolicy"](
                    metadata=ObjectMeta(
                        name=f"{self.app.name}-{self.model.name}-policy-global-allow-nothing-l4",
                        namespace=self.model.name,
                    ),
                    spec={}
                )
            )

            authorization_policies.append(
                RESOURCE_TYPES["AuthorizationPolicy"](
                    metadata=ObjectMeta(
                        name=f"{self.app.name}-{self.model.name}-policy-global-allow-nothing-waypoints",
                        namespace=self.model.name,
                    ),
                    spec={
                        "targetRefs": [
                            {
                                "kind": "GatewayClass",
                                "group": "gateway.networking.k8s.io",
                                "name": "istio-waypoint",
                            },
                        ],
                    },
                )
            )
        return authorization_policies


def flatten_config(value: Any, prefix: str = "") -> Dict[str, Any]:
    """Recursively flatten a nested dictionary or list into a dictionary of key/value pairs."""
    flat: Dict[str, Any] = {}
    if isinstance(value, dict):
        for k, v in value.items():
            new_prefix = f"{prefix}.{k}" if prefix else k
            flat.update(flatten_config(v, new_prefix))
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            new_prefix = f"{prefix}[{i}]" if prefix else f"[{i}]"
            flat.update(flatten_config(item, new_prefix))
    else:
        flat[prefix] = value
    return flat


def generate_telemetry_labels(app_name: str, model_name: str) -> Dict[str, str]:
    """Generate telemetry labels for the application, ensuring it is always <=63 characters and usually unique.

    The telemetry labels need to be unique for each application in order to prevent one application from scraping
    another's metrics (eg: istio-beacon scraping the workloads of istio-ingress).  Ideally, this would be done by
    including model_name and app_name in the label key or value, but Kubernetes label keys and values have a 63
    character limit.  This, thus function returns:
    * a label with a key that includes model_name and app_name, if that key is less than 63 characters
    * a label with a key that is truncated to 63 characters but includes a hash of the full model_name and app_name, to
      attempt to ensure uniqueness.

    The hash is included because simply truncating the model or app names may lead to collisions.  Consider if
    istio-beacon is deployed to two different models of names `really-long-model-name1` and `really-long-model-name2`,
    they'd truncate to the same key.  To reduce this risk, we also include a hash of the model and app names which very
    likely differs between two applications.
    """
    key = f"charms.canonical.com/{model_name}.{app_name}.telemetry"
    if len(key) > 63:
        # Truncate the key to fit within the 63-character limit.  Include a hash of the real model_name.app_name to
        # avoid collisions with some other truncated key.
        hash = hashlib.md5(f"{model_name}.{app_name}".encode()).hexdigest()[:10]
        key = f"charms.canonical.com/{model_name[:10]}.{app_name[:10]}.{hash}.telemetry"
    return {
        key: "aggregated",
    }


if __name__ == "__main__":
    ops.main.main(IstioCoreCharm)
