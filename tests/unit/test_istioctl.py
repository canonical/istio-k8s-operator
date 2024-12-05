import sys
from pathlib import Path
from subprocess import CalledProcessError
from unittest.mock import MagicMock

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader

from istioctl import (
    Istioctl,
    IstioctlError,
    get_client_version,
    get_control_plane_version,
    settings_dict_to_args,
)

ISTIOCTL_BINARY = "not_really_istioctl"
NAMESPACE = "placeholder-namespace"
PROFILE = "my-profile"
TEST_DATA_PATH = Path(__file__).parent / "istioctl_data"
EXPECTED_ISTIOCTL_FLAGS = [
    "--set",
    f"profile={PROFILE}",
    "--set",
    f"values.global.istioNamespace={NAMESPACE}",
]


# autouse to ensure we don't accidentally call out, but
# can also be used explicitly to get access to the mock.
@pytest.fixture(autouse=True)
def mocked_check_output(mocker):
    mocked_check_output = mocker.patch("subprocess.check_output")
    mocked_check_output.return_value = b"stdout"

    yield mocked_check_output


@pytest.fixture()
def mocked_check_output_failing(mocked_check_output):
    cpe = CalledProcessError(cmd="", returncode=1, stderr="stderr", output="stdout")
    mocked_check_output.return_value = None
    mocked_check_output.side_effect = cpe

    yield mocked_check_output


def test_istioctl_install_no_setting_overrides(mocked_check_output):
    """Tests that istioctl.install() calls the binary successfully with the expected arguments."""
    ictl = Istioctl(istioctl_path=ISTIOCTL_BINARY, namespace=NAMESPACE, profile=PROFILE)

    ictl.install()

    # Assert that we call istioctl with the expected arguments
    expected_call_args = [
        ISTIOCTL_BINARY,
        "install",
        "-y",
    ]
    expected_call_args.extend(EXPECTED_ISTIOCTL_FLAGS)

    mocked_check_output.assert_called_once_with(expected_call_args)


def test_istioctl_install_setting_overrides(mocked_check_output):
    """Tests that istioctl.install() calls the binary successfully with the expected arguments."""
    setting_overrides = {"k1": "v1"}
    ictl = Istioctl(
        istioctl_path=ISTIOCTL_BINARY,
        namespace=NAMESPACE,
        profile=PROFILE,
        setting_overrides=setting_overrides,
    )

    ictl.install()

    # Assert that we call istioctl with the expected arguments
    expected_call_args = [
        ISTIOCTL_BINARY,
        "install",
        "-y",
    ]
    expected_call_args.extend(EXPECTED_ISTIOCTL_FLAGS)
    for k, v in setting_overrides.items():
        expected_call_args.extend(["--set", f"{k}={v}"])

    mocked_check_output.assert_called_once_with(expected_call_args)


def test_istioctl_install_error(mocked_check_output_failing):
    """Tests that istioctl.install() calls the binary successfully with the expected arguments."""
    ictl = Istioctl(istioctl_path=ISTIOCTL_BINARY, namespace=NAMESPACE, profile=PROFILE)

    # Assert that we raise an error when istioctl fails
    with pytest.raises(IstioctlError):
        ictl.install()


def test_istioctl_manifest(mocked_check_output):
    ictl = Istioctl(istioctl_path=ISTIOCTL_BINARY, namespace=NAMESPACE, profile=PROFILE)

    manifest = ictl.manifest_generate()

    # Assert that we call istioctl with the expected arguments
    expected_call_args = [
        ISTIOCTL_BINARY,
        "manifest",
        "generate",
    ]
    expected_call_args.extend(EXPECTED_ISTIOCTL_FLAGS)

    mocked_check_output.assert_called_once_with(expected_call_args)

    # Assert that we received the expected manifests from istioctl
    expected_manifest = "stdout"
    assert manifest == expected_manifest


