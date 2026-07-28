#!/usr/bin/env python3
"""KiCad リポジトリ衛生チェック（Windows / Ubuntu 混在対策の自動ゲート）.

作業者の OS が混ざっても「本質的な変更だけが git 差分に出る」ことを、人間の目視ではなく
CI の緑/赤で保証するためのチェック。review_checklist.md §0 を機械化したもの。

検査項目（すべて git に登録済みの内容＝コミットされる実体に対して行う）:
  1. CRLF 混入      … KiCad ファイル等に CRLF が入っていないか（.gitattributes の効き確認）
  2. 一時ファイル    … .gitignore 対象なのに追跡されているファイルが無いか（bak / autosave 等）
  3. 絶対パス        … ライブラリテーブル等にドライブレター・ホームディレクトリが無いか
  4. フォーマット版  … KiCad ファイルの (version ...) が全ファイルで揃い、固定値と一致するか
                        （OS 差ではなく KiCad バージョン差が混在の唯一の実害。ここで止める）

使い方:
    python check_repo_hygiene.py                      # 1〜3 を検査、4 は検出値の報告のみ
    python check_repo_hygiene.py --expect-version 20241229   # 4 も固定値と照合して検査

CI では --expect-version にプロジェクトで固定した値（CLAUDE.md「プロジェクト概要」に記録）を渡す。
違反があれば非ゼロ終了する。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict

# CRLF 混入を検査する対象（テキストとして LF 固定すべきもの）
TEXT_SUFFIXES = (
    ".kicad_sch", ".kicad_pcb", ".kicad_pro", ".kicad_sym", ".kicad_mod",
    ".kicad_dru", ".kicad_wks", ".net", ".py", ".md", ".yml", ".yaml", ".sh",
)
TEXT_NAMES = ("sym-lib-table", "fp-lib-table")

# 絶対パスを検査する対象（環境依存の参照が混入しやすいファイル）
PATH_CHECK_SUFFIXES = (".kicad_pcb", ".kicad_pro", ".kicad_sch")
PATH_CHECK_NAMES = TEXT_NAMES

# 環境依存の絶対パス表現。${KIPRJMOD} 相対でなければならない。
# ホームディレクトリの検査は、Windows パス（C:/Users/...）を二重に報告しないよう
# 直前にドライブレターが無い場合だけ一致させる。
ABS_PATH_PATTERNS = (
    (re.compile(rb"[A-Za-z]:[\\/]"), "Windows のドライブレター"),
    (re.compile(rb"(?<![A-Za-z]:)/home/"), "Linux のホームディレクトリ"),
    (re.compile(rb"(?<![A-Za-z]:)/Users/"), "macOS のホームディレクトリ"),
    (re.compile(rb"\$\{KICAD\d*_3DMODEL_DIR\}"), "環境依存の 3D モデル変数"),
)

VERSION_RE = re.compile(rb"\(version\s+(\d{8})\s*\)")


def git(*args: str) -> bytes:
    """git コマンドを実行し stdout をバイト列で返す。"""
    return subprocess.run(
        ["git", *args], check=True, stdout=subprocess.PIPE
    ).stdout


def tracked_files() -> list[str]:
    out = git("ls-files", "-z").decode("utf-8")
    return [p for p in out.split("\0") if p]


def blob(path: str) -> bytes:
    """インデックスに登録されている内容（＝コミットされる実体）を読む。

    作業ディレクトリではなく git の中身を見るのが要点。作業ディレクトリは
    OS や設定で改行が変わりうるが、リポジトリに入る実体はここで決まる。
    """
    return git("show", f":{path}")


def is_text_target(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path.endswith(TEXT_SUFFIXES) or name in TEXT_NAMES


def is_path_target(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path.endswith(PATH_CHECK_SUFFIXES) or name in PATH_CHECK_NAMES


def check_crlf(paths: list[str]) -> list[str]:
    """CRLF が混入したファイルを返す。"""
    return [p for p in paths if is_text_target(p) and b"\r\n" in blob(p)]


def check_tracked_ignored() -> list[str]:
    """.gitignore 対象なのに追跡されているファイルを返す。"""
    out = git("ls-files", "-ci", "--exclude-standard", "-z").decode("utf-8")
    return [p for p in out.split("\0") if p]


def check_abs_paths(paths: list[str]) -> list[tuple[str, str]]:
    """(ファイル, 違反内容) の一覧を返す。"""
    hits = []
    for path in paths:
        if not is_path_target(path):
            continue
        content = blob(path)
        for pattern, label in ABS_PATH_PATTERNS:
            if pattern.search(content):
                hits.append((path, label))
    return hits


def collect_versions(paths: list[str]) -> dict[str, list[str]]:
    """KiCad ファイルのフォーマットバージョン -> ファイル一覧。"""
    versions: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        if not path.endswith((".kicad_sch", ".kicad_pcb", ".kicad_sym", ".kicad_mod")):
            continue
        match = VERSION_RE.search(blob(path))
        if match:
            versions[match.group(1).decode()].append(path)
    return versions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expect-version",
        help="期待する KiCad フォーマットバージョン（例: 20241229）。指定時は不一致を違反とする",
    )
    args = parser.parse_args()

    paths = tracked_files()
    failures: list[str] = []

    if crlf := check_crlf(paths):
        failures.append(
            "CRLF が混入しています（.gitattributes を確認し、`git add --renormalize .` で直す）:\n"
            + "\n".join(f"  - {p}" for p in crlf)
        )

    if ignored := check_tracked_ignored():
        failures.append(
            "一時・バックアップファイルが追跡されています（`git rm --cached` で外す）:\n"
            + "\n".join(f"  - {p}" for p in ignored)
        )

    if abs_hits := check_abs_paths(paths):
        failures.append(
            "環境依存の絶対パスがあります（${KIPRJMOD} 相対に直す）:\n"
            + "\n".join(f"  - {p}: {label}" for p, label in abs_hits)
        )

    versions = collect_versions(paths)
    if versions:
        print("KiCad フォーマットバージョン:")
        for version, files in sorted(versions.items()):
            print(f"  {version}: {len(files)} ファイル")
        sys.stdout.flush()  # 失敗詳細（stderr）と順序が入れ替わらないようにする
        if len(versions) > 1:
            failures.append(
                "KiCad フォーマットバージョンが混在しています"
                "（作業者間で KiCad バージョンを揃える。詳細は kicad.md「環境」）:\n"
                + "\n".join(
                    f"  - {v}: {', '.join(files)}" for v, files in sorted(versions.items())
                )
            )
        elif args.expect_version and args.expect_version not in versions:
            found = next(iter(versions))
            failures.append(
                f"KiCad フォーマットバージョンが固定値と違います"
                f"（期待 {args.expect_version} / 実際 {found}）。"
                "意図的な更新ならユーザー合意のうえ ADR に記録し、固定値を更新すること"
            )

    if failures:
        print("\nリポジトリ衛生チェック: NG\n", file=sys.stderr)
        for failure in failures:
            print(failure + "\n", file=sys.stderr)
        return 1

    print("リポジトリ衛生チェック: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
