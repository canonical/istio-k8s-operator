"""istio_ingress_config.

This library implements endpoint wrappers for the istio-ingress-config interface.
Currently, it facilitates the exchange of external authorizer configuration details such as the service name, port and a provider identifier.

Usage:

  Requirer (istio k8s charm):

    class FooCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)

            self.ingress_config = IngressConfigRequirer(self.model.relations, self.app, "istio-ingress-config")
            self.framework.observe(self.on["istio-ingress-config"].relation_changed, self._on_ingress_config_changed)
            self.framework.observe(self.on["istio-ingress-config"].relation_broken, self._on_ingress_config_changed)

        def _on_ingress_config_changed(self, event):
            # Publish a unique ext_authz_provider_name for each connected ingress provider.
            for relation in self.ingress_config.relations:
                if self.ingress_config.is_provider_ready(relation):
                    ext_authz_info = self.ingress_config.get_provider_ext_authz_info(relation)
                    unique_name = generate_provider_name(relation.app.name, ext_authz_info)  # type: ignore
                    self.ingress_config.publish_ext_authz_provider_name(relation, unique_name)

    def generate_provider_name(
        ingress_app_name: str, ext_authz_info: ProviderIngressConfigData
    ) -> str:
        data = f"{ext_authz_info.ext_authz_service_name}:{ext_authz_info.ext_authz_port}"
        stable_hash = hashlib.sha256(data.encode("utf-8")).hexdigest()
        return f"ext_authz-{ingress_app_name}-{stable_hash}"
                    ...

  Provider (istio ingress charm):

    class FooCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            self.ingress_config = IngressConfigProvider(self.model.relations, self.app, "istio-ingress-config")

            self.framework.observe(self.on.leader_elected, self.publish_config)
            self.framework.observe(self.on["istio-ingress-config"].relation_joined, self.publish_config)
            self.framework.observe(self.on.some_event, self.publish_config)

        def publish_config(self, event):
            # Publish the ext_authz service details to our databag.
            self.ingress_config.publish(ext_authz_service_name="my-ext_authz-service", ext_authz_port="8080")
            # Later, fetch the ext_authz provider name generated by the requirer:
            if self.ingress_config.is_requirer_ready():
                provider_name = self.ingress_config.get_ext_authz_provider_name()
                # Do something with provider_name
                ...
"""

import logging
from typing import List, Optional

from ops import Application, Relation, RelationMapping
from pydantic import BaseModel, Field, field_validator

# The unique Charmhub library identifier, never change it
LIBID = "12331b5ac41547e087edd7ac993176ed"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 2

DEFAULT_RELATION_NAME = "istio-ingress-config"

PYDEPS = ["pydantic>=2"]

FAKE_EXT_AUTHZ_SERVICE_NAME = "fake_host"
FAKE_EXT_AUTHZ_PORT = "5432"

log = logging.getLogger(__name__)


class ProviderIngressConfigData(BaseModel):
    """Data model for the provider side of the relation.

    Holds the external authorizer service name and port information.
    """

    ext_authz_service_name: Optional[str] = Field(
        default=None,
        description="The external authorizer service name provided by the ingress charm.",
    )
    ext_authz_port: Optional[str] = Field(
        default=None, description="The port on which the external authorizer service is exposed."
    )

    @field_validator("ext_authz_port")
    @classmethod
    def validate_ext_authz_port(cls, port: Optional[str]) -> Optional[str]:
        """Ensure port is convertible to int."""
        if port is None:
            return port
        try:
            int(port)
        except ValueError:
            raise ValueError(f"ext_authz_port must be convertible to an integer, got {port!r}")
        return port


class RequirerIngressConfigData(BaseModel):
    """Data model for the requirer side of the relation.

    Holds the generated external authorizer provider name and the ingress charm's application name.
    """

    ext_authz_provider_name: Optional[str] = Field(
        default=None,
        description="The generated external authorizer provider name.",
    )


class IngressConfigProvider:
    """Provider side wrapper for the istio-ingress-config relation.

    The provider (ingress charm) publishes its external authorizer service name and port and
    can fetch the generated external authorizer provider name from the requirer's databag.
    """

    def __init__(
        self,
        relation_mapping: RelationMapping,
        app: Application,
        relation_name: str = DEFAULT_RELATION_NAME,
    ) -> None:
        """Initialize the IngressConfigProvider.

        Args:
            relation_mapping: The charm's RelationMapping (typically self.model.relations).
            app: This application (the ingress charm).
            model_name: This application juju model (the ingress charm).
            relation_name: The name of the relation.
        """
        self._charm_relation_mapping = relation_mapping
        self._app = app
        self._relation_name = relation_name

    @property
    def relations(self) -> List[Relation]:
        """Return the relation instances for the monitored relation."""
        return self._charm_relation_mapping.get(self._relation_name, [])

    def publish(
        self, ext_authz_service_name: Optional[str] = None, ext_authz_port: Optional[str] = None
    ):
        """Publish external authorizer configuration data to all related applications.

        Args:
            ext_authz_service_name: The external authorizer service name.
            ext_authz_port: The port number for the external authorizer service.
        """
        data = ProviderIngressConfigData(
            ext_authz_service_name=ext_authz_service_name,
            ext_authz_port=ext_authz_port,
        ).model_dump(mode="json", by_alias=True, exclude_defaults=True, round_trip=True)

        for relation in self.relations:
            databag = relation.data[self._app]
            databag.update(data)
            log.debug("Published provider data: %s to relation: %s", data, relation)

    def clear(self) -> None:
        """Clear the local application databag."""
        # Workaround for https://github.com/juju/juju/issues/19474:
        # TODO: switch the below to databag.clear() when issue is fixed
        # We cannot clear a databag in cross-model relations, so we publish a fake config instead.
        self.publish(
            ext_authz_service_name=FAKE_EXT_AUTHZ_SERVICE_NAME,
            ext_authz_port=FAKE_EXT_AUTHZ_PORT,
        )

    def get_ext_authz_provider_name(self) -> Optional[str]:
        """Fetch the external authorizer provider name generated by the requirer for this provider.

        Returns:
            The generated external authorizer provider name if available, else None.
        """
        if not self.relations:
            return None

        relation = self.relations[0]
        raw_data = getattr(relation, "data", {}).get(relation.app, {})
        if not raw_data:
            return None
        try:
            return RequirerIngressConfigData.model_validate(raw_data).ext_authz_provider_name
        except Exception as e:
            log.debug("Failed to validate requirer data: %s", e)
            return None

    def is_ready(self) -> bool:
        """Guard to check if the generated external authorizer provider name is present.

        Returns:
            True if the external authorizer provider name has been published by the requirer.
        """
        return self.get_ext_authz_provider_name() is not None


