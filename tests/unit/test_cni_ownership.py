# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from datetime import datetime, timezone

import ops
import pytest
from canonical_service_mesh.k8s.resource_manager import create_charm_default_labels
from lightkube import ApiError
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.models.rbac_v1 import RoleRef, Subject
from lightkube.resources.core_v1 import ConfigMap, Pod
from lightkube.resources.rbac_authorization_v1 import ClusterRoleBinding
from scenario import Context, Model, State
from scenario.errors import UncaughtCharmError

from src.charm import CONTROL_PLANE_LABEL, IstioCoreCharm


def cni_binding(namespace: str = "owner", application: str = "istio") -> ClusterRoleBinding:
    return ClusterRoleBinding(
        metadata=ObjectMeta(
            name="istio-cni",
            labels=create_charm_default_labels(application, namespace, CONTROL_PLANE_LABEL),
        ),
        roleRef=RoleRef(
            apiGroup="rbac.authorization.k8s.io", kind="ClusterRole", name="istio-cni"
        ),
        subjects=[Subject(kind="ServiceAccount", name="istio-cni", namespace=namespace)],
    )


def api_error(code: int, reason: str) -> ApiError:
    return ApiError(status={"code": code, "reason": reason, "message": reason})


@pytest.fixture()
def cni_context(mocker):
    downstream = [
        "_publish_ext_authz_provider_names",
        "_publish_istio_metadata",
        "_reconcile_gateway_api_crds",
        "_reconcile_istio_crds",
        "_reconcile_authorization_policies",
        "_reconcile_control_plane",
        "_set_istio_version",
        "_setup_proxy_pebble_service",
    ]
    hooks = [mocker.patch.object(IstioCoreCharm, name) for name in downstream]
    mocker.patch.object(
        IstioCoreCharm, "_get_control_plane_statuses", return_value=[ops.ActiveStatus()]
    )
    client = mocker.patch("src.charm.Client", autospec=True).return_value
    client.get.return_value = cni_binding()
    return Context(IstioCoreCharm, app_name="istio"), client, hooks


@pytest.mark.parametrize("existing", [False, True], ids=["new-install", "existing-owner"])
def test_owner_reconciles(cni_context, existing):
    context, client, hooks = cni_context
    if existing:
        client.create.side_effect = api_error(409, "AlreadyExists")

    out = context.run(context.on.config_changed(), State(leader=True, model=Model(name="owner")))

    assert out.unit_status == ops.ActiveStatus()
    client.create.assert_called_once_with(cni_binding())
    for hook in hooks:
        hook.assert_called_once()


@pytest.mark.parametrize(
    "binding",
    [
        cni_binding("other-model"),
        cni_binding(application="other-app"),
        ClusterRoleBinding(
            metadata=ObjectMeta(name="istio-cni"),
            roleRef=cni_binding().roleRef,
            subjects=cni_binding().subjects,
        ),
        ClusterRoleBinding(
            metadata=cni_binding().metadata,
            roleRef=cni_binding().roleRef,
            subjects=cni_binding("other-model").subjects,
        ),
    ],
    ids=["other-namespace", "other-application", "unlabelled-install", "matching-labels"],
)
def test_conflicting_owner_blocks_before_any_reconciliation(cni_context, binding):
    context, client, hooks = cni_context
    # Even if the binding appeared concurrently, create cannot overwrite it.
    client.create.side_effect = api_error(409, "AlreadyExists")
    client.get.return_value = binding

    out = context.run(context.on.config_changed(), State(leader=True, model=Model(name="owner")))

    assert out.unit_status.name == "blocked"
    if binding.metadata.labels:
        assert "remove the other installation first" in out.unit_status.message
        assert binding.subjects[0].namespace in out.unit_status.message
    else:
        assert "Unrecognised Istio CNI owner" in out.unit_status.message
    for hook in hooks:
        hook.assert_not_called()
    client.patch.assert_not_called()
    client.delete.assert_not_called()


@pytest.mark.parametrize("deleted", [False, True], ids=["terminating", "deleted-after-conflict"])
def test_disappearing_claim_waits_without_reconciling(cni_context, deleted):
    context, client, hooks = cni_context
    client.create.side_effect = api_error(409, "AlreadyExists")
    if deleted:
        client.get.side_effect = api_error(404, "NotFound")
    else:
        binding = cni_binding()
        binding.metadata.deletionTimestamp = datetime.now(timezone.utc)
        client.get.return_value = binding

    out = context.run(context.on.start(), State(leader=True, model=Model(name="owner")))

    assert out.unit_status == ops.WaitingStatus("Waiting to claim Istio CNI ownership")
    for hook in hooks:
        hook.assert_not_called()


