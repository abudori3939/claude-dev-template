# workflow_sch.md — kicad-cli / スクリプトによる回路図編集の作法

エージェントは KiCad GUI を持たないため、回路図・基板の読み書きはすべて **kicad-cli ＋ Python スクリプト（S式操作）** で行う。
このファイルはその具体的な手順・コマンド・コード雛形をまとめる。

## 0. 環境準備（最初の1回）

1. KiCad（プロジェクトで固定したメジャーバージョン。推奨 9.x）がインストールされていることを確認する:

   ```bash
   kicad-cli version
   ```

   Windows では PATH に無いことが多い。フルパス（例: `C:\Program Files\KiCad\9.0\bin\kicad-cli.exe`）を
   **CLAUDE.md「プロジェクト概要」に記録し、以降フルパスで呼ぶ**（Python 実行パスも同様）。

2. Python 依存を入れる:

   ```bash
   pip install kiutils pytest
   ```

3. 動作確認: 既存の回路図があれば `kicad-cli sch erc` が実行できること（パース確認を兼ねる）。

## 1. kicad-cli 基本コマンド集

`<sch>` = `hardware/<board>/<board>.kicad_sch`、`<pcb>` = 同 `.kicad_pcb`。出力は `outputs/` へ。

```bash
# ERC（回路図の lint。違反があれば非ゼロ終了）
kicad-cli sch erc --exit-code-violations -o outputs/erc.rpt <sch>

# ネットリスト出力（接続テストの入力。kicadxml 形式を使う）
kicad-cli sch export netlist --format kicadxml -o outputs/netlist.xml <sch>

# 回路図の出図（レビュー用）
kicad-cli sch export pdf -o outputs/sch.pdf <sch>
kicad-cli sch export svg -o outputs/svg/ <sch>

# BOM（フィールドはプロジェクトに合わせて調整）
kicad-cli sch export bom -o outputs/bom.csv --fields "Reference,Value,Footprint,MPN,Datasheet" <sch>

# DRC（基板の lint）
kicad-cli pcb drc --exit-code-violations -o outputs/drc.rpt <pcb>

# 基板の出図・製造データ
kicad-cli pcb export pdf -o outputs/pcb.pdf --layers "F.Cu,B.Cu,Edge.Cuts,F.Silkscreen" <pcb>
kicad-cli pcb export gerbers -o outputs/gerbers/ <pcb>
kicad-cli pcb export drill -o outputs/gerbers/ <pcb>
kicad-cli pcb export pos -o outputs/pos.csv --format csv <pcb>
kicad-cli pcb export step -o outputs/board.step <pcb>
```

## 2. TDD の実行手順（レッド → グリーン → リファクタ）

```bash
# レッド: 接続テストを先に書き、失敗を確認する
kicad-cli sch export netlist --format kicadxml -o outputs/netlist.xml <sch>
python -m pytest tests/ -x        # → 対象ブロックのテストがアサーション失敗すること

# グリーン: 回路図を編集（下記 §3）するたびに検証を回す
kicad-cli sch erc --exit-code-violations -o outputs/erc.rpt <sch>   # パース確認を兼ねる
kicad-cli sch export netlist --format kicadxml -o outputs/netlist.xml <sch>
python -m pytest tests/

# リファクタ後・PR 前: 出図して目視レビュー（サブエージェントに画像を見せる）
kicad-cli sch export pdf -o outputs/sch.pdf <sch>
```

接続テストの書き方は [`scripts/netlist_check.py`](scripts/netlist_check.py) のヘルパを使う。例:

```python
from netlist_check import Netlist

def test_mcu_power(netlist: Netlist):
    # 電源ピンが正しいネットに乗っているか
    assert netlist.connected("U1", "VDD", "+3V3")
    assert netlist.connected("U1", "VSS", "GND")

def test_uart_crossover(netlist: Netlist):
    # TX/RX が交差して結線されているか（ありがちなミスの検出）
    assert netlist.net_of("U1", "PA9") == netlist.net_of("J2", "2")

def test_bom_complete(netlist: Netlist):
    # 全部品にフットプリントが割当済みか
    for ref, comp in netlist.components().items():
        assert comp["footprint"], f"{ref} のフットプリントが未割当"
```

