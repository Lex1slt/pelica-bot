#!/usr/bin/env python
"""原神语料构建：gi.yatta.moe 数据 API（随游戏版本更新）→ PRTS release 格式 → 现有建库。

  python scripts/build_db_genshin.py                    # 构建 data/paimon.db
  python scripts/build_db_genshin.py --db data/x.db
  python scripts/build_db_genshin.py --types aq,lq,iq   # 任务类型过滤
  python scripts/build_db_genshin.py --skip-build       # 只生成 release，不建库

数据源与更新性：
  - 真源 = gi.yatta.moe（Amber）数据 API：社区标准、随游戏版本持续更新、
    多语言；本脚本每次运行都实时拉取（确保最新版本）。
  - 语料范围：魔神任务(aq) + 传说任务(lq) + 邀约(iq) 的完整任务对话
    （role=派蒙/旅人/NPC 逐句台词）+ 全部角色档案（元素/称号/所属/生日/命之座）。
    世界任务(wq, 1149 个)默认跳过——多为一次性跑腿文本，性价比低；
    --types 可自行扩展。
  - 产物 = 标准 release 目录（catalog + shards + release-manifest.json），
    之后照常 `python scripts/build_db.py --db ... --release <release>`。
  - 原神语料无实体标注：entities/relations 表为空，检索走 FTS 全文路径
    （检索接口不变）。

安全约束：仅 https + gi.yatta.moe 域名白名单（解析 IP 须公网）；任务类型
参数白名单校验；产物路径限定 corpus/releases/ 内。
"""

from __future__ import annotations

import argparse
import gzip
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus" / "releases"
CACHE_DIR = ROOT / "corpus" / "genshin_cache"
API_HOST = "gi.yatta.moe"
API_BASE = f"https://{API_HOST}/api/v2/chs"
ALLOWED_TYPES = {"aq", "lq", "iq", "wq", "eq"}
MAX_LINES_PER_DOC = 800
DOCS_PER_SHARD = 300


def _check(url: str) -> str:
    p = urllib.parse.urlparse(url)
    if p.scheme != "https" or (p.hostname or "") != API_HOST:
        raise SystemExit(f"拒绝非白名单地址：{url}")
    for info in socket.getaddrinfo(p.hostname, 443):
        ip = ipaddress.ip_address(info[4][0])
        fake_ip = ip in ipaddress.ip_network("198.18.0.0/15")  # VPN/代理 fake-ip 段
        if (ip.is_loopback or ip.is_link_local or ip.is_reserved
                or (ip.is_private and not fake_ip)):
            raise SystemExit(f"{API_HOST} 解析到内网地址 {ip}，疑似劫持")
    return url