@pytest.mark.parametrize("code,reason", [(403, "Forbidden"), (409, "Conflict"), (500, "InternalError")])
def test_claim_api_errors_propagate(cni_context, code, reason):
    context, client, hooks = cni_context
    error = api_error(code, reason)
    client.create.side_effect = error

    with pytest.raises(UncaughtCharmError) as caught:
        context.run(context.on.start(), State(leader=True, model=Model(name="owner")))

    assert caught.value.__cause__ is error
    for hook in hooks:
        hook.assert_not_called()


def test_update_status_retries_after_owner_is_removed(cni_context):
    context, client, hooks = cni_context
    state = State(
        leader=True,
        model=Model(name="owner"),
        unit_status=ops.BlockedStatus("Istio CNI already exists"),
    )

    out = context.run(context.on.update_status(), state)

    assert out.unit_status == ops.ActiveStatus()
    client.create.assert_called_once()
    for hook in hooks:
        hook.assert_called_once()


@pytest.mark.parametrize(
    "state",
    [State(model=Model(name="owner")), State(leader=True, planned_units=0, model=Model(name="owner"))],
    ids=["nonleader", "removing-application"],
)
def test_inactive_unit_does_not_claim_ownership(cni_context, state):
    context, client, hooks = cni_context

    context.run(context.on.config_changed(), state)

    client.create.assert_not_called()
    for hook in hooks:
        hook.assert_not_called()


@pytest.mark.parametrize("owned", [False, True], ids=["blocked-contender", "owner"])
def test_remove_only_deletes_owned_resources_and_releases_claim_last(cni_context, mocker, owned):
    context, client, _ = cni_context
    client.get.return_value = cni_binding() if owned else cni_binding("other-model")
    manager = mocker.patch.object(IstioCoreCharm, "_get_resource_manager").return_value
    manager.get_deployed_resources.side_effect = [
        [
            cni_binding(),
            ConfigMap(metadata=ObjectMeta(name="owned-config", namespace="owner")),
        ],
        [],
        [],
    ]

    context.run(context.on.remove(), State(leader=True, model=Model(name="owner")))

    if owned:
        assert manager.get_deployed_resources.call_count == 3
        assert client.delete.call_args_list == [
            mocker.call(res=ConfigMap, name="owned-config", namespace="owner"),
            mocker.call(ClusterRoleBinding, "istio-cni"),
        ]
    else:
        manager.get_deployed_resources.assert_not_called()
        client.delete.assert_not_called()


def test_cleanup_failure_keeps_ownership_claim(cni_context, mocker):
    context, client, _ = cni_context
    manager = mocker.patch.object(IstioCoreCharm, "_get_resource_manager").return_value
    manager.get_deployed_resources.side_effect = api_error(500, "InternalError")

    with pytest.raises(UncaughtCharmError):
        context.run(context.on.remove(), State(leader=True, model=Model(name="owner")))

    client.delete.assert_not_called()


def test_remove_waits_for_control_plane_pods_before_releasing_claim(cni_context, mocker):
    context, client, _ = cni_context
    manager = mocker.patch.object(IstioCoreCharm, "_get_resource_manager").return_value
    manager.get_deployed_resources.return_value = []
    terminating = Pod(metadata=ObjectMeta(name="istio-cni-node", namespace="owner"))
    checks = []

    def list_pods(*args, **kwargs):
        client.delete.assert_not_called()
        checks.append(True)
        return [terminating] if len(checks) == 1 else []

    client.list.side_effect = list_pods

    context.run(context.on.remove(), State(leader=True, model=Model(name="owner")))

    assert len(checks) == 2
    client.delete.assert_called_once_with(ClusterRoleBinding, "istio-cni")


def test_shutdown_timeout_keeps_ownership_claim(cni_context, mocker):
    context, client, _ = cni_context
    manager = mocker.patch.object(IstioCoreCharm, "_get_resource_manager").return_value
    manager.get_deployed_resources.return_value = []
    client.list.return_value = [Pod(metadata=ObjectMeta(name="istio-cni-node", namespace="owner"))]
    mocker.patch("src.charm.CONTROL_PLANE_TERMINATION_TIMEOUT", 0)

    with pytest.raises(UncaughtCharmError) as caught:
        context.run(context.on.remove(), State(leader=True, model=Model(name="owner")))

    assert isinstance(caught.value.__cause__, TimeoutError)
    client.delete.assert_not_called()
