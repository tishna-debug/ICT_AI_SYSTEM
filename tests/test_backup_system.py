"""
Tests for scripts/backup_system.py. Never touches the real project tree -
every test builds a small fake source directory under tmp_path instead.
"""

import time
import zipfile

from scripts.backup_system import copy_to_cloud_folder, create_backup, prune_old_backups


def _build_fake_project(root):
    (root / "engine").mkdir()
    (root / "engine" / "rules_base.py").write_text("print('real source file')")
    (root / "data").mkdir()
    (root / "data" / "verdicts.json").write_text("[]")

    (root / ".env").write_text("TELEGRAM_BOT_TOKEN=super-secret-value")

    (root / "venv" / "Lib").mkdir(parents=True)
    (root / "venv" / "Lib" / "junk.py").write_text("reproducible package junk")

    (root / ".git" / "objects").mkdir(parents=True)
    (root / ".git" / "objects" / "abc123").write_text("git internals")

    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "cached.pyc").write_text("bytecode")


def test_create_backup_excludes_secrets_and_reproducible_dirs(tmp_path):
    source = tmp_path / "project"
    source.mkdir()
    _build_fake_project(source)
    backups_dir = tmp_path / "backups"

    archive_path = create_backup(source_dir=source, backups_dir=backups_dir)

    assert archive_path.exists()
    with zipfile.ZipFile(archive_path) as zf:
        names = zf.namelist()

    assert any("rules_base.py" in n for n in names)
    assert any("verdicts.json" in n for n in names)
    assert not any(".env" in n for n in names)
    assert not any("venv" in n for n in names)
    assert not any(".git" in n for n in names)
    assert not any("__pycache__" in n for n in names)


def test_create_backup_never_includes_the_backups_dir_itself(tmp_path):
    source = tmp_path / "project"
    source.mkdir()
    _build_fake_project(source)
    backups_dir = source / "backups"  # backups/ lives INSIDE the project, like the real one does
    backups_dir.mkdir()
    (backups_dir / "old_backup.zip").write_text("a previous backup")

    archive_path = create_backup(source_dir=source, backups_dir=backups_dir)

    with zipfile.ZipFile(archive_path) as zf:
        names = zf.namelist()
    assert not any("backups" in n for n in names)


def test_prune_old_backups_keeps_most_recent_n(tmp_path):
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()

    paths = []
    for i in range(5):
        p = backups_dir / f"ict_ai_system_backup_{i}.zip"
        p.write_text("x")
        os_time = time.time() + i  # ensure strictly increasing mtimes
        import os

        os.utime(p, (os_time, os_time))
        paths.append(p)

    deleted = prune_old_backups(backups_dir=backups_dir, retention_count=2)

    remaining = sorted(backups_dir.glob("ict_ai_system_backup_*.zip"))
    assert len(remaining) == 2
    assert remaining == sorted(paths[-2:])
    assert len(deleted) == 3


def test_prune_old_backups_missing_dir_returns_empty(tmp_path):
    assert prune_old_backups(backups_dir=tmp_path / "does_not_exist") == []


def test_prune_old_backups_zero_retention_deletes_all(tmp_path):
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    (backups_dir / "ict_ai_system_backup_1.zip").write_text("x")
    (backups_dir / "ict_ai_system_backup_2.zip").write_text("x")

    deleted = prune_old_backups(backups_dir=backups_dir, retention_count=0)

    assert len(deleted) == 2
    assert list(backups_dir.glob("ict_ai_system_backup_*.zip")) == []


def test_copy_to_cloud_folder_not_configured_returns_false(tmp_path, monkeypatch):
    import scripts.backup_system as backup_system

    monkeypatch.setattr(backup_system, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("CLOUD_BACKUP_FOLDER", raising=False)

    archive = tmp_path / "archive.zip"
    archive.write_text("x")

    assert copy_to_cloud_folder(archive, cloud_folder=None) is False


def test_copy_to_cloud_folder_copies_when_configured(tmp_path):
    archive = tmp_path / "archive.zip"
    archive.write_text("backup contents")
    destination = tmp_path / "cloud_folder"

    result = copy_to_cloud_folder(archive, cloud_folder=str(destination))

    assert result is True
    assert (destination / "archive.zip").read_text() == "backup contents"


def test_copy_to_cloud_folder_handles_bad_destination_gracefully(tmp_path):
    archive = tmp_path / "archive.zip"
    archive.write_text("x")

    # A file (not a directory) as the "folder" - mkdir(parents=True, exist_ok=True) will raise
    bad_destination = tmp_path / "not_a_folder"
    bad_destination.write_text("I'm a file, not a directory")

    result = copy_to_cloud_folder(archive, cloud_folder=str(bad_destination / "sub"))
    assert result is False  # should not raise
