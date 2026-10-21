import json

import pytest

from core.sandbox_backends.qemu.bundle import Bundle, plain_path


def test_hashes_and_roles_are_checked(qemu_bundle):
    bundle = Bundle.load(qemu_bundle)
    assert bundle.qemu == qemu_bundle / "runtime" / "qemu.exe"
    assert bundle.initrd == qemu_bundle / "initrd"


def test_changed_component_rejected(qemu_bundle):
    (qemu_bundle / "initrd").write_bytes(b"changed")
    with pytest.raises(ValueError, match="hashes"):
        Bundle.load(qemu_bundle)


def test_unlisted_dll_rejected(qemu_bundle):
    (qemu_bundle / "runtime" / "extra.dll").write_bytes(b"not trusted")
    with pytest.raises(ValueError, match="inventariado"):
        Bundle.load(qemu_bundle)


@pytest.mark.parametrize("name", ["../initrd", "C:/initrd", "/initrd", "a\\b", "a/../initrd", "a//b"])
def test_bundle_path_traversal_rejected(qemu_bundle, name):
    with pytest.raises(ValueError):
        plain_path(qemu_bundle, name)


def test_unknown_manifest_fields_rejected(qemu_bundle):
    path = qemu_bundle / "bundle.json"
    data = json.loads(path.read_text())
    data["extra_args"] = ["-net", "user"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        Bundle.load(qemu_bundle)


def test_symlink_component_rejected(qemu_bundle, tmp_path):
    target = qemu_bundle / "kernel"
    target.unlink()
    other = tmp_path / "other"
    other.write_bytes(b"kernel")
    try:
        target.symlink_to(other)
    except OSError:
        pytest.skip("Requiere permiso para symlinks")
    with pytest.raises(ValueError, match="enlaces"):
        Bundle.load(qemu_bundle)
