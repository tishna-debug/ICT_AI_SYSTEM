"""
scripts/backup_system.py

Zips the whole project (excluding .env, venv/, .git/, __pycache__, and
backups/ itself) into backups/, with a timestamped filename. Prunes old
backups beyond BACKUP_RETENTION_COUNT, keeping only the most recent ones
(Master Doc: "retention ~7-14 most recent").

Run it with:
    python scripts/backup_system.py

Optional: set CLOUD_BACKUP_FOLDER in .env to also copy each backup to a
second folder (e.g. a Dropbox or Google Drive sync folder). Not needed if
your project already lives inside a synced folder - this project is
already under OneDrive, so backups/ gets cloud-synced automatically with
no extra config.
"""

from __future__ import annotations

import os
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from engine.logging_config import get_logger

logger = get_logger("backup_system")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUPS_DIR = PROJECT_ROOT / "backups"
BACKUP_FILENAME_PREFIX = "ict_ai_system_backup_"

BACKUP_RETENTION_COUNT = 14  # Master Doc: "retention ~7-14 most recent"

# Never include these - secrets, or reproducible/tooling junk that would
# just bloat the archive (venv/.git are fully reproducible from
# requirements.txt + GitHub; backups/ is excluded so a backup never zips
# itself into the next one).
EXCLUDED_DIR_NAMES = {"venv", ".venv", ".git", "__pycache__", "backups", ".pytest_cache", ".claude"}
EXCLUDED_FILE_NAMES = {".env"}


def _is_excluded(rel_path: Path) -> bool:
    if set(rel_path.parts) & EXCLUDED_DIR_NAMES:
        return True
    if rel_path.name in EXCLUDED_FILE_NAMES:
        return True
    return False


def create_backup(source_dir: Path = PROJECT_ROOT, backups_dir: Path = BACKUPS_DIR) -> Path:
    """Zips `source_dir` (minus EXCLUDED_DIR_NAMES/EXCLUDED_FILE_NAMES)
    into a timestamped archive under `backups_dir`. Returns the archive path.
    """
    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    archive_path = backups_dir / f"{BACKUP_FILENAME_PREFIX}{timestamp}.zip"

    file_count = 0
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            root_path = Path(root)
            rel_root = root_path.relative_to(source_dir)

            # Prune excluded directories in place so os.walk doesn't descend into them at all.
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIR_NAMES]

            for filename in files:
                rel_path = rel_root / filename
                if _is_excluded(rel_path):
                    continue
                zf.write(root_path / filename, arcname=str(rel_path))
                file_count += 1

    logger.info(f"Created backup {archive_path.name} ({file_count} files, {archive_path.stat().st_size / 1_048_576:.1f} MB)")
    return archive_path


def prune_old_backups(backups_dir: Path = BACKUPS_DIR, retention_count: int = BACKUP_RETENTION_COUNT) -> List[Path]:
    """Deletes the oldest backups beyond `retention_count`, keeping the
    most recent ones. Returns the list of deleted paths.
    """
    if not backups_dir.exists():
        return []

    backups = sorted(backups_dir.glob(f"{BACKUP_FILENAME_PREFIX}*.zip"), key=lambda p: p.stat().st_mtime)
    to_delete = backups if retention_count <= 0 else backups[:-retention_count]

    deleted = []
    for path in to_delete:
        try:
            path.unlink()
            deleted.append(path)
            logger.info(f"Pruned old backup: {path.name}")
        except Exception:
            logger.exception(f"Failed to delete old backup {path.name}")

    return deleted


def copy_to_cloud_folder(archive_path: Path, cloud_folder: Optional[str] = None) -> bool:
    """Optional: if a cloud folder is configured (CLOUD_BACKUP_FOLDER in
    .env, or passed explicitly), copies the backup there too. Returns
    False if not configured or if the copy failed - never raises, since a
    failed cloud copy shouldn't be treated as a failed backup (the local
    archive already succeeded by the time this runs).
    """
    if cloud_folder is None:
        load_dotenv()
        cloud_folder = os.environ.get("CLOUD_BACKUP_FOLDER")
    if not cloud_folder:
        return False

    try:
        destination = Path(cloud_folder)
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(archive_path, destination / archive_path.name)
        logger.info(f"Copied backup to cloud folder: {destination}")
        return True
    except Exception:
        logger.exception(f"Failed to copy backup to CLOUD_BACKUP_FOLDER={cloud_folder!r} (local backup is still safe).")
        return False


def main() -> int:
    print("=" * 70)
    print("Backup system")
    print("=" * 70)

    print("\nCreating backup...")
    archive_path = create_backup()
    size_mb = archive_path.stat().st_size / 1_048_576
    print(f"Created {archive_path.relative_to(PROJECT_ROOT)} ({size_mb:.1f} MB)")

    deleted = prune_old_backups()
    if deleted:
        print(f"Pruned {len(deleted)} old backup(s), keeping the most recent {BACKUP_RETENTION_COUNT}.")

    if copy_to_cloud_folder(archive_path):
        print("Also copied to your configured CLOUD_BACKUP_FOLDER.")
    else:
        print("\nNote: this project already lives inside OneDrive, so backups/ is already cloud-synced automatically.")
        print("(CLOUD_BACKUP_FOLDER in .env is only needed if you want a SECOND copy somewhere else.)")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
