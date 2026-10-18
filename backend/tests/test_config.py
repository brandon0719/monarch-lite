from pathlib import Path

from app import config


def test_empty_path_env_vars_fall_back_to_the_default(monkeypatch):
    default = Path("/somewhere/default")
    for blank in ("", "   "):
        monkeypatch.setenv("FRONTEND_DIST", blank)
        assert config.env_path("FRONTEND_DIST", default) == default
    monkeypatch.delenv("FRONTEND_DIST")
    assert config.env_path("FRONTEND_DIST", default) == default
    monkeypatch.setenv("FRONTEND_DIST", "/custom/dist")
    assert config.env_path("FRONTEND_DIST", default) == Path("/custom/dist")


def test_module_paths_are_never_the_empty_path():
    for path in (config.DB_PATH, config.BACKUP_DIR, config.FRONTEND_DIST):
        assert path != Path("")
