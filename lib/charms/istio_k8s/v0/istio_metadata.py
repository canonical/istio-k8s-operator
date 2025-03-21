"""istio_metadata

This implements provider and requirer sides of the istio-metadata interface, which is used to communicate information
about an Istio installation such as its root namespace.

## Usage

### Requirer

To add this relation to your charm as a requirer, add the following to your `charmcraft.yaml` or `metadata.yaml`:

```yaml
requires:
  istio-metadata:
    # The example below uses the API for when limit=1.  If you need to support multiple related applications, remove
    # this and use the list-based data accessor method.
    limit: 1
    interface: istio_metadata
```

To handle the relation events in your charm, use `IstioMetadataRequirer`.  That object handles all relation events for
this relation, and emits a `DataChangedEvent` when data changes the charm might want to react to occur.  To set it up,
instantiate an `IstioMetadataRequirer` object in your charm's `__init__` method and observe the `DataChangedEvent`:

```python
class FooCharm(CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        # Create the IstioMetadataRequirer instance, providing the relation name you've used
        self.istio_metadata = IstioMetadataRequirer(charm=self, relation_name="istio-metadata")
        self.framework.observe(self.istio_metadata.on.data_changed, self.do_something_with_metadata)
```

To access the data elsewhere in the charm, use the provided data accessors.  These return `IstioMetadataAppData`
objects:

```python
class FooCharm(CharmBase):
    ...
    # If using limit=1
    def do_something_with_metadata(self):
        # Get exactly one related application's data, raising if more than one is available
        # note: if not using limit=1, see .get_data_from_all_relations()
        metadata = self.istio_metadata.get_data()
        if metadata is None:
            self.log("No metadata available yet")
            return
        self.log(f"Got Istio's root_namespace: {metadata.root_namespace}")
```

### Provider

To add this relation to your charm as a provider, add the following to your `charmcraft.yaml` or `metadata.yaml`:

```yaml
provides:
  istio-metadata:
    interface: istio_metadata
```

To handle the relation events in your charm, use `IstioMetadataProvider`.  That object sends data to all related
requirers automatically when applications join.  To set it up, instantiate an `IstioMetadataProvider` object in your
charm's `__init__` method:

```python
class FooCharm(CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        # Create the IstioMetadataProvider instance, providing the root namespace for the Istio installation
        self.istio_metadata = IstioMetadataProvider(
            charm=self,
            root_namespace=self.model.name,
            relation_name="istio-metadata',
        )
```
"""


from typing import List, Optional, Union

from charm_relation_building_blocks.relation_handlers import Receiver, Sender
# import and re-export these classes from the relation_handlers module, in case the user needs them
from charm_relation_building_blocks.relation_handlers import DataChangedEvent as DataChangedEvent  # ignore: F401
from charm_relation_building_blocks.relation_handlers import ReceiverCharmEvents as ReceiverCharmEvents  # ignore: F401

from ops import CharmBase, BoundEvent
from pydantic import BaseModel, Field

# The unique Charmhub library identifier, never change it
LIBID = "17dff53d5bf649f29614365bde32451b"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

DEFAULT_RELATION_NAME = "istio-metadata"


# Interface schema

class IstioMetadataAppData(BaseModel):
    """Data model for the istio-metadata interface."""

    root_namespace: str = Field(
        description="The root namespace for the Istio installation.",
        examples=["istio-system"],
    )


class IstioMetadataRequirer(Receiver):
    """Class for handling the receiver side of the istio-metadata relation."""

    # inherits the events:
    # on = ReceiverCharmEvents()  # type: ignore[reportAssignmentType]
    #

    def __init__(
            self,
            charm: CharmBase,
            relation_name: str = DEFAULT_RELATION_NAME,
            refresh_event: Optional[Union[BoundEvent, List[BoundEvent]]] = None,
    ) -> None:
        """Initialize the IstioMetadataRequirer object.

        Args:
            charm: The charm instance.
            relation_name: The name of the relation.
            refresh_event: An event or list of events that should trigger the library to process its relations.
                           By default, this charm already observes the relation_changed event.
        """
        super().__init__(charm, relation_name, IstioMetadataAppData, refresh_event)


class IstioMetadataProvider(Sender):
    """Class for handling the sending side of the istio-metadata relation."""

    def __init__(
            self,
            charm: CharmBase,
            root_namespace: str,
            relation_name: str = DEFAULT_RELATION_NAME,
            refresh_event: Optional[Union[BoundEvent, List[BoundEvent]]] = None,
    ) -> None:
        """Initialize the IstioMetadataProvider object.

        Args:
            charm: The charm instance.
            root_namespace: The root namespace for the Istio installation.
            relation_name: The name of the relation.
            refresh_event: An event or list of events that should trigger the library to publish data to its relations.
                           By default, this charm already observes the relation_joined and on_leader_elected events.
        """
        data = IstioMetadataAppData(root_namespace=root_namespace)
        super().__init__(charm, data, relation_name, refresh_event)
