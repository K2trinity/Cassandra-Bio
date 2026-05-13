import json
import sqlite3

from src.reports.disease.report_store import ReportStore


def test_report_store_saves_once_by_unique_dedupe_key(tmp_path):
    db_path = tmp_path / "events.db"
    store = ReportStore(db_path)
    package = {
        "disease_profile": {
            "target_type": "company",
            "target_name": "Vertex Pharmaceuticals",
            "company_name": "Vertex Pharmaceuticals",
        },
        "source_audit": {"raw_count": 10, "retained_count": 3, "details": {"source": "test"}},
    }
    narratives = {"language": "en", "executive_summary": "summary"}
    artifacts = {"markdown_path": str(tmp_path / "report.md"), "pdf_path": str(tmp_path / "report.pdf")}
    updated_narratives = {"language": "en", "executive_summary": "regenerated wording"}
    updated_artifacts = {"markdown_path": str(tmp_path / "other.md"), "pdf_path": str(tmp_path / "other.pdf")}

    first = store.save(
        package=package,
        narratives=narratives,
        artifact_paths=artifacts,
        query="Vertex pipeline",
        target_type="company",
        target_name="Vertex Pharmaceuticals",
        report_mode="medium",
        source_audit=package["source_audit"],
    )
    second = store.save(
        package=package,
        narratives=updated_narratives,
        artifact_paths=updated_artifacts,
        query="Vertex pipeline",
        target_type="company",
        target_name="Vertex Pharmaceuticals",
        report_mode="medium",
        source_audit=package["source_audit"],
    )

    assert first["status"] == "inserted"
    assert first["inserted"] is True
    assert first["updated"] is False
    assert second["status"] == "duplicate"
    assert second["inserted"] is False
    assert second["updated"] is True
    assert second["report_id"] == first["report_id"]

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT query, target_type, target_name, report_mode,
                   package_json, narratives_json, artifact_paths_json, source_audit_json
            FROM report_documents
            """
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    row = rows[0]
    assert row[:4] == ("Vertex pipeline", "company", "Vertex Pharmaceuticals", "medium")
    assert json.loads(row[4]) == package
    assert json.loads(row[5]) == updated_narratives
    assert json.loads(row[6]) == updated_artifacts
    assert json.loads(row[7]) == package["source_audit"]