def _cache_path(kind: str, key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{kind}_{re.sub(r'[^A-Za-z0-9_-]', '_', key)}.json"


def fetch_json(path_or_url: str) -> dict:
    url = path_or_url if path_or_url.startswith("http") else _check(API_BASE + path_or_url)
    req = urllib.request.Request(url, headers={"User-Agent": "pelica-sync"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


_TAG_RE = re.compile(r"<[^>]*>")
_DOLLAR_RE = re.compile(r"\$[A-Za-z_#0-9]")
_WS_RE = re.compile(r"\s+")


def clean(text: str) -> str:
    """游戏文本清洗：去富文本标签/$标记，代词替换，压缩空白。"""
    t = text or ""
    t = _TAG_RE.sub("", t)
    t = _DOLLAR_RE.sub("", t)
    t = t.replace("{NICKNAME}", "旅行者").replace("{PLAYERNAME}", "旅行者")
    t = t.replace("#", "")
    return _WS_RE.sub(" ", t).strip()


def quest_lines(data: dict) -> list[tuple[str, str, str]]:
    """任务详情 → [(line_type, speaker_raw, text)]。

    对话节点散布在 taskData / narratorData / talkData 等不同容器里，
    但台词节点形态统一：{role: 说话人, text: [{text: 台词}]}——
    全树通用识别，不做容器名白名单。
    """
    lines: list[tuple[str, str, str]] = []

    def emit(kind: str, speaker: str, text: str) -> None:
        text = clean(text)
        if text:
            lines.append((kind, clean(speaker), text))

    def walk(node) -> None:
        if isinstance(node, dict):
            role = node.get("role")
            if isinstance(role, str) and isinstance(node.get("text"), list):
                for t in node["text"]:
                    raw = t.get("text") if isinstance(t, dict) else str(t)
                    if raw:
                        emit("dialogue", role, raw)
            sd = node.get("stepDescription")
            if isinstance(sd, str) and sd:
                emit("narration", "", sd)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data.get("storyList"))
    dedup: list[tuple[str, str, str]] = []
    for ln in lines:
        if dedup and dedup[-1] == ln:
            continue
        dedup.append(ln)
        if len(dedup) >= MAX_LINES_PER_DOC:
            break
    return dedup


def avatar_lines(data: dict) -> list[tuple[str, str, str]]:
    name = clean(data.get("name") or "")
    lines: list[tuple[str, str, str]] = []
    fet = data.get("fetter") if isinstance(data.get("fetter"), dict) else {}
    title = clean(str(fet.get("title") or ""))
    detail = clean(str(fet.get("detail") or ""))
    if detail:
        lines.append(("knowledge", name, detail))
    if title:
        lines.append(("knowledge", "", f"{name}的称号是「{title}」。"))
    element = clean(str(data.get("element") or ""))
    region = clean(str(data.get("region") or ""))
    weapon = clean(str(data.get("weaponType") or ""))
    rank = data.get("rank") or ""
    if element or region:
        parts = [p for p in (region, f"{element}属性", f"{rank}星", weapon + "角色") if p]
        lines.append(("knowledge", "", f"{name}是{'、'.join(parts)}。"))
    birth = data.get("birthday")
    if isinstance(birth, dict) and birth.get("month") and birth.get("day"):
        lines.append(("knowledge", "",
                      f"{name}的生日是{birth['month']}月{birth['day']}日。"))
    elif isinstance(birth, list) and len(birth) >= 2:
        lines.append(("knowledge", "",
                      f"{name}的生日是{birth[0]}月{birth[1]}日。"))
    native = clean(str(fet.get("native") or ""))
    if native:
        lines.append(("knowledge", "", f"{name}来自{native}。"))
    const = data.get("constellation")
    if isinstance(const, list) and const:
        first = const[0]
        c_name = clean(first.get("name") if isinstance(first, dict) else str(first))
        if c_name:
            lines.append(("knowledge", "", f"{name}的命之座是{c_name}。"))
    return [ln for ln in lines if ln[2]]


def write_pack(release: Path, pack_id: str, docs: list[dict]) -> None:
    pack_dir = release / pack_id
    shard_dir = pack_dir / "shards"
    catalog_dir = pack_dir / "catalog"
    shard_dir.mkdir(parents=True, exist_ok=True)
    catalog_dir.mkdir(parents=True, exist_ok=True)

    catalog_entries = []
    for si, start in enumerate(range(0, len(docs), DOCS_PER_SHARD)):
        chunk = docs[start:start + DOCS_PER_SHARD]
        shard_name = f"{si:05d}.jsonl.gz"
        with gzip.open(shard_dir / shard_name, "wt", encoding="utf-8") as f:
            for d in chunk:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        for d in chunk:
            catalog_entries.append({"document_id": d["document"]["document_id"],
                                    "shard_path": "shards/" + shard_name})
    with gzip.open(catalog_dir / "documents.jsonl.gz", "wt", encoding="utf-8") as f:
        for e in catalog_entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    (pack_dir / "pack-manifest.json").write_text(json.dumps(
        {"pack_id": pack_id, "documents": len(docs),
         "shards": len(range(0, len(docs), DOCS_PER_SHARD))},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  pack {pack_id}: {len(docs)} 篇文档")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/paimon.db")
    ap.add_argument("--types", default="aq,lq,iq",
                    help="任务类型（aq魔神 lq传说 iq邀约 wq世界 eq活动）")
    ap.add_argument("--skip-build", action="store_true", help="只生成 release 不建库")
    ap.add_argument("--refresh", action="store_true",
                    help="忽略本地缓存，强制重新拉取最新版本（更新语料用）")
    args = ap.parse_args()

    types = [t.strip() for t in args.types.split(",") if t.strip()]
    if not types or not set(types) <= ALLOWED_TYPES:
        raise SystemExit(f"--types 只允许 {sorted(ALLOWED_TYPES)}")

    print("拉取任务列表…")
    quests = fetch_json("/quest")["data"]["items"]
    picked = {qid: v for qid, v in quests.items()
              if str(v.get("type")) in types}
    print(f"任务 {len(quests)} 个，按类型 {types} 选取 {len(picked)} 个")

    print("拉取角色列表…")
    avatars = fetch_json("/avatar")["data"]["items"]
    print(f"角色 {len(avatars)} 个")

    release = CORPUS_DIR / f"genshin-v1-{date.today().isoformat()}"
    release.mkdir(parents=True, exist_ok=True)

    # -- 任务文档（逐个拉详情，实时最新版） -----------------------------------
    quest_docs: list[dict] = []
    for i, (qid, meta) in enumerate(sorted(picked.items(), key=lambda kv: int(kv[0])), 1):
        cache_file = _cache_path("quest", qid)
        data = None
        if cache_file.exists() and not args.refresh:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
        else:
            try:
                data = fetch_json(f"/quest/{qid}")["data"]
                cache_file.write_text(
                    json.dumps(data, ensure_ascii=False), encoding="utf-8")
            except Exception as exc:  # noqa: BLE001 单个任务失败不拖垮整体
                if not cache_file.exists():
                    print(f"  [warn] quest {qid} 拉取失败且无缓存：{exc}")
                    continue
                print(f"  [fallback] quest {qid} 用缓存")
                data = json.loads(cache_file.read_text(encoding="utf-8"))
        info = data.get("info") or {}
        title = clean(info.get("chapterTitle") or info.get("title") or f"任务{qid}")
        lines = quest_lines(data)
        if not lines:
            continue
        quest_docs.append({
            "document": {
                "document_id": f"genshin/quest/{qid}",
                "display_title": title,
                "document_category": "任务",
                "document_kind": str(meta.get("type") or ""),
            },
            "lines": [{"line_number": n + 1, "line_type": k,
                       "speaker_raw": sp, "text": tx}
                      for n, (k, sp, tx) in enumerate(lines)],
        })
        if i % 40 == 0:
            print(f"  任务详情 {i}/{len(picked)}，已产出文档 {len(quest_docs)}")

    # -- 角色档案 -------------------------------------------------------------
    avatar_docs: list[dict] = []
    for i, (aid, meta) in enumerate(sorted(avatars.items()), 1):
        if "-" in aid:  # 元素变体（如 10000005-pyro）与本体重复，跳过
            continue
        cache_file = _cache_path("avatar", aid)
        data = None
        if cache_file.exists() and not args.refresh:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
        else:
            try:
                data = fetch_json(f"/avatar/{aid}")["data"]
                cache_file.write_text(
                    json.dumps(data, ensure_ascii=False), encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                if not cache_file.exists():
                    print(f"  [warn] avatar {aid} 拉取失败且无缓存：{exc}")
                    continue
                print(f"  [fallback] avatar {aid} 用缓存")
                data = json.loads(cache_file.read_text(encoding="utf-8"))
        name = clean(data.get("name") or "")
        lines = avatar_lines(data)
        if not name or not lines:
            continue
        avatar_docs.append({
            "document": {
                "document_id": f"genshin/avatar/{aid}",
                "display_title": name,
                "document_category": "角色档案",
                "document_kind": "profile",
            },
            "lines": [{"line_number": n + 1, "line_type": k,
                       "speaker_raw": sp, "text": tx}
                      for n, (k, sp, tx) in enumerate(lines)],
        })

    version = f"genshin-v1-{date.today().isoformat()}"
    print(f"写出 release：{release}")
    write_pack(release, "genshin_quest", quest_docs)
    write_pack(release, "genshin_avatar", avatar_docs)
    (release / "release-manifest.json").write_text(json.dumps({
        "corpus_version": version,
        "packs": ["genshin_quest", "genshin_avatar"],
        "source": "gi.yatta.moe API v2 (chs)",
        "quest_types": types,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.skip_build:
        print("完成（--skip-build）")
        return 0

    print("建库…")
    db = Path(args.db)
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_db.py"),
         "--db", str(db), "--force", "--skip-relations",
         "--release", release.name],
        check=True, shell=False,
    )
    print(f"完成：{db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
