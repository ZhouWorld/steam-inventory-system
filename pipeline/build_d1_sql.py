#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段 2：把 inventory.json 转成 wrangler d1 execute 可执行的 import.sql

用法：
    python build_d1_sql.py --in inventory.json --out import.sql
"""

import argparse
import json
import sys


def esc(s):
    """SQL 字符串转义（单引号翻倍）"""
    if s is None:
        return "NULL"
    return "'" + str(s).replace("'", "''") + "'"


def num(v):
    """数值或 NULL"""
    if v is None or v == "":
        return "NULL"
    return str(v)


def build_sql(data):
    lines = []
    lines.append("-- 自动生成，请勿手动编辑")
    lines.append(f"-- steamid: {data.get('steamid')}")
    lines.append(f"-- fetched_at: {data.get('fetched_at')}")
    lines.append(f"-- descriptions: {len(data.get('descriptions', []))}")
    lines.append(f"-- assets: {len(data.get('assets', []))}")
    lines.append("")

    # ---------- 1. item_descriptions ----------
    descs = data.get("descriptions", [])
    desc_batch_size = 50
    for i in range(0, len(descs), desc_batch_size):
        batch = descs[i:i + desc_batch_size]
        values = []
        for d in batch:
            values.append("(" + ", ".join([
                esc(d.get("classid")),
                esc(d.get("instanceid") or "0"),
                esc(d.get("market_hash_name")),
                esc(d.get("name")),
                esc(d.get("icon_url")),
                num(d.get("commodity", 0)),
                num(d.get("tradable", 0)),
                num(d.get("marketable", 0)),
            ]) + ")")
        lines.append(
            "INSERT OR IGNORE INTO item_descriptions "
            "(classid, instanceid, market_hash_name, name, icon_url, commodity, tradable, marketable) "
            "VALUES\n" + ",\n".join(values) + ";"
        )
        lines.append("")

        # ---------- 2. assets ----------
    assets = data.get("assets", [])
    asset_batch_size = 20   # 加了 2 列，每行 15 列，批次调小
    for i in range(0, len(assets), asset_batch_size):
        batch = assets[i:i + asset_batch_size]
        values = []
        for a in batch:
            desc_sub = (
                "(SELECT id FROM item_descriptions WHERE "
                f"classid={esc(a.get('classid'))} AND instanceid={esc(a.get('instanceid') or '0')})"
            )
            values.append("(" + ", ".join([
                esc(a.get("assetid")),
                desc_sub,
                num(a.get("amount", 1)),
                num(a.get("float_value")),
                num(a.get("paint_seed")),
                num(a.get("paint_index")),
                num(a.get("def_index")),
                num(a.get("quality")),
                num(a.get("tradable")),
                num(a.get("marketable")),
                esc(data.get("steamid")),
                "CURRENT_TIMESTAMP",
                "CURRENT_TIMESTAMP",
                esc(a.get("inspect_link")),
                esc(a.get("float_source")),
            ]) + ")")

        lines.append(
            "INSERT INTO assets "
            "(assetid, description_id, amount, float_value, paint_seed, paint_index, "
            "def_index, quality, tradable, marketable, owner_steamid, first_seen_at, last_seen_at, "
            "inspect_link, float_source) "
            "VALUES\n" + ",\n".join(values) + "\n"
            "ON CONFLICT(assetid) DO UPDATE SET\n"
            "  float_value = excluded.float_value,\n"
            "  paint_seed = excluded.paint_seed,\n"
            "  paint_index = excluded.paint_index,\n"
            "  def_index = excluded.def_index,\n"
            "  quality = excluded.quality,\n"
            "  tradable = excluded.tradable,\n"
            "  marketable = excluded.marketable,\n"
            "  inspect_link = excluded.inspect_link,\n"
            "  float_source = excluded.float_source,\n"
            "  last_seen_at = CURRENT_TIMESTAMP;"
        )
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="infile", default="inventory.json")
    parser.add_argument("--out", dest="outfile", default="import.sql")
    args = parser.parse_args()

    with open(args.infile, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    sql = build_sql(data)
    with open(args.outfile, "w", encoding="utf-8") as fh:
        fh.write(sql)

    size_kb = len(sql.encode("utf-8")) / 1024
    print(f"已写入 {args.outfile}（{size_kb:.1f} KB）", file=sys.stderr)
    print(f"descriptions={len(data.get('descriptions', []))}  assets={len(data.get('assets', []))}",
          file=sys.stderr)


if __name__ == "__main__":
    main()