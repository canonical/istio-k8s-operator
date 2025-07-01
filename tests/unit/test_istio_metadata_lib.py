"""Tests for the istio-metadata lib requirer and provider classes, excluding their usage in IstioCharm."""

from typing import Union

import pytest
from charms.istio_k8s.v0.istio_metadata import (
    IstioMetadataAppData,
    IstioMetadataProvider,
    IstioMetadataRequirer,
)
from ops import CharmBase
from ops.testing import Context, Relation, State

RELATION_NAME = "app-data-relation"
INTERFACE_NAME = "app-data-interface"

# Note: if this is changed, the IstioMetadataAppData concrete classes below need to change their constructors to match
SAMPLE_APP_DATA = IstioMetadataAppData(root_namespace="root-namespace")
SAMPLE_APP_DATA_2 = IstioMetadataAppData(root_namespace="root-namespace-2")


class IstioMetadataProviderCharm(CharmBase):
    META = {
        "name": "provider",
        "provides": {RELATION_NAME: {"interface": INTERFACE_NAME}},
    }

    def __init__(self, framework):
        super().__init__(framework)
        self.relation_provider = IstioMetadataProvider(
            relation_mapping=self.model.relations,
            app=self.app,
            relation_name=RELATION_NAME,  # pyright: ignore
        )


@pytest.fixture()
def istio_metadata_provider_context():
    return Context(charm_type=IstioMetadataProviderCharm, meta=IstioMetadataProviderCharm.META)


class IstioMetadataRequirerCharm(CharmBase):
    META = {
        "name": "requirer",
        "requires": {RELATION_NAME: {"interface": INTERFACE_NAME}},
    }

    def __init__(self, framework):
        super().__init__(framework)
        self.relation_requirer = IstioMetadataRequirer(
            self.model.relations, relation_name=RELATION_NAME
        )


@pytest.fixture()
def istio_metadata_requirer_context():
    return Context(charm_type=IstioMetadataRequirerCharm, meta=IstioMetadataRequirerCharm.META)


@pytest.mark.parametrize("data", [SAMPLE_APP_DATA, SAMPLE_APP_DATA_2])
def test_istio_metadata_provider_sends_data_correctly(data, istio_metadata_provider_context):
    """Tests that a charm using IstioMetadataProvider sends the correct data during publish."""
    # Arrange
    istio_metadata_relation = Relation(RELATION_NAME, INTERFACE_NAME, local_app_data={})
    relations = [istio_metadata_relation]
    state = State(relations=relations, leader=True)

    state_out = None
    # Act
    with istio_metadata_provider_context(
        # construct a charm using an event that won't trigger anything here
        istio_metadata_provider_context.on.update_status(),
        state=state,
    ) as manager:
        # Manually do a .publish() to simulate the publish, but also do .run() to generate the state_out that we need
        # to inspect the relation data
        manager.charm.relation_provider.publish(**data.model_dump())
        state_out = manager.run()

    # Assert
    # Convert local_app_data to TempoApiAppData for comparison
    actual = IstioMetadataAppData.model_validate(
        dict(state_out.get_relation(istio_metadata_relation.id).local_app_data)
    )

    assert actual == data


@pytest.mark.parametrize(
    "relations, expected_data",
    [
        # no relations
        ([], None),
        # one empty relation
        (
            [Relation(RELATION_NAME, INTERFACE_NAME, remote_app_data={})],
            None,
        ),
        # one populated relation
        (
            [
                Relation(
                    RELATION_NAME,
                    INTERFACE_NAME,
                    remote_app_data=SAMPLE_APP_DATA.model_dump(mode="json"),
                )
            ],
            SAMPLE_APP_DATA,  # pyright: ignore
        ),
    ],
)
def test_istio_metadata_requirer_get_data(
    relations, expected_data, istio_metadata_requirer_context
):
    """Tests that IstioMetadataRequirer.get_data() returns correctly."""
    state = State(
        relations=relations,
        leader=False,
    )

    with istio_metadata_requirer_context(
        istio_metadata_requirer_context.on.update_status(), state=state
    ) as manager:
        charm = manager.charm

        data = charm.relation_requirer.get_data()
        assert are_app_data_equal(data, expected_data)


def are_app_data_equal(
    data1: Union[IstioMetadataAppData, None], data2: Union[IstioMetadataAppData, None]
):
    """Compare two IstioMetadataRequirer objects, tolerating when one or both is None."""
    if data1 is None and data2 is None:
        return True
    if data1 is None or data2 is None:
        return False
    return data1.model_dump() == data2.model_dump()
