"""TODO: Add a proper docstring here.

* using requirer:
    * handle info changed event  <-- suggest a charm test to confirm this?

* using provider:
    * handle send error
    * use the is_ready()

use the custom event

requires cosl
"""
from typing import List, Optional, Union, TypeVar

from cosl.interfaces.utils import DatabagModelV2, DataValidationError
from ops import CharmBase, Object, EventBase, CharmEvents, EventSource, BoundEvent
from pydantic import BaseModel, Field

# The unique Charmhub library identifier, never change it
LIBID = "17dff53d5bf649f29614365bde32451b"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

DEFAULT_RELATION_NAME = "istio-info"


# This section is a generic implementation of a sender/receiver library for a uni-directional application data relation
# using a provided schema.  It is intended to be moved to a shared library in the future.
#
# See the concrete implementation for the istio-info interface at the bottom of this file.

SchemaType = TypeVar("SchemaType")


# Receiver side

class DataChangedEvent(EventBase):
    """Charm Event triggered when the relation data has changed."""


class ReceiverCharmEvents(CharmEvents):
    """Events raised by the data receiver side of the interface."""
    data_changed = EventSource(DataChangedEvent)


class Receiver(Object):
    """Base class for the receiver side of a generic uni-directional application data relation."""

    on = ReceiverCharmEvents()

    def __init__(
            self,
            charm: CharmBase,
            relation_name: str,
            schema: SchemaType,
            refresh_event: Optional[Union[BoundEvent, List[BoundEvent]]] = None,
    ) -> None:
        """Initialize the Receiver object.

        Args:
            charm: The charm instance that the relation is attached to.
            relation_name: The name of the relation.
            schema: The schema to use for the data model.
            refresh_event: An event or list of events that should trigger this library to process its relations.
                           By default, this charm already observes the relation_changed event.
        """
        super().__init__(charm, relation_name)

        self._charm = charm
        self._relation_name = relation_name
        self._schema = schema

        if not refresh_event:
            refresh_event = []
        if isinstance(refresh_event, BoundEvent):
            refresh_event = [refresh_event]
        for ev in refresh_event:
            self.framework.observe(ev, self.on_relation_changed)

        self.framework.observe(
            self._charm.on[self._relation_name].relation_changed,
            self.on_relation_changed
        )

    def __len__(self):
        """Return the number of related applications."""
        return len(self.get_relations())

    def on_relation_changed(self, _: EventBase) -> None:
        """Handle when the remote application data changed."""
        self.on.data_changed.emit()

    def get_relations(self):
        """Return the relation instances for applications related to us on the monitored relation."""
        return self._charm.model.relations.get(self._relation_name, tuple())

    def get_data(self) -> Optional[SchemaType]:
        """Return data for at most one related application, raising if more than one is available.

        Useful for charms that always expect exactly one related application.  It is recommended that those charms also
        set limit=1 for that relation in charmcraft.yaml.  Returns None if no data is available (either because no
        applications are related to us, or because the related application has not sent data).
        """
        relations = self.get_relations()
        if len(relations) == 0:
            return None
        elif len(relations) > 1:
            # TODO: Different exception type?
            raise ValueError("Cannot get_info when more than one application is related.")

        raw_data = relations[0].data.get(relations[0].app)
        if raw_data == {}:
            return None

        return self._schema(**raw_data)

    def get_data_from_all_relations(self) -> List[SchemaType]:
        """Return a list of data objects from all relations."""
        relations = self.get_relations()
        info_list = [None] * len(relations)
        for i, relation in enumerate(relations):
            data_dict = relation.data.get(relation.app)
            if data_dict == {}:
                # No data - leave this as None
                continue
            info_list[i] = self._schema(**data_dict)
        return info_list


# Sender

