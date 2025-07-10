"""A python API for operating the istioctl binary."""

import logging
import subprocess
import sys
from itertools import chain
from typing import Dict, List, Optional

import yaml
from lightkube.core.resource import Resource

logger = logging.getLogger(__name__)


class IstioctlError(Exception):
    """Error raised when an istioctl command fails."""

    def __init__(
        self,
        message: str,
        returncode: Optional[int] = None,
        stdout: Optional[str] = None,
        stderr: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def __str__(self):
        """Human-readable description of the error."""
        return self.message


class Istioctl:
    """Python API to operate the istioctl binary."""

    def __init__(
        self,
        istioctl_path: Optional[str] = "./istioctl",
        namespace: Optional[str] = "istio-system",
        profile: Optional[str] = "empty",
        setting_overrides: Optional[Dict[str, str]] = None,
    ):
        """Python API for operating the istioctl binary.

        Args:
            istioctl_path (str): Path to the istioctl binary to be wrapped
            namespace (str): The namespace to install Istio into
            profile (str): The Istio profile to use for installation or upgrades.  Defaults to 'empty' because we
                           typically select a subset of the components to install via `components.NAME.enabled=true`
                           setting_overrides or using `manifest_generate`'s `components` argument.
            setting_overrides (optional, dict): A map of IstioOperator overrides to apply during
                                                istioctl calls, passed to istioctl as `--set`
                                                options
        """
        self._istioctl_path = istioctl_path
        self._namespace = namespace
        self._profile = profile
        self._setting_overrides = setting_overrides if setting_overrides is not None else {}

    @property
    def _args(self) -> List[str]:
        settings = {
            "profile": self._profile,
            "values.global.istioNamespace": self._namespace,
        }
        settings.update(self._setting_overrides)
        return settings_dict_to_args(settings)

    def install(self):
        """Install Istio using the `istioctl install` command."""
        # TODO: If this ever gets used, it probably needs the same `components` arg as `manifest_generate`
        args = ["install", "-y", *self._args]
        self._run(*args)

    def manifest_generate(self, components: Optional[List[str]] = None, overrides: Optional[List[Resource]] = None) -> str:
        """Generate Istio's manifests using the `istioctl manifest generate` command.

        Args:
            components: An optional list of Istio components to enable by passing the argument
                        `--set components.COMPONENT.enabled=true`.  See
                        https://istio.io/latest/docs/setup/additional-setup/customize-installation/
                        for more details. If undefined, no components will be added and only those components included
                        by default in the profile will be included.
                        Note that this argument changed when moving to Istio 1.24 because istioctl removed the old
                        `--component` argument.
            overrides: An optional list of lightkube Resource objects to override specific resources
                       in the generated manifest. The default value of the spec in the istioctl generated
                       manifest will be retained if the spec value is not included in the overriding
                       lightkube Resource. Resources are matched by kind, metadata.namespace and metadata.name.

        Returns:
            (str) a YAML string of the Kubernetes manifest for Istio
        """
        components = components if components is not None else []
        # Format the requested components into istioctl args
        components_args = chain.from_iterable(
            ("--set", f"components.{component}.enabled=true") for component in components
        )
        args = ["manifest", "generate", *self._args, *components_args]
        manifest_yaml = self._run(*args)

        # Apply overrides if provided
        if overrides:
            manifest_yaml = _apply_manifest_overrides(manifest_yaml, overrides)

        return manifest_yaml

    def precheck(self):
        """Execute `istioctl x precheck` to validate whether the environment can be updated.

        NOTE: This function does not validate exact versions compatibility. This verification
        should be done by caller.

        Raises:
            PrecheckFailedError: if the precheck command fails.
        """
        args = ["x", "precheck"]
        self._run(*args)

    def _run(self, *args) -> str:
        """Run an istioctl command with the given arguments, logging errors."""
        command = [self._istioctl_path, *args]
        logger.info(f"Running command: {' '.join(command)}")
        try:
            output = subprocess.check_output(command)
        except subprocess.CalledProcessError as cpe:
            istioctl_error = IstioctlError(
                f"Failed to run command {' '.join(command)} with error code {cpe.returncode}",
                returncode=cpe.returncode,
                stdout=cpe.stdout,
                stderr=cpe.stderr,
            )
            logger.error(istioctl_error.message)
            logger.error(f"stderr: {cpe.stderr}")
            raise istioctl_error from cpe

        return output.decode(sys.stdout.encoding)

    def uninstall(self):
        """Uninstall Istio using istioctl.

        Raises:
            IstioctlError: if the istioctl uninstall subprocess fails
        """
        args = ["uninstall", "--purge", "-y"]
        self._run(*args)

    def upgrade(self):
        """Upgrade the Istio installation using istioctl.

        Note that this only upgrades the control plane (eg: istiod), it does not upgrade the data
        plane (for example, the istio/proxyv2 image used in the istio-gateway charm).

        """
        args = ["upgrade", "-y", *self._args]
        self._run(*args)

    def version(self) -> dict:
        """Return istio client and control plane versions."""
        args = ["version", f"-i={self._namespace}", "-o=yaml"]
        version_string = self._run(*args)

        version_dict = yaml.safe_load(version_string)
        return {
            "client": get_client_version(version_dict),
            "control_plane": get_control_plane_version(version_dict),
        }


def get_client_version(version_dict: dict) -> str:
    """Return the client version from a dict of `istioctl version` output.

    Args:
        version_dict (dict): A dict of the version output from `istioctl version -o yaml`

    Returns:
        (str) The client version
    """
    try:
        version = version_dict["clientVersion"]["version"]
    except (KeyError, TypeError):
        # TypeError in case version_dict is None
        raise IstioctlError("Failed to get client version - no version found in output")
    return version


def get_control_plane_version(version_dict: dict) -> str:
    """Return the control plane version from a dict of `istioctl version` output.

    Args:
        version_dict (dict): A dict of the version output from `istioctl version -o yaml`

    Returns:
        (str) The control plane version
    """
    # Assert that we have only one mesh and it says it is a pilot.  Not sure how we can handle
    # multiple meshes here.
    error_message_template = "Failed to get control plane version - {message}"
    try:
        meshes = version_dict["meshVersion"]
    except KeyError:
        raise IstioctlError(error_message_template.format(message="no control plane found"))

    if len(meshes) == 0:
        raise IstioctlError(error_message_template.format(message="no mesh found"))
    if len(meshes) > 1:
        raise IstioctlError(error_message_template.format(message="too many meshes found"))

    mesh = meshes[0]

    try:
        if mesh["Component"] != "pilot":
            raise IstioctlError(error_message_template.format(message="no control plane found"))
        version = mesh["Info"]["version"]
    except KeyError:
        raise IstioctlError(error_message_template.format(message="no control plane found"))

    return version


def _apply_manifest_overrides(manifest_yaml: str, overrides: List[Resource]) -> str:
    """Apply lightkube resource overrides to specific resources in a Kubernetes manifest.

    Args:
        manifest_yaml: The YAML string containing Kubernetes manifests
        overrides: List of lightkube Resource objects to override matching resources

    Returns:
        The modified YAML string with overrides applied
    """
    documents = list(yaml.safe_load_all(manifest_yaml))

    for doc in documents:
        if doc is None:
            continue

        # Check if this document matches any override resource
        for override in overrides:
            if _is_same_resource(doc, override):
                override_dict = override.to_dict()  # pyright: ignore
                _deep_merge_dict(doc, override_dict)
                break

    return yaml.dump_all(documents, default_flow_style=False)


def _is_same_resource(manifest_doc: dict, override_resource: Resource) -> bool:
    """Check if a manifest document matches an override resource.

    Args:
        manifest_doc: Dictionary from the manifest YAML
        override_resource: Lightkube Resource object

    Returns:
        True if they represent the same resource
    """
    # Match by kind, namespace and name
    manifest_kind = manifest_doc.get("kind", "")
    manifest_name = manifest_doc.get("metadata", {}).get("name", "")
    manifest_namespace = manifest_doc.get("metadata", {}).get("namespace", "")

    override_kind = override_resource.__class__.__name__
    override_name = override_resource.metadata.name  # pyright: ignore
    override_namespace = override_resource.metadata.namespace  # pyright: ignore

    return (manifest_kind == override_kind and
            manifest_name == override_name and
            manifest_namespace == override_namespace)


def _deep_merge_dict(base: dict, updates: dict) -> None:
    """Recursively merge updates into base dict in-place.

    Args:
        base: The base dictionary to update
        updates: Dictionary containing updates to apply
    """
    for key, value in updates.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            # Recursively merge nested dicts
            _deep_merge_dict(base[key], value)
        else:
            base[key] = value


def settings_dict_to_args(settings: Dict[str, Optional[str]]) -> List[str]:
    """Return a list of istioctl `--set` arguments for the given settings.

    For example:
        settings_dict_to_args({"k1": "v1", "k2", "v2"})

    Returns:
        ['--set', 'k1=v1', '--set', 'k2=v2']
    """
    return list(
        chain.from_iterable(("--set", f"{key}={value}") for key, value in settings.items())
    )
