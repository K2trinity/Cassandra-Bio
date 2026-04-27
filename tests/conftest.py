from pathlib import Path


def pytest_configure(config):
    project_root = Path(__file__).resolve().parents[1]
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        return

    template_path = project_root / ".env.example"
    if template_path.exists():
        env_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
        return

    env_path.write_text(
        "GOOGLE_CLOUD_PROJECT=test-project\n"
        "GOOGLE_CLOUD_LOCATION=us-central1\n",
        encoding="utf-8",
    )
