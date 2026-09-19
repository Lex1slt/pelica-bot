#!/usr/bin/env python
"""GitHub 发布辅助（纯 API，无 git 子进程；git push 由外部完成）：

  python scripts/publish_github.py create-repo <repo-name>   # 建仓库，打印全名
  python scripts/publish_github.py release <owner/repo>      # 建 Release + 传资产

安全约束：仅访问 https://api.github.com 与 https://uploads.github.com
（域名白名单硬校验）；owner/repo 与仓库名均白名单正则校验；
令牌经 GCM 获取，只在内存中使用。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_BASE = "https://api.github.com"
UPLOAD_BASE = "https://uploads.github.com"
_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_REPO_FULL_RE = re.compile(r"^[A-Za-z0-9.-]+/[A-Za-z0-9_.-]{1,100}$")


def gcm_token() -> str:
    import os

    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        return tok
    out = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True, text=True, check=True, shell=False,
    ).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    raise SystemExit("未取到 GitHub 令牌：请设 GITHUB_TOKEN 环境变量或完成 GCM 授权")


def _check(url: str) -> str:
    p = urllib.parse.urlparse(url)
    if p.scheme != "https" or (p.hostname or "") not in ("api.github.com", "uploads.github.com"):
        raise SystemExit(f"拒绝非 GitHub API 地址：{url}")
    return url


def api(method: str, path: str, token: str, payload: dict | None = None):
    req = urllib.request.Request(
        _check(API_BASE + path), method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "pelica-release",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        return {"__http_error__": exc.code, "__detail__": exc.read().decode("utf-8", "replace")}
    return json.loads(body) if body else {}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    token = gcm_token()

    if mode == "create-repo":
        repo_name = sys.argv[2]
        if not _REPO_NAME_RE.fullmatch(repo_name):
            raise SystemExit(f"仓库名不合法：{repo_name!r}")
        owner = api("GET", "/user", token)["login"]
        print("GitHub 用户：", owner)
        r = api("POST", "/user/repos", token, {
            "name": repo_name,
            "description": "佩丽卡监督 —— 基于 PRTS 语料的《明日方舟：终末地》人设微信群机器人（免费开源 / 个人微信号 / 本机部署）",
            "private": False,
            "has_issues": True,
            "has_wiki": False,
        })
        if r.get("__http_error__") == 422:
            print("仓库已存在，复用")
            full = f"{owner}/{repo_name}"
        elif r.get("__http_error__"):
            raise SystemExit(f"建仓库失败：{r}")
        else:
            full = r["full_name"]
        if not _REPO_FULL_RE.fullmatch(full):
            raise SystemExit(f"仓库全名不合法：{full!r}")
        print(full)
        return 0

    if mode == "release":
        full = sys.argv[2]
        if not _REPO_FULL_RE.fullmatch(full):
            raise SystemExit(f"仓库全名不合法：{full!r}")
        notes = (ROOT / "docs" / "RELEASE_v1.0.0.md").read_text(encoding="utf-8")
        rel = api("POST", f"/repos/{full}/releases", token, {
            "tag_name": "v1.0.0",
            "target_commitish": "main",
            "name": "佩丽卡监督 v1.0.0",
            "body": notes,
            "draft": False,
            "prerelease": False,
        })
        if rel.get("__http_error__"):
            print("Release 创建返回", rel["__http_error__"], "，尝试取已有 Release")
            rel = api("GET", f"/repos/{full}/releases/tags/v1.0.0", token)
            if rel.get("__http_error__"):
                raise SystemExit(f"Release 不可用：{rel}")
        upload_base = rel["upload_url"].split("{")[0]
        for fname in ("佩丽卡监督-1.0.0-win64-setup.zip",
                      "佩丽卡监督-1.0.0-pelica.db.zip"):
            path = ROOT / "dist" / fname
            if not path.exists():
                print("[warn] 缺少资产，跳过：", fname)
                continue
            url = _check(upload_base) + "?name=" + urllib.parse.quote(fname)
            req = urllib.request.Request(
                url, method="POST", data=path.read_bytes(),
                headers={
                    "Authorization": f"token {token}",
                    "Content-Type": "application/zip",
                    "Content-Length": str(path.stat().st_size),
                    "User-Agent": "pelica-release",
                },
            )
            with urllib.request.urlopen(req) as resp:
                resp.read()
            print("资产已上传：", fname)
        print(f"Release 地址：https://github.com/{full}/releases/tag/v1.0.0")
        return 0

    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