class IngressConfigRequirer:
    """Requirer side wrapper for the istio-ingress-config relation.

    The requirer generates and publishes a unique external authorizer provider name
    for a connected ingress charm. It can also check that the provider has published
    its required external authorizer service configuration.
    """

    def __init__(
        self,
        relation_mapping: RelationMapping,
        app: Application,
        relation_name: str = DEFAULT_RELATION_NAME,
    ) -> None:
        """Initialize the IngressConfigRequirer.

        Args:
            relation_mapping: The charm's RelationMapping (typically self.model.relations).
            app: This application.
            relation_name: The name of the relation.
        """
        self._charm_relation_mapping = relation_mapping
        self._app = app
        self._relation_name = relation_name

    @property
    def relations(self) -> List[Relation]:
        """Return the relation instances for the monitored relation."""
        return self._charm_relation_mapping.get(self._relation_name, [])

    def publish_ext_authz_provider_name(self, relation: Relation, unique_name: str) -> None:
        """Publish a unique external authorizer provider name and ingress provider name for a connected ingress charm.

        The provided unique_name is stored as the ext_authz_provider_name, and the ingress charm's
        application name is stored as ingress_provider_name.

        Args:
            relation: A specific relation instance.
            unique_name: The unique external authorizer provider name to publish.
        """
        data = RequirerIngressConfigData(
            ext_authz_provider_name=unique_name,
        ).model_dump(mode="json", by_alias=True, exclude_defaults=True, round_trip=True)
        relation.data[self._app].update(data)
        log.debug("Published requirer data: %s", data)

    def get_provider_ext_authz_info(
        self, relation: Relation
    ) -> Optional[ProviderIngressConfigData]:
        """Retrieve the entire provider app databag for the given relation.

        This method retrieves the data that the provider (ingress charm) has published,
        validates it using the ProviderIngressConfigData model, and returns the model instance.

        Args:
            relation: A specific relation instance.

        Returns:
            An instance of ProviderIngressConfigData if available and valid, else None.
        """
        raw_data = getattr(relation, "data", {}).get(relation.app, {})
        if not raw_data:
            return None
        try:
            return ProviderIngressConfigData.model_validate(raw_data)
        except Exception as e:
            log.debug("Failed to validate provider data: %s", e)
            return None

    def is_fake_authz_config(self, relation: Relation) -> bool:
        """Check if the provider has published a fake external authorization configuration.

        Returns:
            True if any of the provider relations contains fake authz configuration, else False.
        """
        # Workaround for https://github.com/juju/juju/issues/19474:
        # TODO: remove this function entirely as it becomes redunant when issue is fixed
        # We cannot clear a databag in cross-model relations, so we publish a fake config instead.
        provider_info = self.get_provider_ext_authz_info(relation)
        if provider_info is not None:
            if (
                provider_info.ext_authz_service_name == FAKE_EXT_AUTHZ_SERVICE_NAME
                and provider_info.ext_authz_port == FAKE_EXT_AUTHZ_PORT
            ):
                return True
        return False

    def is_ready(self, relation: Relation) -> bool:
        """Guard to check if the provider has published its external authorizer service configuration.

        Args:
            relation: A specific relation instance.

        Returns:
            True if both ext_authz_service_name and ext_authz_port are present in the provider's databag.
        """
        provider_info = self.get_provider_ext_authz_info(relation)
        if provider_info is None:
            return False
        return (
            provider_info.ext_authz_service_name is not None
            and provider_info.ext_authz_port is not None
        )

    def get_ext_authz_provider_name(self, relation: Relation) -> Optional[str]:
        """Retrieve the generated external authorizer provider name for the given provider.

        Args:
            relation: A specific relation instance.

        Returns:
            The external authorizer provider name if available, else None.
        """
        raw_data = getattr(relation, "data", {}).get(self._app, {})
        if not raw_data:
            return None
        try:
            requirer_data = RequirerIngressConfigData.model_validate(raw_data)
            return requirer_data.ext_authz_provider_name
        except Exception as e:
            log.debug("Failed to retrieve external authorizer provider name: %s", e)
            return None
