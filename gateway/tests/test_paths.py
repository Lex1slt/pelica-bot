"""数据目录解析优先级（任务书 §4.2）。"""

from __future__ import annotations

from pathlib import Path

from gateway.paths import resolve_data_dir


def test_pelica_home_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("PELICA_HOME", str(tmp_path / "custom"))
    monkeypatch.chdir(tmp_path)  # 即便 CWD 看起来像仓库
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "pelica").mkdir()
    assert resolve_data_dir() == tmp_path / "custom"


def test_repo_cwd_is_dev_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("PELICA_HOME", raising=False)
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "pelica").mkdir()
    monkeypatch.chdir(tmp_path)
    assert resolve_data_dir() == tmp_path / "data"


def test_default_appdata(tmp_path, monkeypatch):
    monkeypatch.delenv("PELICA_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.chdir(tmp_path)  # 无 main.py/pelica：不是仓库
    assert resolve_data_dir() == tmp_path / "roaming" / "pelica-console"