class Sender(Object):
    """Base class for the sending side of a generic uni-directional application data relation."""

    def __init__(
            self,
            charm: CharmBase,
            data: SchemaType,
            relation_name: str = DEFAULT_RELATION_NAME,
            refresh_event: Optional[Union[BoundEvent, List[BoundEvent]]] = None,
    ) -> None:
        """Initialize the IstioInfoProvider object.

        Args:
            charm: The charm instance.
            data: An instance of the data sent on this relation.
            relation_name: The name of the relation.
            refresh_event: An event or list of events that should trigger the library to publish data to its relations.
                           By default, this charm already observes the relation_joined and on_leader_elected events.
        """
        super().__init__(charm, relation_name)

        self._charm = charm
        self._data = data
        self._relation_name = relation_name

        if not refresh_event:
            refresh_event = []
        if isinstance(refresh_event, BoundEvent):
            refresh_event = [refresh_event]
        for ev in refresh_event:
            self.framework.observe(ev, self.handle_send_data_event)

        self.framework.observe(
            self._charm.on[self._relation_name].relation_joined,
            self.handle_send_data_event
        )
        # Observe leader elected events because only the leader should send data, and we don't want to miss a case where
        # the relation_joined event happens during a leadership change.
        self.framework.observe(
            self._charm.on.leader_elected,
            self.handle_send_data_event
        )

    def handle_send_data_event(self, _: EventBase) -> None:
        """Handle events that should send data to the relation."""
        if self._charm.unit.is_leader():
            self.send_data()

    def _get_relations(self):
        """Return the applications related to us under the monitored relation."""
        return self._charm.model.relations.get(self._relation_name, tuple())

    def send_data(self):
        """Post istio-info to all related applications.

        If the calling charm needs to handle cases where the data cannot be sent, it should observe the
        send_info_failed event.  This, however, is better handled by including a check on the is_ready method
        in the charm's collect_status event.
        """
        info_relations = self._get_relations()
        for relation in info_relations:
            self._data.dump(relation.data[self._charm.app])

    def _is_relation_data_up_to_date(self):
        """Confirm that the Istio info data we should publish is published to all related applications."""
        expected_app_data = self._data
        for relation in self._get_relations():
            try:
                app_data = self._data.__class__.load(relation.data[self._charm.app])
            except DataValidationError:
                return False
            if app_data != expected_app_data:
                return False
        return True

    def is_ready(self):
        """Return whether the data has been published to all related applications.

        Useful for charms that handle the collect_status event.
        """
        return self._is_relation_data_up_to_date()


# Concrete implementation for istio-info requirer and provider

# Interface schema

class IstioInfoAppData(DatabagModelV2, BaseModel):
    """Data model for the istio-info interface."""

    root_namespace: str = Field(
        description="The root namespace for the Istio installation.",
        examples=["istio-system"],
    )


class IstioInfoRequirer(Receiver):
    """Class for handling the receiver side of the istio-info relation."""

    def __init__(
            self,
            charm: CharmBase,
            relation_name: str = DEFAULT_RELATION_NAME,
            refresh_event: Optional[Union[BoundEvent, List[BoundEvent]]] = None,
    ) -> None:
        """Initialize the IstioInfoRequirer object.

        Args:
            charm: The charm instance.
            relation_name: The name of the relation.
            refresh_event: An event or list of events that should trigger the library to process its relations.
                           By default, this charm already observes the relation_changed event.
        """
        super().__init__(charm, relation_name, IstioInfoAppData, refresh_event)


class IstioInfoProvider(Sender):
    """Class for handling the sending side of the istio-info relation."""

    def __init__(
            self,
            charm: CharmBase,
            root_namespace: str,
            relation_name: str = DEFAULT_RELATION_NAME,
            refresh_event: Optional[Union[BoundEvent, List[BoundEvent]]] = None,
    ) -> None:
        """Initialize the IstioInfoProvider object.

        Args:
            charm: The charm instance.
            root_namespace: The root namespace for the Istio installation.
            relation_name: The name of the relation.
            refresh_event: An event or list of events that should trigger the library to publish data to its relations.
                           By default, this charm already observes the relation_joined and on_leader_elected events.
        """
        data = IstioInfoAppData(root_namespace=root_namespace)
        super().__init__(charm, data, relation_name, refresh_event)
