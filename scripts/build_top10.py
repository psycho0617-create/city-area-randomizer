# scripts/build_top10.py
# e-Stat CSV（町丁・字）から、市区町村ごとに人口上位Nのエリアを作る
# - 集計行（「町丁字コードxxxxの計」「〜の計」「総数」等）を除外
# - 「大字」「字」などの接頭語は表示名から削除（使用感優先）
# - out/areas_top10.json を生成

import argparse
import glob
import json
import os
import re
from collections import defaultdict
from datetime import datetime

import pandas as pd


# -----------------------------
# 文字列ユーティリティ
# -----------------------------
def s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and pd.isna(v):
        return ""
    v = str(v).strip()
    return "" if v in ("-", "—", "ｰ") else v


def to_int(v) -> int:
    v = s(v)
    if not v:
        return 0
    # "33,520" みたいなのを許容
    v = v.replace(",", "")
    try:
        return int(float(v))
    except Exception:
        return 0


# -----------------------------
# 除外・整形ルール
# -----------------------------
RE_AGG_1 = re.compile(r"町丁字コード\d+の計")
RE_AGG_2 = re.compile(r"(?:^|.*)(の計|計)$")  # 末尾が「計」or「の計」
RE_BAD = re.compile(r"(総数|不詳)")

def is_aggregate_row(name: str) -> bool:
    """集計っぽい行を弾く"""
    name = s(name)
    if not name:
        return True
    if "町丁字コード" in name:
        return True
    if RE_AGG_1.search(name):
        return True
    if RE_BAD.search(name):
        return True
    # 「○○の計」「○○計」系
    if RE_AGG_2.search(name):
        return True
    return False


def normalize_place_name(oaza_machi: str, aza_chome: str, strip_oaza=True) -> str:
    """
    表示用の地名を作る
    - 大字・町名 + 字・丁目名 を連結
    - 先頭の「大字」「字」を消す（使用感優先）
    """
    a = s(oaza_machi)
    b = s(aza_chome)

    # どっちも空なら無効
    if not a and not b:
        return ""

    # 先頭の「大字」「字」を消す（例：大字的場 -> 的場）
    if strip_oaza:
        if a.startswith("大字"):
            a = a.replace("大字", "", 1).strip()
        if a.startswith("字"):
            a = a.replace("字", "", 1).strip()
        if b.startswith("字"):
            b = b.replace("字", "", 1).strip()

    # 連結（例：岩神町 + 1丁目）
    name = (a + " " + b).strip() if a and b else (a or b)

    # 余計な全角・半角スペース調整
    name = re.sub(r"\s+", " ", name).strip()
    return name


# -----------------------------
# メイン処理
# -----------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data_glob", default="data/**/*.csv", help="入力CSVのglob")
    ap.add_argument("--topn", type=int, default=10, help="市内上位Nを保持（web側の上位プール）")
    ap.add_argument("--out_json", default="out/areas_top10.json", help="出力JSON")
    ap.add_argument("--encoding", default="cp932", help="CSVエンコード（cp932想定）")
    ap.add_argument("--header_row", type=int, default=3, help="CSVヘッダー行（0-index）。e-Statは3が多い")
    ap.add_argument("--strip_oaza", action="store_true", help="表示名から『大字』『字』を削除する（推奨）")
    ap.add_argument("--keep_level4", action="store_true", help="地域階層レベル4（丁目など）も残す")
    args = ap.parse_args()

    files = sorted(glob.glob(args.data_glob, recursive=True))
    if not files:
        raise RuntimeError("CSVが見つからない。data/ 配下にCSVがあるか確認してね。")

    # 市区町村ごとに人口を集計（同名が複数行ある場合は合算）
    # key: (pref, city, name) -> pop
    bucket = defaultdict(int)

    used_csv = 0
    skipped_csv = 0

    # 除外理由カウント（ログ）
    drop_reason = defaultdict(int)

    for f in files:
        try:
            df = pd.read_csv(
                f,
                dtype=str,
                header=args.header_row,
                encoding=args.encoding,
            )
        except Exception:
            skipped_csv += 1
            continue

        need_cols = ["都道府県名", "市区町村名", "大字・町名", "字・丁目名", "総数", "地域階層レベル", "町丁字コード"]
        if not all(c in df.columns for c in need_cols):
            skipped_csv += 1
            continue

        used_csv += 1

        for _, row in df.iterrows():
            pref = s(row.get("都道府県名"))
            city = s(row.get("市区町村名"))
            level = s(row.get("地域階層レベル"))
            cho_code = s(row.get("町丁字コード"))

            # 市レベルや総計レベルの行を弾く（町丁字コードが "-" とか、レベルが1/2）
            lvl = to_int(level)
            if lvl <= 2:
                drop_reason["level<=2"] += 1
                continue

            if not args.keep_level4 and lvl >= 4:
                drop_reason["level>=4_removed"] += 1
                continue

            # 町丁字コードが空/ハイフン系は集計行の可能性が高い
            if not cho_code:
                drop_reason["cho_code_empty"] += 1
                continue

            oaza = s(row.get("大字・町名"))
            aza = s(row.get("字・丁目名"))

            # 表示名を作る
            name = normalize_place_name(oaza, aza, strip_oaza=args.strip_oaza)

            # 集計っぽい行を除外
            if is_aggregate_row(name) or is_aggregate_row(oaza) or is_aggregate_row(aza):
                drop_reason["aggregate_like"] += 1
                continue

            pop = to_int(row.get("総数"))
            if pop <= 0:
                drop_reason["pop<=0"] += 1
                continue

            if not pref or not city or not name:
                drop_reason["missing_pref_city_name"] += 1
                continue

            bucket[(pref, city, name)] += pop

    if used_csv == 0:
        raise RuntimeError("有効なCSVが1件も読めなかった。header行/encodingが違う可能性あり。")

    # 市区町村ごとに上位Nへ
    city_map = defaultdict(list)  # (pref, city) -> [(name,pop)]
    for (pref, city, name), pop in bucket.items():
        city_map[(pref, city)].append((name, pop))

    out = {}
    for (pref, city), items in city_map.items():
        items.sort(key=lambda x: x[1], reverse=True)
        top_items = items[: args.topn]

        # e-Statの「市区町村コード」も入れたいなら後で拡張できるけど、
        # 現状webでは pref/city/name/pop があれば十分なのでこの形にする
        key = f"{pref}::{city}"
        out[key] = {
            "pref": pref,
            "city": city,
            "areas": [{"name": n, "pop": p} for n, p in top_items],
        }

    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as w:
        json.dump(out, w, ensure_ascii=False, indent=2)

    # web 側にもコピーしたい場合（同名ファイルで参照してるなら）
    # web/areas_top10.json がある運用っぽいので同期
    web_json = os.path.join("web", os.path.basename(args.out_json))
    try:
        os.makedirs("web", exist_ok=True)
        with open(web_json, "w", encoding="utf-8") as w:
            json.dump(out, w, ensure_ascii=False, indent=2)
    except Exception:
        pass

    print(f"OK: {args.out_json} を生成しました")
    print(f"  市区町村数: {len(out)} / 使用CSV: {used_csv} / スキップCSV: {skipped_csv}")
    print("  除外理由カウント:")
    for k, v in sorted(drop_reason.items(), key=lambda x: x[1], reverse=True):
        print(f"   - {k}: {v}")


if __name__ == "__main__":
    main()
