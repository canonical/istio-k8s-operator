"""istio_metadata.

This library implements endpoint wrappers for the istio-metadata interface.  The istio-metadata interface is used to
transfer information about an instance of Istio, such as its root namespace.  Typically, this is useful for charms that
need details on how to interface with Istio.

## Usage

### Requirer

IstioMetadataRequirer is a wrapper for pulling data from the istio-metadata interface.  To use it in your charm:

* observe the relation-changed and relation-broken events for this relation wherever your charm needs to use this data
  (this endpoint wrapper DOES NOT automatically observe any events)
* wherever you need access to the data, call `IstioMetadataRequirer(...).get_data()`

An example implementation is:

```python
class FooCharm(CharmBase):
    def __init__(self, framework):
        super().__init__(framework)

        istio_metadata = IstioMetadataRequirer(self.model.relations, "istio-metadata")

        self.framework.observe(self.on["istio-metadata"].relation_changed, self._on_istio_metadata_changed)
        self.framework.observe(self.on["istio-metadata"].relation_broken, self._on_istio_metadata_changed)

    def _on_istio_metadata_changed(self):
        data = istio_metadata.get_data()
        ...
```

Where you also add relation to your `charmcraft.yaml` or `metadata.yaml` (note that IstioMetadataRequirer is designed
for relating to a single application and must be used with limit=1 as shown below):

```yaml
requires:
  istio-metadata:
    limit: 1
    interface: istio_metadata
```

### Provider

IstioMetadataProvider is a wrapper for publishing data to charms related using the istio-metadata interface.  Note
that `IstioMetadataProvider` *does not* manage any events, but instead provides a `publish` method for sending data to
all related applications.  Triggering `publish` appropriately is left to the charm author, although generally you want
to do this at least during the `relation_joined` and `leader_elected` events.  An example implementation is:

```python
class FooCharm(CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        self.istio_metadata = IstioMetadataProvider(
            relation_mapping=self.model.relations,
            app=self.app,
            relation_name="istio-metadata",
        )

        self.framework.observe(self.on.leader_elected, self.do_something_to_publish)
        self.framework.observe(self._charm.on["istio-metadata"].relation_joined, self.do_something_to_publish)
        self.framework.observe(self.on.some_event_that_changes_istio_metadata, self.do_something_to_publish)

    def do_something_to_publish(self, e):
        self.istio_metadata.publish(...)
```

Where you also add the following to your `charmcraft.yaml` or `metadata.yaml`:

```yaml
provides:
  istio-metadata:
    interface: istio_metadata
```
"""

import logging
from typing import Optional

from ops import Application, RelationMapping
from pydantic import BaseModel, Field

# The unique Charmhub library identifier, never change it

LIBID = "23257732473e4bb39d47e4a4b4e97bc2"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

PYDEPS = ["pydantic>=2"]

log = logging.getLogger(__name__)

DEFAULT_RELATION_NAME = "istio-metadata"


class IstioMetadataAppData(BaseModel):
    """Data model for the istio-metadata interface."""

    root_namespace: str = Field(
        description="The root namespace for the Istio installation.",
        examples=["istio-system"],
    )


class IstioMetadataRequirer:
    """Endpoint wrapper for the requirer side of the istio-metadata relation."""

    def __init__(
        self,
        relation_mapping: RelationMapping,
        relation_name: str = DEFAULT_RELATION_NAME,
    ) -> None:
        """Initialize the IstioMetadataRequirer object.

        This object is for accessing data from relations that use the istio-metadata interface.  It **does not**
        autonomously handle the events associated with that relation.  It is up to the charm using this object to
        observe those events as they see fit.  Typically, that charm should observe this relation's relation-changed
        event.

        This object is for interacting with a relation that has limit=1 set in charmcraft.yaml.  In particular, the
        get_data method will raise if more than one related application is available.

        Args:
            relation_mapping: The RelationMapping of a charm (typically `self.model.relations` from within a charm
                              object).
            relation_name: The name of the wrapped relation.
        """
        self._charm_relation_mapping = relation_mapping
        self._relation_name = relation_name

    @property
    def relations(self):
        """Return the relation instances for applications related to us on the monitored relation."""
        return self._charm_relation_mapping.get(self._relation_name, ())

    def get_data(self) -> Optional[BaseModel]:
        """Return data for at most one related application, raising if more than one is available.

        Useful for charms that always expect exactly one related application.  It is recommended that those charms also
        set limit=1 for that relation in charmcraft.yaml.  Returns None if no data is available (either because no
        applications are related to us, or because the related application has not sent data).
        """
        relations = self.relations
        if len(relations) == 0:
            return None
        if len(relations) > 1:
            raise ValueError("Cannot get_info when more than one application is related.")

        # Being a little cautious here using getattr and get, since some funny things have happened with relation data
        # in the past.
        raw_data_dict = getattr(relations[0], "data", {}).get(relations[0].app)
        if not raw_data_dict:
            return None

        return IstioMetadataAppData.model_validate(raw_data_dict)


class IstioMetadataProvider:
    """The provider side of the istio-metadata relation."""

    def __init__(
        self,
        relation_mapping: RelationMapping,
        app: Application,
        relation_name: str = DEFAULT_RELATION_NAME,
    ):
        """Initialize the IstioMetadataProvider object.

        This object is for serializing and sending data to a relation that uses the istio-metadata interface - it does
        not automatically observe any events for that relation.  It is up to the charm using this to call publish when
        it is appropriate to do so, typically on at least the charm's leader_elected event and this relation's
        relation_joined event.

        Args:
            relation_mapping: The RelationMapping of a charm (typically `self.model.relations` from within a charm object).
            app: This application.
            relation_name: The name of the relation.
        """
        self._charm_relation_mapping = relation_mapping
        self._app = app
        self._relation_name = relation_name

    @property
    def relations(self):
        """Return the applications related to us under the monitored relation."""
        return self._charm_relation_mapping.get(self._relation_name, ())

    def publish(self, root_namespace: str):
        """Post istio-metadata to all related applications.

        This method writes to the relation's app data bag, and thus should never be called by a unit that is not the
        leader otherwise ops will raise an exception.

        Args:
            root_namespace: The root namespace of the Istio deployment.
        """
        data = IstioMetadataAppData(root_namespace=root_namespace).model_dump(
            mode="json", by_alias=True, exclude_defaults=True, round_trip=True
        )

        for relation in self.relations:
            databag = relation.data[self._app]
            databag.update(data)
