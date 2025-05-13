"""Tests that assert IstioCharm is wired up correctly to be a istio-metadata provider."""

import pytest
from ops.testing import Model, Relation, State

RELATION_NAME = "istio-metadata"
INTERFACE_NAME = "istio_metadata"

# Note: if this is changed, the IstioMetadataAppData concrete classes below need to change their constructors to match
SAMPLE_APP_DATA = {"root_namespace": "root-namespace"}


@pytest.mark.parametrize("model_name", ["istio", "istio-system"])
def test_provider_sender_sends_data_on_relation_joined(istio_core_context, model_name):
    """Tests that a charm using IstioMetadataProvider sends the correct data on a relation joined event."""
    # Arrange
    relation = Relation(RELATION_NAME, INTERFACE_NAME)
    relations = [relation]

    state = State(
        relations=relations,
        leader=True,
        model=Model(model_name),
    )

    expected = {"root_namespace": model_name}

    # Act
    state_out = istio_core_context.run(
        istio_core_context.on.relation_joined(relation), state=state
    )

    # Assert
    assert state_out.get_relation(relation.id).local_app_data == expected


@pytest.mark.parametrize("model_name", ["istio", "istio-system"])
def test_provider_sends_data_on_leader_elected(istio_core_context, model_name):
    """Tests that a charm using IstioMetadataProvider sends data on a leader elected event."""
    # Arrange
    relation = Relation(RELATION_NAME, INTERFACE_NAME)
    relations = [relation]

    state = State(
        relations=relations,
        leader=True,
        model=Model(model_name),
    )

    expected = {"root_namespace": model_name}

    event = getattr(istio_core_context.on, "leader_elected")()

    # Act
    state_out = istio_core_context.run(event, state=state)

    # Assert
    assert state_out.get_relation(relation.id).local_app_data == expected
