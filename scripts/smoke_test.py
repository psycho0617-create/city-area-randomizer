# scripts/smoke_test.py
import json
import random
from pathlib import Path

DATA_PATH = Path("out/areas_top10.json")

def main():
    if not DATA_PATH.exists():
        raise SystemExit("out/areas_top10.json が見つかりません。先に build_top10.py を実行してね。")

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    # まずは市区町村名で検索できるように index を作る
    # key: "札幌市" みたいな文字 → value: [code1, code2...]（重複保険）
    index = {}
    for code, v in data.items():
        city = v.get("city", "")
        if city:
            index.setdefault(city, []).append(code)

    print("市区町村名を入力してね（例：札幌市 / 品川区 / 那覇市）")
    while True:
        q = input("> ").strip()
        if not q:
            continue
        if q.lower() in ["q", "quit", "exit"]:
            break

        codes = index.get(q)
        if not codes:
            # 部分一致の候補を出す
            candidates = [k for k in index.keys() if q in k]
            if candidates:
                print("見つからないけど近い候補：")
                for c in candidates[:20]:
                    print(" -", c)
            else:
                print("見つからない。例：札幌市 / 品川区 / 那覇市")
            continue

        code = codes[0]
        areas = data[code]["areas"]

        # 上位10からランダム3件（重複なし）
        picks = random.sample(areas, k=min(3, len(areas)))

        print(f"\n{data[code]['pref']} {data[code]['city']}（上位{len(areas)}からランダム）")
        for a in picks:
            print(f" - {a['name']}（{a['pop']}人）")
        print("")

if __name__ == "__main__":
    main()