def test_istioctl_manifest_with_setting_overrides_and_components(mocked_check_output):
    setting_overrides = {"k1": "v1"}
    ictl = Istioctl(
        istioctl_path=ISTIOCTL_BINARY,
        namespace=NAMESPACE,
        profile=PROFILE,
        setting_overrides=setting_overrides,
    )
    components = ["c1", "c2"]

    ictl.manifest_generate(components=components)

    # Assert that we call istioctl with the expected arguments
    expected_call_args = [
        ISTIOCTL_BINARY,
        "manifest",
        "generate",
    ]
    expected_call_args.extend(EXPECTED_ISTIOCTL_FLAGS)
    for k, v in setting_overrides.items():
        expected_call_args.extend(["--set", f"{k}={v}"])
    for c in components:
        expected_call_args.extend(["--set", f"components.{c}.enabled=true"])

    mocked_check_output.assert_called_once_with(expected_call_args)


def test_istioctl_manifest_error(mocked_check_output_failing):
    """Tests that istioctl.install() calls the binary successfully with the expected arguments."""
    ictl = Istioctl(istioctl_path=ISTIOCTL_BINARY, namespace=NAMESPACE, profile=PROFILE)

    # Assert that we raise an error when istioctl fails
    with pytest.raises(IstioctlError):
        ictl.manifest_generate()


@pytest.fixture()
def mocked_lightkube_client(mocker):
    mocked_lightkube_client = MagicMock()
    mocked_lightkube_client_class = mocker.patch("istioctl.Client")
    mocked_lightkube_client_class.return_value = mocked_lightkube_client

    yield mocked_lightkube_client


def test_istioctl_remove(mocked_check_output):
    ictl = Istioctl(istioctl_path=ISTIOCTL_BINARY, namespace=NAMESPACE, profile=PROFILE)

    ictl.uninstall()

    mocked_check_output.assert_called_once_with([ISTIOCTL_BINARY, "uninstall", "--purge", "-y"])


def test_istioctl_remove_error(mocked_check_output_failing):
    ictl = Istioctl(istioctl_path=ISTIOCTL_BINARY, namespace=NAMESPACE, profile=PROFILE)

    with pytest.raises(IstioctlError):
        ictl.uninstall()


def test_istioctl_precheck(mocked_check_output):
    ictl = Istioctl(istioctl_path=ISTIOCTL_BINARY, namespace=NAMESPACE, profile=PROFILE)

    ictl.precheck()

    mocked_check_output.assert_called_once_with([ISTIOCTL_BINARY, "x", "precheck"])


def test_istioctl_precheck_error(mocked_check_output_failing):
    ictl = Istioctl(istioctl_path=ISTIOCTL_BINARY, namespace=NAMESPACE, profile=PROFILE)

    with pytest.raises(IstioctlError):
        ictl.precheck()


def test_istioctl_upgrade(mocked_check_output):
    ictl = Istioctl(istioctl_path=ISTIOCTL_BINARY, namespace=NAMESPACE, profile=PROFILE)

    ictl.upgrade()

    expected_call_args = [
        ISTIOCTL_BINARY,
        "upgrade",
        "-y",
    ]
    expected_call_args.extend(EXPECTED_ISTIOCTL_FLAGS)

    mocked_check_output.assert_called_once_with(expected_call_args)


def test_istioctl_upgrade_error(mocked_check_output_failing):
    ictl = Istioctl(istioctl_path=ISTIOCTL_BINARY, namespace=NAMESPACE, profile=PROFILE)

    with pytest.raises(IstioctlError) as exception_info:
        ictl.upgrade()

    # Check if we failed for the right reason
    assert "istioctl upgrade" in exception_info.value.args[0]


