"""gateway 测试夹具：隔离数据目录 + FastAPI TestClient（不触网、不读仓库 .env）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from gateway.app import create_app  # noqa: E402


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch) -> Path:
    # PELICA_ENV_IMPORT 指向不存在的文件，阻断开发模式自动导入仓库 .env
    monkeypatch.setenv("PELICA_ENV_IMPORT", str(tmp_path / "no.env"))
    monkeypatch.setenv("PELICA_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    app = create_app(data_dir)
    token = app.state.token
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer " + token})
    yield client
    app.state.db.close()
