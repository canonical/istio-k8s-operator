from contextlib import nullcontext as does_not_raise

import pytest
from charms.istio_k8s.v0.istio_info import (
    DataChangedEvent,
    IstioInfoAppData,
    IstioInfoProvider,
    IstioInfoRequirer,
)
from ops import CharmBase
from ops.testing import Context, Model, Relation, State

RELATION_NAME = "app-data-relation"
MODEL_NAME = "not-istio-system"


class ProviderCharm(CharmBase):
    META = {
        "name": "provider",
        "provides": {RELATION_NAME: {"interface": RELATION_NAME}},
    }

    def __init__(self, framework):
        super().__init__(framework)
        self.relation_provider = IstioInfoProvider(
            self, root_namespace=MODEL_NAME, relation_name=RELATION_NAME
        )


@pytest.fixture()
def provider_context():
    return Context(charm_type=ProviderCharm, meta=ProviderCharm.META)


class RequirerCharm(CharmBase):
    META = {
        "name": "requirer",
        "requires": {RELATION_NAME: {"interface": "istio-info"}},
    }

    def __init__(self, framework):
        super().__init__(framework)
        self.relation_requirer = IstioInfoRequirer(self, relation_name=RELATION_NAME)


@pytest.fixture()
def requirer_context():
    return Context(charm_type=RequirerCharm, meta=RequirerCharm.META)


def istio_info_test_state(leader: bool, local_app_data: dict = None) -> (Relation, State):
    """Return a testing State that has a single istio-info relation."""
    if local_app_data is None:
        local_app_data = {}

    istio_info_relation = Relation(RELATION_NAME, "istio-info", local_app_data=local_app_data)
    relations = [istio_info_relation]

    state = State(
        relations=relations,
        leader=leader,
        model=Model(name=MODEL_NAME),
    )

    return istio_info_relation, state


def test_provider_sends_data_on_relation_joined(provider_context):
    """Tests that a charm using IstioInfoProvider sends the correct data to the relation on a relation joined event."""
    # Arrange
    istio_info_relation, state = istio_info_test_state(leader=True)

    # Act
    provider_context.run(provider_context.on.relation_joined(istio_info_relation), state=state)

    # Assert
    assert istio_info_relation.local_app_data == {"root_namespace": MODEL_NAME}


def test_provider_sends_data_on_leader_elected(provider_context):
    """Tests that a charm using IstioInfoProvider sends the correct data to the relation on a leader elected event."""
    # Arrange
    istio_info_relation, state = istio_info_test_state(leader=True)

    # Act
    provider_context.run(provider_context.on.leader_elected(), state=state)

    # Assert
    assert istio_info_relation.local_app_data == {"root_namespace": MODEL_NAME}


def test_provider_doesnt_send_data_when_not_leader(provider_context):
    """Tests that a charm using the IstioInfoProvider does not send data if not the leader."""
    # Arrange
    istio_info_relation, state = istio_info_test_state(leader=False)

    events = [
        provider_context.on.relation_joined(istio_info_relation),
        provider_context.on.leader_elected(),
        provider_context.on.config_changed(),  # just to have some other event
    ]
    for event in events:
        # Act
        provider_context.run(event, state=state)

        # Assert
        assert istio_info_relation.local_app_data == {}


@pytest.mark.parametrize(
    "local_app_data",
    [
        {},  # empty data
        {"root_namespace": "not-the-real-namespace"},  # stale data
    ],
)
def test_provider_is_ready(local_app_data, provider_context):
    """Tests that a charm using the IstioInfoProvider correctly assesses whether the data sent is up to date."""
    # Arrange
    istio_info_relation, state = istio_info_test_state(leader=True, local_app_data=local_app_data)

    with provider_context(
        provider_context.on.relation_joined(istio_info_relation), state=state
    ) as manager:
        charm = manager.charm

        # Before executing the event that causes data to be emitted, the relation handler should not be ready
        assert not charm.relation_provider.is_ready()

        # After the data is sent, the provider should indicate ready
        manager.run()
        assert charm.relation_provider.is_ready()


