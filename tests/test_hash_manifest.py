from __future__ import annotations

from pathlib import Path

from app.services import hash_manifest


def test_hash_manifest_write_and_read(monkeypatch, tmp_path):
    monkeypatch.setattr(hash_manifest, "MANIFEST_ROOT", tmp_path / "hashes")

    f = tmp_path / "Demo Show - S01E01.mkv"
    f.write_bytes(b"episode-1")

    digest = hash_manifest.compute_md5(f)
    path = hash_manifest.record_episode_hash("Demo Show", 1, 1, f, digest)

    assert path.exists()
    loaded = hash_manifest.load_manifest("Demo Show")
    assert loaded["episodes"]["S01E01"]["md5"] == digest
    assert loaded["hash_index"][digest] == "S01E01"


def test_verify_range_detects_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(hash_manifest, "MANIFEST_ROOT", tmp_path / "hashes")

    f = tmp_path / "Demo Show - S02E01.mkv"
    f.write_bytes(b"original")
    digest = hash_manifest.compute_md5(f)
    hash_manifest.record_episode_hash("Demo Show", 2, 1, f, digest)

    # Simulate wrong remap/overwrite later.
    f.write_bytes(b"mutated")

    mismatches = hash_manifest.verify_range_against_manifest("Demo Show", 2, 1, 1)
    assert len(mismatches) == 1
    assert mismatches[0]["episode"] == "S02E01"
    assert mismatches[0]["status"] == "md5_mismatch"


def test_consistency_check_flags_hash_conflict(monkeypatch, tmp_path):
    monkeypatch.setattr(hash_manifest, "MANIFEST_ROOT", tmp_path / "hashes")

    f = tmp_path / "Demo Show - S02E01.mkv"
    f.write_bytes(b"same-bits")
    digest = hash_manifest.compute_md5(f)
    hash_manifest.record_episode_hash("Demo Show", 2, 1, f, digest)

    check = hash_manifest.check_mapping_consistency("Demo Show", 2, 2, digest)
    assert check.ok is False
    assert "hash_conflicts_with_S02E01" in check.reasons
