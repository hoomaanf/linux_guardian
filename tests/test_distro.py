from pathlib import Path

from app.core.distro import _parse_os_release, detect_distro


def test_parse_os_release(tmp_path: Path) -> None:
    content = 'NAME="Arch Linux"\nID=arch\nPRETTY_NAME="Arch Linux"\n'
    f = tmp_path / "os-release"
    f.write_text(content)
    data = _parse_os_release(str(f))
    assert data["ID"] == "arch"
    assert data["NAME"] == "Arch Linux"


def test_parse_os_release_missing_file(tmp_path: Path) -> None:
    data = _parse_os_release(str(tmp_path / "does-not-exist"))
    assert data == {}


def test_detect_distro_returns_info() -> None:
    info = detect_distro()
    assert info.id  # always populated, even if "unknown"
    assert isinstance(info.universal_managers, list)
