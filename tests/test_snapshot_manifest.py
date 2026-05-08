from __future__ import annotations

import json

import pytest


def test_write_snapshot_manifest_is_deterministic_and_redacts_secrets(tmp_path):
    from src.data_ingestion.manifest import (
        build_snapshot_manifest,
        write_snapshot_manifest,
    )

    manifest = build_snapshot_manifest(
        data_snapshot_id="snap-1",
        snapshot_date="2026-05-08",
        universe_id="biotech_us_v1",
        providers=["sec", "tiingo", "SEC"],
        universe_member_count=2,
        coverage={"prices": {"tickers": 2}},
        fetch_summary={"tiingo": {"success": 2}},
        skipped=[],
        source_hashes={"universe": "abc"},
        metadata={"note": "token=secret"},
        secret_values=["secret"],
    )

    path = write_snapshot_manifest(manifest, output_dir=tmp_path)

    assert path.name == "snap-1-manifest.json"
    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    assert payload["data_snapshot_id"] == "snap-1"
    assert payload["survivorship_bias_warning"] is True
    assert payload["universe_bias_status"] == "current_constituents_only"
    assert payload["providers"] == ["sec", "tiingo"]
    assert "secret" not in raw
    assert "<redacted>" in raw

    second_path = write_snapshot_manifest(manifest, output_dir=tmp_path)
    assert second_path.read_text(encoding="utf-8") == raw


@pytest.mark.parametrize(
    "snapshot_id",
    [
        "../manifest-escape",
        "nested/snap-1",
        "nested\\snap-1",
        "snap..escape",
    ],
)
def test_write_snapshot_manifest_rejects_unsafe_snapshot_ids(
    tmp_path,
    snapshot_id,
):
    from src.data_ingestion.manifest import write_snapshot_manifest

    output_dir = tmp_path / "manifests"
    escape_path = tmp_path / "manifest-escape-manifest.json"

    with pytest.raises(ValueError, match="data_snapshot_id"):
        write_snapshot_manifest(
            {"data_snapshot_id": snapshot_id, "payload": "ok"},
            output_dir=output_dir,
        )

    assert not escape_path.exists()
    assert not output_dir.exists() or list(output_dir.iterdir()) == []
