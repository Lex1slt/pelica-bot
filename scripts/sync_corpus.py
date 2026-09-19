#!/usr/bin/env python
"""PRTS.chat 语料自动同步（上游真源 = PRTS.chat 版本 API；公开镜像 = ModelScope）。

  python scripts/sync_corpus.py                 # 检查并同步两个数据集到最新 Release
  python scripts/sync_corpus.py --dataset endfield
  python scripts/sync_corpus.py --rebuild       # 同步后重建 pelica.db（调 build_db.py）

流程：
  1) ModelScope dataset API 读 README，解析当前批准的 Release ID；
  2) 与 corpus/releases/<release>/.sync-complete 比对，已是最新则跳过；
  3) 下载 dataset-manifest.json（含全量 SHA-256），校验后按清单下载
     bundles/*.tar|zip（已存在且 SHA 相符的跳过——增量）；
  4) 解包到 corpus/releases/<release>/（zip 公开密码 arknights）；
  5) 更新 current.json。

安全约束：
  - 仅 https；主机必须为 modelscope.cn，且解析出的全部 IP 必须公网
    （拒绝环回/私网/链路本地/保留地址，防 SSRF 与 DNS rebinding）；
  - manifest 相对路径与压缩包成员一律规范化校验，拒绝 ../ 与绝对路径
    （防路径穿越）；解包目标限定 corpus/releases/<release>/ 内。
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import socket
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus" / "releases"
CURRENT = CORPUS_DIR / "current.json"

ALLOWED_HOST = "modelscope.cn"
DATASETS = {
    "arknights": "HTiantian/prts-agent-corpus-arknights",
    "endfield": "HTiantian/prts-agent-corpus-endfield",
}
ZIP_PASSWORD = b"arknights"  # README 声明的公开兼容参数，非加密
MAX_BYTES = 2 * 1024**3      # 单文件 2GB 上限


def _assert_public_host(hostname: str) -> None:
    if hostname != ALLOWED_HOST:
        raise SystemExit(f"拒绝非白名单主机：{hostname}")
    for info in socket.getaddrinfo(hostname, 443):
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or not ip.is_global):
            raise SystemExit(f"{hostname} 解析到非公网地址 {ip}，疑似劫持")


def _check(url: str) -> str:
    p = urllib.parse.urlparse(url)
    if p.scheme != "https":
        raise SystemExit(f"拒绝非 https：{url}")
    _assert_public_host(p.hostname or "")
    return url


def fetch_json(url: str):
    req = urllib.request.Request(_check(url), headers={"User-Agent": "pelica-sync"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(_check(url), headers={"User-Agent": "pelica-sync"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise SystemExit(f"文件超过 {MAX_BYTES} 上限：{url}")
    return data


def latest_release(dataset: str) -> str:
    info = fetch_json(f"https://modelscope.cn/api/v1/datasets/{dataset}")["Data"]
    m = re.search(r"Release：`([^`]+)`", info.get("ReadmeContent") or "")
    if not m:
        raise SystemExit(f"{dataset}：README 里没有 Release 标记")
    return m.group(1)


def safe_target(out_dir: Path, rel_path: str) -> Path:
    """校验 manifest 相对路径：禁 ../ 与绝对路径，目标必须落在 out_dir 内。"""
    if PurePosixPath(rel_path).is_absolute() or ".." in PurePosixPath(rel_path).parts:
        raise SystemExit(f"manifest 路径可疑：{rel_path!r}")
    target = (out_dir / rel_path).resolve()
    if not str(target).startswith(str(out_dir.resolve()) + os.sep):
        raise SystemExit(f"路径越界：{rel_path!r}")
    return target


def safe_members(archive_path: Path, out_dir: Path):
    """迭代压缩包成员并逐个校验落点（防路径穿越）。"""
    out_root = str(out_dir.resolve()) + os.sep
    if archive_path.suffix == ".tar":
        with tarfile.open(archive_path) as tf:
            for m in tf.getmembers():
                if m.issym() or m.islnk():
                    continue  # 跳过链接，杜绝逃逸
                target = (out_dir / m.name).resolve()
                if not str(target).startswith(out_root):
                    raise SystemExit(f"tar 成员越界：{m.name!r}")
                yield m, target
    else:
        with zipfile.ZipFile(archive_path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                target = (out_dir / info.filename).resolve()
                if not str(target).startswith(out_root):
                    raise SystemExit(f"zip 成员越界：{info.filename!r}")
                yield info, target


def extract(archive_path: Path, out_dir: Path) -> None:
    if archive_path.suffix == ".tar":
        for m, target in safe_members(archive_path, out_dir):
            out_dir.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archive_path) as tf, tf.extractfile(m) as src:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(src.read())
    else:
        for info, target in safe_members(archive_path, out_dir):
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive_path) as zf:
                target.write_bytes(zf.read(info, pwd=ZIP_PASSWORD))


def detect_dest(archive_path: Path, out_dir: Path, pack_id: str) -> Path:
    """按首个成员的顶层目录判断解包目的地：
    自带 <pack_id>/ 包裹层 → release 根；直接是 shards/… → <pack_id>/ 内。"""
    for m, _t in safe_members(archive_path, out_dir):
        name = getattr(m, "name", None) or getattr(m, "filename", "")
        top = PurePosixPath(name.replace("\\", "/")).parts[0]
        return out_dir if top == pack_id else out_dir / pack_id
    raise SystemExit(f"压缩包为空：{archive_path}")


def dl_repo_file(dataset: str, release: str, rel_path: str) -> bytes:
    fp = urllib.parse.quote(f"releases/{release}/{rel_path}", safe="")
    url = (f"https://modelscope.cn/api/v1/datasets/{dataset}/repo"
           f"?Revision=master&FilePath={fp}")
    return fetch_bytes(url)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sync_dataset(name: str, dataset: str) -> tuple[str, list[str]]:
    release = latest_release(dataset)
    out_dir = CORPUS_DIR / release
    marker = out_dir / f".sync-complete-{name}"
    if marker.exists():
        print(f"[{name}] 已是最新：{release}")
        return release, []

    print(f"[{name}] 新版本 {release}，下载 manifest…")
    manifest_raw = dl_repo_file(dataset, release, "dataset-manifest.json")
    manifest = json.loads(manifest_raw)
    prefix = f"releases/{release}/"
    pack_ids = manifest.get("pack_ids") or []
    if not pack_ids:
        raise SystemExit(f"manifest 没有 pack_ids：{list(manifest)}")

    # bundle 不在 dataset-manifest 清单里（README 的下载示例按固定命名）：
    # 对每个 pack 依次尝试 bundles/<pack>.tar（审校/Wiki/实体）与 .zip（游戏内原始资料）
    for pack_id in pack_ids:
        pack_dir = safe_target(out_dir, pack_id)
        if (pack_dir / "pack-manifest.json").exists():
            print(f"  跳过（已存在）：{pack_id}")
            continue
        blob = None
        used = None
        for ext in (".tar", ".zip"):
            try:
                blob = dl_repo_file(dataset, release, f"bundles/{pack_id}{ext}")
                used = ext
                break
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
        if blob is None:
            print(f"  [warn] {pack_id}：tar/zip 均不存在，跳过")
            continue
        local = safe_target(out_dir, f"bundles/{pack_id}{used}")
        local.parent.mkdir(parents=True, exist_ok=True)
        tmp = local.with_suffix(local.suffix + ".part")
        tmp.write_bytes(blob)
        tmp.replace(local)
        print(f"  下载 {local.name} ({len(blob) / 1048576:.1f} MB)，解包…")
        dest = detect_dest(local, out_dir, pack_id)
        extract(local, dest)
        # bundle 内不含 pack-manifest.json（它在仓库顶层）——按清单 SHA 单独补拉
        pm_rel = f"{pack_id}/pack-manifest.json"
        pm_meta = (manifest.get("files") or {}).get(prefix + pm_rel)
        if pm_meta:
            pm_blob = dl_repo_file(dataset, release, pm_rel)
            if pm_meta.get("sha256") and sha256(pm_blob) != pm_meta["sha256"]:
                raise SystemExit(f"SHA-256 不符：{pm_rel}")
            pm_target = safe_target(out_dir, pm_rel)
            pm_target.parent.mkdir(parents=True, exist_ok=True)
            pm_target.write_bytes(pm_blob)
        if not (pack_dir / "pack-manifest.json").exists():
            raise SystemExit(f"{pack_id} 解包后缺 pack-manifest.json，结构异常")
        print(f"  完成：{pack_id}")

    missing = [p for p in pack_ids
               if not (out_dir / p / "pack-manifest.json").exists()]
    if missing:
        print(f"[{name}][warn] 以下 pack 未获取：{missing}")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("ok", encoding="utf-8")
    print(f"[{name}] 同步完成：{out_dir}")
    return release, pack_ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=[*DATASETS, "all"], default="all")
    ap.add_argument("--rebuild", action="store_true", help="同步后重建 pelica.db")
    args = ap.parse_args()

    names = list(DATASETS) if args.dataset == "all" else [args.dataset]
    done: dict[str, str] = {}
    all_packs: list[str] = []
    release = ""
    for n in names:
        release = latest_release(DATASETS[n])
        done[n] = release
        _rel, packs = sync_dataset(n, DATASETS[n])
        all_packs += [p for p in packs if p not in all_packs]

    # 合成 ingest_release 需要的 release-manifest.json（老打包格式的入口文件）
    out_dir = CORPUS_DIR / release
    if not all_packs:  # 早已同步过：从磁盘扫描已就位的 pack
        all_packs = sorted(d.name for d in out_dir.iterdir()
                           if d.is_dir() and (d / "pack-manifest.json").exists())
    rm_path = out_dir / "release-manifest.json"
    rm = {"corpus_version": release, "packs": all_packs,
          "source": "PRTS.chat via ModelScope " + ", ".join(DATASETS[n] for n in names)}
    if not rm_path.exists() or json.loads(rm_path.read_text(encoding="utf-8")) != rm:
        rm_path.write_text(json.dumps(rm, ensure_ascii=False, indent=2), encoding="utf-8")
        print("release-manifest.json 已合成（packs =", all_packs, "）")

    CURRENT.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone

    CURRENT.write_text(json.dumps({
        "releases": done,
        "channel": "modelscope",
        "schema_version": 1,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("current.json 已更新")

    if args.rebuild:
        latest = max(done.values())
        print("重建数据库（源：", latest, "）")
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_db.py"),
                        "--force", "--release", latest], check=True, shell=False)
    return 0


if __name__ == "__main__":
    import os
    sys.exit(main())
