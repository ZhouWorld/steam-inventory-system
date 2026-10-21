#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段 2：拉取 CS2 库存 → 解析浮点 → 输出 inventory.json

用法：
    pip install requests
    python cs2_float_query.py --steamid 76561198000000000 --out inventory.json

输出：
    inventory.json（descriptions + assets，供 build_d1_sql.py 消费）
"""

import argparse
import json
import re
import struct
import sys
import time
import zlib
from urllib.parse import unquote

try:
    import requests
except ImportError:
    requests = None

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
INSPECT_MARKER = "csgo_econ_action_preview"
PAYLOAD_MIN_HEX = 12
PAYLOAD_MAX_HEX = 4096
STEAM_INVENTORY_URL = "https://steamcommunity.com/inventory/{steamid}/730/{contextid}"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_HEX_RE = re.compile(r"^[0-9A-Fa-f]+$")


# ---------------------------------------------------------------------------
# 浮点解码（和原脚本一致，保留）
# ---------------------------------------------------------------------------
def _read_varint(buf, i):
    val = 0; shift = 0
    while True:
        if i >= len(buf): raise ValueError("varint 越界")
        b = buf[i]; i += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80): return val, i
        shift += 7
        if shift > 70: raise ValueError("varint 过长")


def _float_from_bits(bits):
    return struct.unpack("<f", struct.pack("<I", bits & 0xFFFFFFFF))[0]


def _parse_sticker(buf):
    st = {}; i = 0
    while i < len(buf):
        try: tag, i = _read_varint(buf, i)
        except ValueError: break
        field, wire = tag >> 3, tag & 7
        try:
            if wire == 0: v, i = _read_varint(buf, i)
            elif wire == 2:
                ln, i = _read_varint(buf, i); v = buf[i:i+ln]; i += ln
            elif wire == 5: v = buf[i:i+4]; i += 4
            elif wire == 1: v = buf[i:i+8]; i += 8
            else: break
        except ValueError: break
        if field == 1: st["slot"] = v
        elif field == 2: st["stickerId"] = v
        elif field == 3 and len(v) == 4: st["wear"] = struct.unpack("<f", v)[0]
        elif field == 4 and len(v) == 4: st["scale"] = struct.unpack("<f", v)[0]
        elif field == 5 and len(v) == 4: st["rotation"] = struct.unpack("<f", v)[0]
        elif field == 10: st["pattern"] = v
    return st


def decode_payload(payload_hex):
    payload_hex = payload_hex.strip()
    if len(payload_hex) < PAYLOAD_MIN_HEX or len(payload_hex) > PAYLOAD_MAX_HEX:
        raise ValueError("载荷长度不合法")
    if len(payload_hex) % 2: raise ValueError("十六进制串长度必须为偶数")
    if not _HEX_RE.match(payload_hex): raise ValueError("载荷含非十六进制字符")

    wire = bytes.fromhex(payload_hex)
    key = wire[0]
    raw = bytes(b ^ key for b in wire)
    if raw[0] != 0x00: raise ValueError("还原后首字节应为 0x00")

    proto = raw[1:-4]
    if len(proto) < 2: raise ValueError("载荷过短")

    cks_link = int.from_bytes(raw[-4:], "big")
    crc = zlib.crc32(b"\x00" + proto) & 0xFFFFFFFF
    cks_calc = ((crc & 0xFFFF) ^ (len(proto) * crc)) & 0xFFFFFFFF
    checksum_ok = (cks_link == cks_calc)

    out = {"defIndex": None, "paintIndex": None, "paintSeed": None, "paintWear": None,
           "quality": None, "stickers": []}
    i = 0; seen = 0
    while i < len(proto):
        tag, i = _read_varint(proto, i)
        field, wire = tag >> 3, tag & 7
        seen += 1
        if seen > 100: break
        if wire == 0: v, i = _read_varint(proto, i)
        elif wire == 2:
            ln, i = _read_varint(proto, i); v = proto[i:i+ln]; i += ln
        elif wire == 5: v = proto[i:i+4]; i += 4
        elif wire == 1: v = proto[i:i+8]; i += 8
        else: break
        if field == 3: out["defIndex"] = v
        elif field == 4: out["paintIndex"] = v
        elif field == 5: out["rarity"] = v
        elif field == 6: out["quality"] = v
        elif field == 7: out["paintWear"] = _float_from_bits(v)
        elif field == 8: out["paintSeed"] = v
        elif field == 12: out["stickers"].append(_parse_sticker(v))

    if out["paintWear"] is not None and not (0.0 <= out["paintWear"] <= 1.0):
        checksum_ok = False
    out["checksumOk"] = checksum_ok
    return out


def parse_link(link):
    """从检视链接里提取候选十六进制载荷。"""
    info = {"candidates": [], "mode": "unknown"}
    if not link: return info
    try:
        decoded = unquote(unquote(link.strip()))
    except Exception:
        decoded = link.strip()
    idx = decoded.find(INSPECT_MARKER)
    body = decoded[idx + len(INSPECT_MARKER):] if idx >= 0 else decoded
    body = body.strip()
    if not body: return info

    cands = []
    if re.match(r"^[SM]\d", body):
        m = re.match(r"^([SM])(\d+)", body)
        rest = body[m.end():]
        m = re.match(r"^A(\d+)", rest)
        if m: rest = rest[m.end():]
        m = re.match(r"^D(.+)$", rest)
        if m:
            d = m.group(1).strip()
            if _HEX_RE.match(d) and len(d) % 2 == 0 and len(d) >= PAYLOAD_MIN_HEX:
                cands.append(d)
        info["mode"] = "classic" if not cands else "masked"
    else:
        if _HEX_RE.match(body) and len(body) % 2 == 0 and len(body) >= PAYLOAD_MIN_HEX:
            cands.append(body)
        if body[:1].upper() == "A" and len(body) - 1 >= PAYLOAD_MIN_HEX \
                and (len(body) - 1) % 2 == 0 and _HEX_RE.match(body[1:]):
            cands.append(body[1:])
        info["mode"] = "masked" if cands else "unknown"
    info["candidates"] = cands
    return info


def resolve_float_from_link(link):
    """
    返回 (float_value, float_source)：
      float_source = 'local' | 'classic' | 'placeholder' | 'unknown'
    """
    if not link:
        return None, "unknown"
    # 占位符模板直接跳过
    if "%propid:" in link or re.search(r"%[A-Za-z_][A-Za-z0-9_:]*%", link):
        return None, "placeholder"
    info = parse_link(link)
    for cand in info["candidates"]:
        try:
            data = decode_payload(cand)
            if data.get("checksumOk") and data.get("paintWear") is not None:
                return data["paintWear"], "local"
        except Exception:
            continue
    if info["mode"] == "classic":
        return None, "classic"
    return None, "unknown"


# ---------------------------------------------------------------------------
# 库存拉取（支持 context 2 和 16）
# ---------------------------------------------------------------------------
def _extract_inspect_link(desc, steamid, assetid):
    for key in ("actions", "owner_actions", "market_actions"):
        for act in (desc.get(key) or []):
            link = (act or {}).get("link") or ""
            if "csgo_econ_action_preview" not in link:
                continue
            if "%propid:" in link:
                return link
            out = (link.replace("%owner%", str(steamid))
                       .replace("%assetid%", str(assetid))
                       .replace("%appid%", "730")
                       .replace("%contextid%", "2"))
            return out
    return ""


import time

def fetch_inventory_context(steamid, contextid, timeout=30, max_pages=60,
                            max_retries=5, cookies=None):
    """
    拉取单个 context 的全部物品。
    返回 (descriptions, assets, prop_map)
      prop_map: assetid -> {propertyid: value}
    """
    if requests is None:
        raise RuntimeError("需要 requests：pip install requests")

    # ⭐ 所有状态变量在循环前初始化
    all_descs = []
    all_assets = []
    prop_map = {}
    start_assetid = None

    session = requests.Session()
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": f"https://steamcommunity.com/profiles/{steamid}/inventory/",
    }
    session.headers.update(headers)

    if cookies:
        for k, v in cookies.items():
            if v:
                session.cookies.set(k, v, domain="steamcommunity.com")

    for page in range(1, max_pages + 1):
        params = {"l": "zh_cn", "count": 500}
        if start_assetid:
            params["start_assetid"] = start_assetid

        url = STEAM_INVENTORY_URL.format(steamid=steamid, contextid=contextid)

        resp = None
        for attempt in range(max_retries):
            resp = session.get(url, params=params, timeout=timeout)
            if resp.status_code == 429:
                wait = 10 * (2 ** attempt)
                print(f"  ⏳ context {contextid} 429，等待 {wait}s 后重试 ({attempt+1}/{max_retries})",
                      file=sys.stderr)
                time.sleep(wait)
                continue
            break

        if resp is None or resp.status_code == 429:
            raise RuntimeError(f"context {contextid} 连续 429，请等待 15 分钟后再试")
        if resp.status_code == 403:
            raise RuntimeError("Steam 403：库存未公开或 Cookie 无效")
        resp.raise_for_status()

        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(f"context {contextid} 返回 success=false")

        all_descs.extend(data.get("descriptions", []))
        all_assets.extend(data.get("assets", []))

        # ⭐ 提取 asset_properties
        for ap in (data.get("asset_properties") or []):
            aid = str(ap.get("assetid"))
            props = {}
            for p in (ap.get("asset_properties") or []):
                pid = p.get("propertyid")
                if pid is None:
                    continue
                if "float_value" in p:
                    props[pid] = p["float_value"]
                elif "int_value" in p:
                    props[pid] = p["int_value"]
                elif "string_value" in p:
                    props[pid] = p["string_value"]
            if props:
                prop_map[aid] = props

        print(f"  context {contextid} 第 {page} 页，累计 {len(all_assets)} 件，"
              f"asset_properties {len(prop_map)} 条", file=sys.stderr)

        if data.get("more_items") and data.get("last_assetid"):
            start_assetid = str(data["last_assetid"])
            time.sleep(2)
        else:
            break

    return all_descs, all_assets, prop_map


def fetch_full_inventory(steamid, timeout=30, cookies=None):
    """拉 context 2 + context 16，去重 descriptions，合并 assets 和 prop_map。"""
    desc_map = {}
    assets_out = []
    all_prop_map = {}

    for idx, ctx in enumerate(("2", "16")):
        if idx > 0:
            print(f"  等待 8 秒再拉 context {ctx} ...", file=sys.stderr)
            time.sleep(8)

        try:
            descs, assets, prop_map = fetch_inventory_context(
                steamid, ctx, timeout=timeout, cookies=cookies
            )
        except Exception as e:
            print(f"  ⚠️ context {ctx} 拉取失败：{e}", file=sys.stderr)
            continue

        all_prop_map.update(prop_map)

        for d in descs:
            key = (d.get("classid"), d.get("instanceid"))
            if key not in desc_map:
                desc_map[key] = d

        for a in assets:
            key = (a.get("classid"), a.get("instanceid"))
            desc = desc_map.get(key) or {}
            aid = str(a.get("assetid"))
            props = all_prop_map.get(aid) or {}

            fv = None
            paint_seed = None
            paint_index = None
            def_index = None
            quality = None
            fsrc = "unknown"

            # ⭐ propertyid 2 直接是浮点
            if 2 in props:
                fv = props[2]
                fsrc = "property"

            # ⭐ propertyid 1 是 defindex
            if 1 in props:
                def_index = props[1]

            # ⭐ propertyid 6 是载荷，解码补充 paint_seed / paint_index
            if 6 in props:
                try:
                    dd = decode_payload(props[6])
                    if dd.get("checksumOk"):
                        if fv is None and dd.get("paintWear") is not None:
                            fv = dd["paintWear"]
                            fsrc = "local"
                        paint_seed = dd.get("paintSeed")
                        paint_index = dd.get("paintIndex")
                        def_index = def_index or dd.get("defIndex")
                        quality = dd.get("quality")
                except Exception:
                    pass

            # 兜底：从检视链接解析（完整模板时有效）
            if fv is None:
                link = _extract_inspect_link(desc, steamid, a.get("assetid"))
                fv_link, fsrc_link = resolve_float_from_link(link)
                if fv_link is not None:
                    fv = fv_link
                    fsrc = fsrc_link

            assets_out.append({
                "assetid": aid,
                "classid": str(a.get("classid")),
                "instanceid": str(a.get("instanceid") or "0"),
                "contextid": ctx,
                "amount": int(a.get("amount", 1)),
                "float_value": fv,
                "float_source": fsrc,
                "paint_seed": paint_seed,
                "paint_index": paint_index,
                "def_index": def_index,
                "quality": quality,
                "tradable": 1 if desc.get("tradable") == 1 else 0,
                "marketable": 1 if desc.get("marketable") == 1 else 0,
            })

    descriptions_out = []
    for d in desc_map.values():
        descriptions_out.append({
            "classid": str(d.get("classid")),
            "instanceid": str(d.get("instanceid") or "0"),
            "market_hash_name": d.get("market_hash_name") or d.get("name") or "",
            "name": d.get("name") or "",
            "icon_url": d.get("icon_url") or "",
            "commodity": 1 if d.get("commodity") == 1 else 0,
            "tradable": 1 if d.get("tradable") == 1 else 0,
            "marketable": 1 if d.get("marketable") == 1 else 0,
        })

    return descriptions_out, assets_out


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="拉取 CS2 库存 → inventory.json")
    parser.add_argument("--steamid", required=True, help="SteamID64（17 位数字）")
    parser.add_argument("--out", default="inventory.json", help="输出 JSON 路径")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--steam-login-secure", default="",
                        help="浏览器 cookie steamLoginSecure 的值（带 Cookie 可大幅降低 429 概率）")
    parser.add_argument("--sessionid", default="",
                        help="浏览器 cookie sessionid 的值")
    args = parser.parse_args()

    # ⭐ 构造 cookies
    cookies = {}
    if args.steam_login_secure:
        cookies["steamLoginSecure"] = args.steam_login_secure
    if args.sessionid:
        cookies["sessionid"] = args.sessionid

    if cookies:
        print(f"使用登录态请求（Cookie: {', '.join(cookies.keys())}）", file=sys.stderr)
    else:
        print("⚠️ 未提供 Cookie，匿名请求容易被 429 限流", file=sys.stderr)

    print(f"拉取账号 {args.steamid} 的 CS2 库存 ...", file=sys.stderr)
    descs, assets = fetch_full_inventory(args.steamid, timeout=args.timeout, cookies=cookies)
    print(f"descriptions={len(descs)}  assets={len(assets)}", file=sys.stderr)

    payload = {
        "steamid": args.steamid,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "descriptions": descs,
        "assets": assets,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"已写入 {args.out}", file=sys.stderr)

    local = sum(1 for a in assets if a["float_source"] == "local")
    prop = sum(1 for a in assets if a["float_source"] == "property")
    ph = sum(1 for a in assets if a["float_source"] == "placeholder")
    classic = sum(1 for a in assets if a["float_source"] == "classic")
    unknown = sum(1 for a in assets if a["float_source"] == "unknown")
    print(f"浮点来源：local={local}  property={prop}  placeholder={ph}  classic={classic}  unknown={unknown}",
          file=sys.stderr)


if __name__ == "__main__":
    main()