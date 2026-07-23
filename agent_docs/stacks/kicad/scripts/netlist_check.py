#!/usr/bin/env python3
"""KiCad ネットリスト（kicadxml 形式）の接続テスト用ヘルパ。

TDD の「レッド」で使う: 接続アサーションを pytest で先に書き、
回路図の実装（グリーン）でテストを通す。

使い方:
  1. ネットリストを出力する:
       kicad-cli sch export netlist --format kicadxml -o outputs/netlist.xml <sch>
  2. tests/conftest.py にフィクスチャを置く:

       import pytest
       from netlist_check import Netlist

       @pytest.fixture(scope="session")
       def netlist():
           return Netlist.load("outputs/netlist.xml")

  3. テストを書く:

       def test_mcu_power(netlist):
           assert netlist.connected("U1", "VDD", "+3V3")

デバッグ用の単体実行:
  python netlist_check.py outputs/netlist.xml            # 全ネットとノード一覧
  python netlist_check.py outputs/netlist.xml --ref U1   # 指定部品のピン接続一覧
"""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from collections import defaultdict


class Netlist:
    """kicadxml ネットリストのパース結果。

    - ピンは「ピン番号」（例 "7"）でも「ピン名/機能名」（例 "VDD"）でも指定できる。
    - ネット名は完全一致のほか、階層名（例 "/power/+3V3"）の末尾セグメント一致も許す。
    """

    def __init__(self, root: ET.Element) -> None:
        # ref -> {"value": ..., "footprint": ...}
        self._components: dict[str, dict[str, str]] = {}
        for comp in root.iter("comp"):
            ref = comp.get("ref", "")
            self._components[ref] = {
                "value": (comp.findtext("value") or "").strip(),
                "footprint": (comp.findtext("footprint") or "").strip(),
            }

        # ネット名 -> [(ref, pin番号, ピン機能名), ...]
        self._nets: dict[str, list[tuple[str, str, str]]] = {}
        # (ref, ピン番号) -> ネット名 / (ref, ピン機能名) -> ネット名の集合
        self._by_pin: dict[tuple[str, str], str] = {}
        self._by_func: dict[tuple[str, str], set[str]] = defaultdict(set)
        for net in root.iter("net"):
            name = net.get("name", "")
            nodes = []
            for node in net.iter("node"):
                ref = node.get("ref", "")
                pin = node.get("pin", "")
                func = node.get("pinfunction", "")
                nodes.append((ref, pin, func))
                self._by_pin[(ref, pin)] = name
                if func:
                    self._by_func[(ref, func)].add(name)
            self._nets[name] = nodes

    @classmethod
    def load(cls, path: str) -> "Netlist":
        return cls(ET.parse(path).getroot())

    # ---- 部品 ----

    def components(self) -> dict[str, dict[str, str]]:
        """全部品。ref -> {"value", "footprint"}"""
        return dict(self._components)

    def component(self, ref: str) -> dict[str, str]:
        if ref not in self._components:
            raise KeyError(f"部品 {ref} がネットリストに存在しない")
        return self._components[ref]

    # ---- 接続 ----

    def net_of(self, ref: str, pin: str) -> str:
        """ref のピン（番号または機能名）が乗っているネット名を返す。

        機能名指定で複数の異なるネットに該当する場合（同名ピンが複数あるIC等）は
        エラーにするので、その場合はピン番号で指定し直す。
        未接続ピンは KeyError。
        """
        if (ref, pin) in self._by_pin:
            return self._by_pin[(ref, pin)]
        nets = self._by_func.get((ref, pin), set())
        if len(nets) == 1:
            return next(iter(nets))
        if len(nets) > 1:
            raise ValueError(
                f"{ref} のピン機能 {pin} は複数ネット {sorted(nets)} に該当する。ピン番号で指定すること"
            )
        raise KeyError(f"{ref} のピン {pin} はどのネットにも乗っていない（未接続または名称違い）")

    def connected(self, ref: str, pin: str, net_name: str) -> bool:
        """ref のピンが net_name（末尾セグメント一致可）に乗っているか。"""
        try:
            actual = self.net_of(ref, pin)
        except (KeyError, ValueError):
            return False
        return self._net_matches(actual, net_name)

    def refs_on(self, net_name: str) -> set[str]:
        """ネットに乗っている部品リファレンスの集合。"""
        refs: set[str] = set()
        for name, nodes in self._nets.items():
            if self._net_matches(name, net_name):
                refs.update(ref for ref, _, _ in nodes)
        return refs

    def nets(self) -> list[str]:
        return sorted(self._nets)

    @staticmethod
    def _net_matches(full_name: str, query: str) -> bool:
        return full_name == query or full_name.rsplit("/", 1)[-1] == query


def _main() -> None:
    parser = argparse.ArgumentParser(description="kicadxml ネットリストのダンプ（デバッグ用）")
    parser.add_argument("netlist", help="kicadxml ネットリストのパス")
    parser.add_argument("--ref", help="指定部品のピン接続だけ表示")
    args = parser.parse_args()

    nl = Netlist.load(args.netlist)
    for name in nl.nets():
        nodes = [(r, p, f) for r, p, f in nl._nets[name] if not args.ref or r == args.ref]
        if not nodes:
            continue
        print(name)
        for ref, pin, func in sorted(nodes):
            label = f"{pin}({func})" if func else pin
            print(f"  {ref}.{label}")


if __name__ == "__main__":
    _main()