def test_requirer_emits_info_changed_on_relation_data_changes(requirer_context):
    """Tests that a charm using IstioInfoRequirer emits a DataChangedEvent when the relation data changes."""
    # Arrange
    istio_info_relation, state = istio_info_test_state(leader=False)

    # Act
    requirer_context.run(requirer_context.on.relation_changed(istio_info_relation), state=state)

    # Assert we emitted the info changed event
    # Note: emitted_events also includes the event we executed above in .run()
    assert len(requirer_context.emitted_events) == 2
    assert isinstance(requirer_context.emitted_events[1], DataChangedEvent)


@pytest.mark.parametrize(
    "relations, expected_data, context_raised",
    [
        ([], None, does_not_raise()),  # no relations
        (
            [Relation(RELATION_NAME, "istio-info", remote_app_data={})],
            None,
            does_not_raise(),
        ),  # one empty relation
        (
            [
                Relation(
                    RELATION_NAME,
                    "istio-info",
                    remote_app_data={"root_namespace": MODEL_NAME},
                )
            ],
            IstioInfoAppData(root_namespace=MODEL_NAME),
            does_not_raise(),
        ),  # one populated relation
        (
            [
                Relation(
                    RELATION_NAME,
                    "istio-info",
                    remote_app_data={"root_namespace": MODEL_NAME},
                ),
                Relation(
                    RELATION_NAME,
                    "istio-info",
                    remote_app_data={"root_namespace": MODEL_NAME},
                ),
            ],
            None,
            pytest.raises(ValueError),
        ),  # stale data
    ],
)
def test_requirer_get_data(relations, expected_data, context_raised, requirer_context):
    """Tests that IstioInfoRequirer.get_data() returns correctly."""
    state = State(
        relations=relations,
        leader=False,
        model=Model(name=MODEL_NAME),
    )

    with requirer_context(requirer_context.on.update_status(), state=state) as manager:
        charm = manager.charm

        with context_raised:
            data = charm.relation_requirer.get_data()
            assert data == expected_data


@pytest.mark.parametrize(
    "relations, expected_data, context_raised",
    [
        ([], [], does_not_raise()),  # no relations
        (
            [Relation(RELATION_NAME, "istio-info", remote_app_data={})],
            [None],
            does_not_raise(),
        ),  # one empty relation
        (
            [
                Relation(
                    RELATION_NAME,
                    "istio-info",
                    remote_app_data={"root_namespace": MODEL_NAME},
                )
            ],
            [IstioInfoAppData(root_namespace=MODEL_NAME)],
            does_not_raise(),
        ),  # one populated relation
        (
            [
                Relation(
                    RELATION_NAME,
                    "istio-info",
                    remote_app_data={"root_namespace": MODEL_NAME + "1"},
                ),
                Relation(RELATION_NAME, "istio-info", remote_app_data={}),
                Relation(
                    RELATION_NAME,
                    "istio-info",
                    remote_app_data={"root_namespace": MODEL_NAME + "3"},
                ),
            ],
            [
                IstioInfoAppData(root_namespace=MODEL_NAME + "1"),
                None,
                IstioInfoAppData(root_namespace=MODEL_NAME + "3"),
            ],
            does_not_raise(),
        ),  # many related applications, some with missing data
    ],
)
def test_requirer_get_data_from_all_relations(
    relations, expected_data, context_raised, requirer_context
):
    """Tests that IstioInfoRequirer.get_data_from_all_relations() returns correctly."""
    state = State(
        relations=relations,
        leader=False,
        model=Model(name=MODEL_NAME),
    )

    with requirer_context(requirer_context.on.update_status(), state=state) as manager:
        charm = manager.charm

        with context_raised:
            data = sort_app_data(charm.relation_requirer.get_data_from_all_relations())
            expected_data = sort_app_data(expected_data)
            assert data == expected_data


def sort_app_data(data):
    """Return sorted version of the list of relation data objects."""
    return sorted(data, key=lambda x: x.root_namespace if x else "")
