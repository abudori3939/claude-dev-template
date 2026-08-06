#!/usr/bin/env python3
"""2つのネットリストが電気的に等価かを判定する（回路変更ゼロ PR の機械証明）.

用途: 回路図の**可読化・整理**（ワイヤの引き直し・部品の再配置・ラベルの無名化）を
した PR で、「見た目は全部変わったが回路は1ミリも変えていない」ことを証明する。
目視では追えないので機械に証明させる。

原理: ネットリストを **ネット名ではなく `(ref, pin)` の集合の分割（パーティション）**
として比較する。ネット名は可読化で正当に変わる（ラベルを外すと `Net-(R1-Pad2)` の
ような自動名になる）が、**どのピンとどのピンが繋がっているか**は変わってはならない。
パーティションが一致すれば、名前が何であれ回路は等価。

使い方:
    # main と PR head のネットリストをそれぞれ出力してから比較する
    git switch main   && kicad-cli sch export netlist --format kicadxml -o /tmp/base.xml <sch>
    git switch -      && kicad-cli sch export netlist --format kicadxml -o /tmp/head.xml <sch>
    python compare_netlists.py /tmp/base.xml /tmp/head.xml

等価なら "回路等価: OK" と表示して終了コード 0、差があれば差分を表示して 1。
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET

Pin = tuple[str, str]  # (リファレンス, ピン番号)


def load_partition(path: str) -> tuple[set[frozenset[Pin]], dict[frozenset[Pin], str]]:
    """ネットリストを (ref, pin) 集合の分割として読む。

    戻り値: (分割, 各グループの代表ネット名)。ネット名は差分表示にのみ使い、
    等価判定には使わない。
    """
    root = ET.parse(path).getroot()
    partition: set[frozenset[Pin]] = set()
    names: dict[frozenset[Pin], str] = {}
    for net in root.iter("net"):
        pins = frozenset(
            (node.get("ref", ""), node.get("pin", "")) for node in net.iter("node")
        )
        if not pins:
            continue  # ピンの乗っていないネットは回路に影響しない
        partition.add(pins)
        names[pins] = net.get("name", "")
    return partition, names


def describe(pins: frozenset[Pin], name: str) -> str:
    listed = ", ".join(f"{ref}.{pin}" for ref, pin in sorted(pins))
    return f"  [{name}] {listed}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", help="比較元のネットリスト（例: main のもの）")
    parser.add_argument("head", help="比較先のネットリスト（例: PR head のもの）")
    args = parser.parse_args()

    base, base_names = load_partition(args.base)
    head, head_names = load_partition(args.head)

    only_base = base - head
    only_head = head - base

    # 部品・ピンの集合そのものが変わっていないかも見る（部品追加/削除の検出）
    base_pins = {p for group in base for p in group}
    head_pins = {p for group in head for p in group}
    lost_pins = base_pins - head_pins
    new_pins = head_pins - base_pins

    print(f"ネット数: base={len(base)} head={len(head)}")
    print(f"接続ピン数: base={len(base_pins)} head={len(head_pins)}")

    if not only_base and not only_head:
        print("\n回路等価: OK（ネット名は変わっていても接続関係は同一）")
        return 0

    sys.stdout.flush()
    print("\n回路等価: NG（接続関係が変わっています）\n", file=sys.stderr)

    if lost_pins:
        print("消えたピン（部品削除・未接続化の疑い）:", file=sys.stderr)
        for ref, pin in sorted(lost_pins):
            print(f"  - {ref}.{pin}", file=sys.stderr)
        print(file=sys.stderr)
    if new_pins:
        print("増えたピン（部品追加・結線追加の疑い）:", file=sys.stderr)
        for ref, pin in sorted(new_pins):
            print(f"  - {ref}.{pin}", file=sys.stderr)
        print(file=sys.stderr)

    if only_base:
        print("base にしか無い接続グループ:", file=sys.stderr)
        for group in sorted(only_base, key=lambda g: sorted(g)):
            print(describe(group, base_names[group]), file=sys.stderr)
        print(file=sys.stderr)
    if only_head:
        print("head にしか無い接続グループ:", file=sys.stderr)
        for group in sorted(only_head, key=lambda g: sorted(g)):
            print(describe(group, head_names[group]), file=sys.stderr)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