def test_istioctl_version(mocked_check_output):
    """Test that istioctl.version() returns successfully when expected."""
    expected_client_version = "1.2.3"
    expected_control_version = "4.5.6"
    environment = Environment(loader=FileSystemLoader(TEST_DATA_PATH))
    template = environment.get_template("istioctl_version_output_template.yaml.j2")
    istioctl_version_output_str = template.render(
        client_version=expected_client_version,
        control_version=expected_control_version,
    )
    mocked_check_output.return_value = istioctl_version_output_str.encode(sys.stdout.encoding)

    ictl = Istioctl(istioctl_path=ISTIOCTL_BINARY, namespace=NAMESPACE, profile=PROFILE)

    version_data = ictl.version()

    mocked_check_output.assert_called_once_with(
        [
            ISTIOCTL_BINARY,
            "version",
            f"-i={NAMESPACE}",
            "-o=yaml",
        ]
    )

    assert version_data["client"] == expected_client_version
    assert version_data["control_plane"] == expected_control_version


def test_istioctl_version_no_versions(mocked_check_output):
    """Test that istioctl.version() returns successfully when expected."""
    # Mock with empty return
    mocked_check_output.return_value = "".encode(sys.stdout.encoding)

    ictl = Istioctl(istioctl_path=ISTIOCTL_BINARY, namespace=NAMESPACE, profile=PROFILE)

    with pytest.raises(IstioctlError):
        ictl.version()


def test_istioctl_version_istioctl_command_fails(mocked_check_output_failing):
    """Test that istioctl.version() returns successfully when expected."""
    ictl = Istioctl(istioctl_path=ISTIOCTL_BINARY, namespace=NAMESPACE, profile=PROFILE)

    with pytest.raises(IstioctlError):
        ictl.version()


def test_get_client_version():
    client_version = "1.2.3"

    environment = Environment(loader=FileSystemLoader(TEST_DATA_PATH))
    template = environment.get_template("istioctl_version_output_template.yaml.j2")
    istioctl_version_output_str = template.render(
        client_version=client_version,
        control_version="None",
    )

    istioctl_version_output = yaml.safe_load(istioctl_version_output_str)

    assert get_client_version(istioctl_version_output) == client_version


def test_get_client_version_no_version():
    """Assert that get_client_version raises when input does not have correct keys."""
    with pytest.raises(IstioctlError):
        get_client_version({})


def test_get_control_plane_version():
    control_plane_version = "3.2.1"

    environment = Environment(loader=FileSystemLoader(TEST_DATA_PATH))
    template = environment.get_template("istioctl_version_output_template.yaml.j2")
    istioctl_version_output_str = template.render(
        client_version="None",
        control_version=control_plane_version,
    )

    istioctl_version_output = yaml.safe_load(istioctl_version_output_str)

    assert get_control_plane_version(istioctl_version_output) == control_plane_version


def test_get_control_plane_version_no_version():
    """Assert that get_client_version raises when input does not have correct keys."""
    with pytest.raises(IstioctlError):
        get_control_plane_version({})


def test_get_control_plane_version_too_many_meshes():
    istioctl_version_output = yaml.safe_load(
        (TEST_DATA_PATH / "istioctl_version_output_too_many_meshes.yaml").read_text()
    )

    with pytest.raises(IstioctlError):
        get_control_plane_version(istioctl_version_output)


def test_get_control_plane_version_no_pilot_in_meshes():
    istioctl_version_output = yaml.safe_load(
        (TEST_DATA_PATH / "istioctl_version_output_no_pilot_in_control.yaml").read_text()
    )
    with pytest.raises(IstioctlError):
        get_control_plane_version(istioctl_version_output)


@pytest.mark.parametrize(
    "settings, expected_args",
    [
        ({}, []),
        ({"k1": "v1"}, ["--set", "k1=v1"]),
        ({"k1": "v1", "k2": "v2"}, ["--set", "k1=v1", "--set", "k2=v2"]),
    ],
)
def test_settings_dict_to_args(settings, expected_args):
    assert settings_dict_to_args(settings) == expected_args
