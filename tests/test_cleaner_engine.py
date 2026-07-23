from pathlib import Path

from app.cleaner import cleaner_engine
from app.cleaner.models import Finding, RiskLevel


def test_default_selection_only_checks_safe() -> None:
    findings = [
        Finding(path=Path("/tmp/a"), category="x", risk=RiskLevel.SAFE, size_bytes=1, reason=""),
        Finding(path=Path("/tmp/b"), category="x", risk=RiskLevel.PROBABLY_SAFE, size_bytes=1, reason=""),
        Finding(path=Path("/tmp/c"), category="x", risk=RiskLevel.NEEDS_CONFIRMATION, size_bytes=1, reason=""),
        Finding(path=Path("/tmp/d"), category="x", risk=RiskLevel.DANGEROUS, size_bytes=1, reason=""),
    ]
    cleaner_engine.default_selection(findings)
    assert [f.selected for f in findings] == [True, False, False, False]


def test_clean_moves_file_to_quarantine_not_hard_delete(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cleaner_engine, "BACKUP_ROOT", tmp_path / "quarantine")

    target = tmp_path / "some_cache_file.txt"
    target.write_text("disposable content")

    finding = Finding(
        path=target, category="user_cache", risk=RiskLevel.SAFE,
        size_bytes=target.stat().st_size, reason="test", selected=True,
    )

    result = cleaner_engine.clean([finding])

    assert not target.exists(), "source file should have been moved, not left in place"
    assert result.quarantine_session_dir is not None
    assert any(result.quarantine_session_dir.iterdir()), "quarantine dir should contain the moved file"
    assert result.freed_bytes == len("disposable content")


def test_clean_skips_unselected_findings(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cleaner_engine, "BACKUP_ROOT", tmp_path / "quarantine")
    target = tmp_path / "keep_me.txt"
    target.write_text("keep")
    finding = Finding(
        path=target, category="x", risk=RiskLevel.SAFE, size_bytes=4, reason="", selected=False,
    )
    result = cleaner_engine.clean([finding])
    assert target.exists(), "unselected findings must never be touched"
    assert result.freed_bytes == 0


def test_undo_restores_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cleaner_engine, "BACKUP_ROOT", tmp_path / "quarantine")
    target = tmp_path / "restore_me.txt"
    target.write_text("hello")
    finding = Finding(
        path=target, category="x", risk=RiskLevel.SAFE, size_bytes=5, reason="", selected=True,
    )
    result = cleaner_engine.clean([finding])
    assert not target.exists()

    undo_result = cleaner_engine.undo(result.quarantine_session_dir)
    assert target.exists()
    assert target.read_text() == "hello"
