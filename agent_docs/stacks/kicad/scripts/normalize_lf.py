#!/usr/bin/env python3
"""KiCad ファイルの CRLF を LF に正規化する（Windows の GUI セッション後に実行）.

Windows の KiCad GUI は保存時に CRLF を書く。リポジトリは `.gitattributes` で LF 管理
しているため、コミット時には git が正規化してくれるが、**作業ツリーは CRLF のまま残る**。
これは次の作業を分かりにくくする:

  - 生成スクリプトの出力（LF）と GUI 保存後のファイル（CRLF）がバイト比較できない
  - ラウンドトリップ検証（無編集保存でバイト一致）が改行差で落ちる

そこで **GUI セッションの後にこれを実行し、作業ツリーを git 格納形（LF）に揃える**。
内容の差分はゼロなので、いつ実行しても安全。

使い方:
    python normalize_lf.py hardware/<board>            # 指定ディレクトリ直下の KiCad ファイル
    python normalize_lf.py hardware/<board> --recursive # 配下を再帰的に処理
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# .kicad_prl はローカル状態ファイル（.gitignore 対象）のため触らない
SKIP_SUFFIXES = {".kicad_prl"}


def normalize(path: Path) -> bool:
    """CRLF を LF に置換する。変更したら True。"""
    raw = path.read_bytes()
    fixed = raw.replace(b"\r\n", b"\n")
    if fixed == raw:
        return False
    path.write_bytes(fixed)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="KiCad ファイルのあるディレクトリ（例: hardware/<board>）")
    parser.add_argument(
        "--recursive", action="store_true", help="サブディレクトリも処理する（lib/ 等を含める場合）"
    )
    args = parser.parse_args()

    target = Path(args.target)
    if not target.is_dir():
        print(f"ディレクトリが見つかりません: {target}", file=sys.stderr)
        return 1

    pattern = "**/*.kicad_*" if args.recursive else "*.kicad_*"
    changed = 0
    for path in sorted(target.glob(pattern)):
        if path.suffix in SKIP_SUFFIXES or not path.is_file():
            continue
        if normalize(path):
            changed += 1
            print(f"normalized: {path}")

    print(f"CRLF→LF 正規化: {changed} ファイルを変更")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
