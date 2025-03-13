#!/usr/bin/env python3

# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for managing the Istio service mesh control plane."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

import ops
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.istio_k8s.v0.istio_ingress_config import IngressConfigRequirer
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm
from charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer

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


@trace_charm(
    tracing_endpoint="_charm_tracing_endpoint",
    extra_types=[
        Istioctl,
        MetricsEndpointProvider,
        GrafanaDashboardProvider,
    ],
    # we don't add a cert because istio does TLS his way
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
        self.telemetry_labels = {
            f"charms.canonical.com/{self.model.name}.{self.app.name}.telemetry": "aggregated"
        }
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

        self.framework.observe(self.on.config_changed, self._reconcile)
        self.framework.observe(self.on.remove, self._remove)
        self.framework.observe(self.on.metrics_proxy_pebble_ready, self._reconcile)
        self.framework.observe(self.workload_tracing.on.endpoint_changed, self._reconcile)
        self.framework.observe(self.workload_tracing.on.endpoint_removed, self._reconcile)
        self.framework.observe(self.on.collect_unit_status, self.on_collect_status)

        self.framework.observe(self.on["istio-ingress-config"].relation_joined, self._reconcile)
        self.framework.observe(self.on["istio-ingress-config"].relation_changed, self._reconcile)
        self.framework.observe(self.on["istio-ingress-config"].relation_broken, self._reconcile)
        self.framework.observe(self.on["istio-ingress-config"].relation_departed, self._reconcile)

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
        # Order here matters, we want to ensure rel data is populated before we reconcile objects/config
        self._publish_oauth_provider_names()

        self._reconcile_gateway_api_crds()
        self._reconcile_istio_crds()
        self._reconcile_control_plane()

        # Ensure the Pebble service is up-to-date
        self._setup_proxy_pebble_service()

    def on_collect_status(self, event: ops.CollectStatusEvent):
        """Handle the collect status event, determining the status of the charm."""
        statuses: List[StatusBase] = []

        # Check if istiod is up
        # TODO: Implement a better check for whether the deployment is actually active.  Atm if we get to this stage, we
        #  know everything was attempted properly and we assume it worked.
        statuses.append(ops.ActiveStatus())

        for status in statuses:
            event.add_status(status)

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

        resources = self._add_metrics_labels(resources)

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

    def _publish_oauth_provider_names(self):
        """Publish the unique OAuth provider name for each ready relation.

        This method iterates over all relations and, if a provider is ready,
        it publishes its unique OAuth provider name.
        """
        for relation in self.ingress_config.relations:
            if self.ingress_config.is_provider_ready(relation):
                ingress_app_name = relation.app.name
                ingress_app_model = self.ingress_config.get_provider_oauth_info(relation).model_name  # type: ignore
                unique_name = f"oauth-{ingress_app_name}-{ingress_app_model}"
                self.ingress_config.publish_oauth_provider_name(relation, unique_name)

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

    def _workload_tracing_provider(self) -> Tuple[List[Any], Dict[str, Any]]:
        """Return a tuple with a list containing the tracing provider and global tracing settings."""
        providers = []
        global_config = {}
        if self.workload_tracing.is_ready():
            workload_tracing_endpoint = self.workload_tracing.get_endpoint("otlp_grpc")
            if workload_tracing_endpoint:
                parsed = urlparse(f"//{workload_tracing_endpoint}")
                providers.append(
                    {
                        "name": "otel-tracing",
                        "opentelemetry": {
                            "port": parsed.port,
                            "service": parsed.hostname,
                        },
                    }
                )
                global_config = {
                    "meshConfig.enableTracing": "true",
                    "meshConfig.defaultProviders.tracing": "otel-tracing",
                    "meshConfig.defaultConfig.tracing.sampling": 100.0,
                }
        return providers, global_config

    def _external_authorizers_providers(self) -> List[Dict[str, Any]]:
        """Return a list of external authorizers provider configurations."""
        providers = []
        for relation in self.ingress_config.relations:
            if self.ingress_config.is_provider_ready(relation):
                oauth_info = self.ingress_config.get_provider_oauth_info(relation)
                oauth_name = self.ingress_config.get_oauth_provider_name(relation)
                if oauth_name and oauth_info:
                    providers.append(
                        {
                            "name": oauth_name,
                            "envoyExtAuthzHttp": {
                                "service": oauth_info.oauth_service_name,
                                "port": oauth_info.oauth_port,
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

    # TODO: Still a WIP due to unmarshaling issue with istioctl
    def _helm_list(self, lst: List[str]) -> str:
        """Convert a list of strings into a Helm-style array literal with quoted items."""
        return "[" + ",".join(f'"{item}"' for item in lst) + "]"

    # TODO: Still a WIP due to unmarshaling issue with istioctl
    def _helm_map(self, d: Dict[str, str]) -> str:
        """Convert a dictionary into a Helm-style map literal with quoted keys and values."""
        return "{" + ",".join(f'"{k}":"{v}"' for k, v in d.items()) + "}"

    def _build_extension_providers_config(self, providers: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build a flat configuration dictionary for all extension providers."""
        config: Dict[str, Any] = {}
        for idx, provider in enumerate(providers):
            base = f"meshConfig.extensionProviders[{idx}]"
            config[f"{base}.name"] = provider["name"]
            if "opentelemetry" in provider:
                config[f"{base}.opentelemetry.port"] = str(provider["opentelemetry"]["port"])
                config[f"{base}.opentelemetry.service"] = provider["opentelemetry"]["service"]
            if "envoyExtAuthzHttp" in provider:
                ext_http_cfg = provider["envoyExtAuthzHttp"]
                config[f"{base}.envoyExtAuthzHttp.service"] = ext_http_cfg["service"]
                config[f"{base}.envoyExtAuthzHttp.port"] = ext_http_cfg["port"]
                # config[f"{base}.envoyExtAuthzHttp.includeRequestHeadersInCheck"] = self._helm_map(
                #     ext_http_cfg["includeRequestHeadersInCheck"]
                # )
                config[f"{base}.envoyExtAuthzHttp.headersToUpstreamOnAllow"] = self._helm_list(
                    ext_http_cfg["headersToUpstreamOnAllow"]
                )
                config[f"{base}.envoyExtAuthzHttp.headersToDownstreamOnAllow"] = self._helm_list(
                    ext_http_cfg["headersToDownstreamOnAllow"]
                )
                config[f"{base}.envoyExtAuthzHttp.headersToDownstreamOnDeny"] = self._helm_list(
                    ext_http_cfg["headersToDownstreamOnDeny"]
                )
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
        external_providers = self._external_authorizers_providers()

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


if __name__ == "__main__":
    ops.main.main(IstioCoreCharm)
