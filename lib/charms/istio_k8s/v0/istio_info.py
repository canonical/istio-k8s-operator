"""TODO: Add a proper docstring here.

* using requirer:
    * handle info changed event  <-- suggest a charm test to confirm this?

* using provider:
    * handle send error
    * use the is_ready()


requires cosl
"""
from typing import List, Optional, Union

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


# Interface schema

class IstioInfoAppData(DatabagModelV2, BaseModel):
    """Data model for the istio-info interface."""

    # TODO: Confirm that comparison between these objects works as expected so is_ready below works.

    root_namespace: str = Field(
        description="The root namespace for the Istio installation.",
        examples=["istio-system"],
    )

    # To make it sortable, which is useful for comparing unordered sets like how relation data is stored.
    # TODO: Move this to DatabagModelV2?
    def __lt__(self, other):
        return tuple(self.model_dump().values()) < tuple(other.model_dump().values())

    def __le__(self, other):
        return tuple(self.model_dump().values()) <= tuple(other.model_dump().values())

    def __gt__(self, other):
        return tuple(self.model_dump().values()) > tuple(other.model_dump().values())

    def __ge__(self, other):
        return tuple(self.model_dump().values()) >= tuple(other.model_dump().values())



# Requirer library

class DataChangedEvent(EventBase):
    """Charm Event triggered when the istio-info relation changes."""


class IstioInfoRequirerCharmEvents(CharmEvents):
    """Events raised by the IstioInfoRequirer class."""
    info_changed = EventSource(DataChangedEvent)


class IstioInfoRequirer(Object):
    """Class for handling the requirer side of the istio-info relation."""

    on = IstioInfoRequirerCharmEvents()

    def __init__(
            self,
            charm: CharmBase,
            relation_name: str = DEFAULT_RELATION_NAME,
            refresh_event: Optional[Union[BoundEvent, List[BoundEvent]]] = None,
    ) -> None:
        """Initialize the IstioInfoRequirer object.

        Args:
            charm: The charm instance that the relation is attached to.
            relation_name: The name of the relation.
            refresh_event: An event or list of events that should trigger this library to process its relations.
                           By default, this charm already observes the relation_changed event.
        """
        super().__init__(charm, relation_name)

        self._charm = charm
        self._relation_name = relation_name

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
        self.on.info_changed.emit()

    def get_relations(self):
        """Return the applications related to us under the monitored relation."""
        return self._charm.model.relations.get(self._relation_name, tuple())

    def get_data(self, skip_empty: bool = True) -> Optional[IstioInfoAppData]:
        """Return data for at most one related application, raising if more than one is available.

        Useful for charms that always expect exactly one related application.  It is recommended that those charms also
        set limit=1 for that relation in charmcraft.yaml.  Returns None if no data is available.

        # TODO: Should this raise if no data is available?  Or just return None?

        Args:
            skip_empty: If True, return None if there is a relation that has not yet provided any data.
                        If False, raise a DataValidationError
                        TODO: Is there a better way to handle the False case?  Practically, if we ever don't skip this
                         case it'll be hard for a charm to avoid erroring on transient situations while data is coming
                         but not here yet.
        """
        # TODO: Use get_data_from_all_relations here
        relations = self.get_relations()
        if len(relations) == 0:
            return None
        if len(relations) > 1:
            # TODO: Different exception type?
            raise ValueError("Cannot get_info when more than one application is related.")

        raw_data = relations[0].data.get(relations[0].app)
        if raw_data == {} and skip_empty:
            return None

        return IstioInfoAppData.load(relations[0].data[relations[0].app])

    def get_data_from_all_relations(self, skip_empty: bool = True) -> List[IstioInfoAppData]:
        """Return a list of data objects from all relations.

        Args:
            skip_empty: If True, return None if there is a relation that has not yet provided any data.
                        If False, raise a DataValidationError
                        TODO: is it practical for this to ever be used with skip_empty=False?  Should it be removed?
        """
        info_list = []
        for relation in self.get_relations():
            data = relation.data.get(relation.app)
            if data == {} and skip_empty:
                continue
            info_list.append(IstioInfoAppData.load(relation.data[relation.app]))
        return info_list


# Provider library

class SendInfoFailedEvent(EventBase):
    """Charm Event triggered when the istio-info provider fails to send data successfully."""


class IstioInfoProviderCharmEvents(CharmEvents):
    """Events raised by the IstioInfoProvider class."""
    # TODO: If this becomes frequently used, consider adding more data to the event
    send_info_failed = EventSource(SendInfoFailedEvent)


class IstioInfoProvider(Object):
    """Class for handling the provider side of the istio-info relation."""

    on = IstioInfoProviderCharmEvents()

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
        super().__init__(charm, relation_name)

        self._charm = charm
        self._root_namespace = root_namespace
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
        try:
            if self._charm.unit.is_leader():
                self.send_data()
        except Exception:
            # TODO: This doesn't work!  Syntax is wrong
            self.on.send_info_failed.emit()

    def istio_info(self):
        """Return the istio-info data for the relation."""
        return IstioInfoAppData(
            root_namespace=self._root_namespace,
        )

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
        app_data = self.istio_info()
        for relation in info_relations:
            app_data.dump(relation.data[self._charm.app])

    def _is_relation_data_up_to_date(self):
        """Confirm that the Istio info data we should publish is published to all related applications."""
        expected_app_data = self.istio_info()
        for relation in self._get_relations():
            try:
                app_data = IstioInfoAppData.load(relation.data[self._charm.app])
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