## 3. S式編集の作法（.kicad_sch をスクリプトで編集する）

### 原則

1. **必ずスクリプト（kiutils 等）経由で編集する。** S式を文字列置換で直接いじらない（括弧・UUID を壊す）。
2. **雛形コピー方式を基本にする。** シンボルをゼロから構築せず、**一度正しく配置された既存シンボル（または雛形シート）を複製し、UUID・リファレンス・座標・値だけ変える**。プロパティ構造の組み立てミスを避ける最も堅い方法。
3. **UUID は複製のたびに必ず新規生成する**（`uuid.uuid4()`）。UUID 重複はアノテーションやネット追跡を静かに壊す。
4. **座標はグリッド（1.27mm = 50mil）に必ず載せる。** グリッド外配置はワイヤが接続されない事故のもと。
5. **編集→保存→ERC→テスト を1編集単位ごとに回す。** 壊れた状態を持ち越さない。

### ラベル配線を優先する（エージェント作図の基本戦略）

長いワイヤの引き回しはエージェントには難しく、図も汚くなる。**ピンには短いスタブワイヤ＋ラベル（ブロック内はローカルラベル、ブロック間は階層ラベル/グローバルラベル）で結線する**。

- 利点: 結線が「ラベル名の一致」に還元され、スクリプトで堅牢に扱える。接続テストとの対応も明快。図の交差も消える。
- **ブロック間ネットのラベル名は spec.md の「境界の契約」と完全一致**させる（仕様と実装の突合がそのまま diff でできる）。
- 電源は電源シンボル（`+3V3`, `GND` 等）を使う。

### kiutils の骨組み

```python
import uuid
from kiutils.schematic import Schematic

sch = Schematic.from_file(path)          # パース
# … sch 内のシンボル・ワイヤ・ラベルを複製/追加/変更（雛形コピー方式）…
#    新規要素の uuid は str(uuid.uuid4()) で必ず振り直す
sch.to_file(path)                        # 保存
# 保存後は必ず kicad-cli sch erc でパース・電気チェック
```

> kiutils の詳細 API はバージョンで変わる。**書く前に、対象プロジェクトの実ファイルを小さく読んで構造を確認**し、
> 雛形コピー方式で差分最小の編集をすること。大規模な一括生成をする場合は、まず1シンボルで
> 「編集→GUI で人間が開いて確認」を1往復してから展開する。

### 回路図の可読性規約（リファクタ工程で満たす）

- 信号の流れは**左→右**（入力コネクタ左、出力右）。電源レール上・GND 下。
- **1ブロック＝1シート**（階層シート）。ルートシートはブロック図として読めるようにする。
- リファレンス指定子はブロック内で連番に整理（`kicad-cli` のアノテーションに頼らず、割当を spec の接続表と一致させる）。
- 定数・型番は Value フィールドに、選定根拠は parts.md に（図面に書き散らさない）。

## 4. レイアウト（.kicad_pcb）での支援作業

配置・配線は人間の GUI 作業が既定（kicad.md 参照）。エージェントがスクリプトでやってよいのは:

- 回路図→基板のネット同期確認（`kicad-cli pcb drc` は回路図との不一致も検出する）
- DRC・出図・製造データ生成（§1 のコマンド）
- 配置方針 md（フロアプラン）の作成、出図画像による配置・シルクのレビュー

pcbnew Python API による一括操作（例: リファレンス一括整列）は可能だが、**配線そのものをエージェントが行うのは既定では禁止**。行う場合は plan.md に明記し ADR に記録する。

## 5. やってはいけないこと（再掲・追加）

- KiCad GUI が開いているファイルへの書き込み（`*.lck` を見たら停止してユーザー確認）
- フォーマットバージョンを上げる保存（ユーザー合意＋ADR なしに新バージョンの KiCad で保存しない）
- 並列エージェントによる同一ファイル編集
- `outputs/` の生成物を手で編集する（必ず元ファイル→再出図）
