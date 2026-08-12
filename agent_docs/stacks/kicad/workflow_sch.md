# workflow_sch.md — kicad-cli / スクリプトによる回路図編集の作法

エージェントは KiCad GUI を持たないため、回路図・基板の読み書きはすべて **kicad-cli ＋ Python スクリプト（S式操作）** で行う。
このファイルはその具体的な手順・コマンド・コード雛形をまとめる。

## 0. 環境準備（最初の1回）

1. KiCad（プロジェクトで固定したメジャーバージョン。既定＝最新メジャー、執筆時点では 10.x。ユーザー指定があればそれに従う）がインストールされていることを確認する:

   ```bash
   kicad-cli version
   ```

   Windows では PATH に無いことが多い。フルパス（例: `C:\Program Files\KiCad\10.0\bin\kicad-cli.exe`）を
   **CLAUDE.md「プロジェクト概要」に記録し、以降フルパスで呼ぶ**（Python 実行パスも同様）。

2. Python 依存を入れる:

   ```bash
   pip install pytest
   ```

   **S式の読み書きは同梱の [`scripts/sexp_helper.py`](scripts/sexp_helper.py) を使う（kiutils は使わない）。**
   kiutils 1.4.8 は KiCad 10 フォーマットに追随しておらず、パースは通るが**再出力で
   `generator_version` / `embedded_fonts` 等が脱落して旧書式に再整形される**。
   これでは下記の検証ゲート（GUI 無変更保存でバイト一致）を満たせない。

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

### 接続テストの設計パターン（検出力を落とさないための必須事項）

接続テストは「書けば緑になる」ため、**設計を誤ると何も検出しないテスト**になりやすい。次の3点を守る。

1. **契約データを独立2系統にする（トートロジーの排除）。**
   テスト側の接続表は **spec.md の写しを手で持つ**。回路図を生成しているスクリプトのデータ（部品表・接続定義）を
   `import` して突き合わせてはならない。同じデータ同士の比較は必ず緑になり、仕様との乖離を一切検出しない。
   *テストが照合するのは「spec ↔ 実際のネットリスト」であって「生成データ ↔ 生成結果」ではない。*

2. **無名ネットは構造で検証する。**
   可読化（後述 §4）でラベルを外した純配管ネットは `Net-(R1-Pad2)` のような自動名になり、名前で書けなくなる。
   **「2部品が同じネットを共有しているか」**で検証する。このとき **GND・電源レールは必ず除外**する
   （除外しないとほぼ全部品対が GND を共有し、アサーションが常に真になる）。

   ```python
   def test_gate_drive_path(netlist: Netlist):
       # ラベル名に依存せず「U1 と R1 が電源/GND 以外のネットで繋がっている」ことを見る
       assert netlist.shared_nets("U1", "R1", exclude=("GND", "+3V3"))
   ```

3. **短絡の方向のアサーションも書く。**
   「繋がっていること」だけを書くと、**余分に繋がってしまった事故（短絡）を検出できない**。
   落ちてはいけない組み合わせを明示的に否定する。

   ```python
   def test_no_short(netlist: Netlist):
       assert not netlist.is_connected("Q1", "1", "U1", "1")   # ゲートノードが GND に落ちていない
       assert not netlist.is_connected("D1", "1", "D1", "2")   # LED の両端が同一ネットでない
   ```

> ⭐ 自分のテストの検出力は**ミューテーション（わざと回路図を壊してテストが落ちるか）**で確認できる。
> 「接続を1本消す」「2本を短絡させる」で落ちないなら、そのテストは仕様を守っていない。

## 3. S式編集の作法（.kicad_sch をスクリプトで編集する）

### 原則

1. **必ず [`scripts/sexp_helper.py`](scripts/sexp_helper.py) 経由で編集する。** S式を無手勝流の文字列置換で直接いじらない（括弧・UUID を壊す）。
2. **雛形コピー方式を基本にする。** シンボルをゼロから構築せず、**一度正しく配置された既存シンボル（または雛形シート）を複製し、UUID・リファレンス・座標・値だけ変える**。プロパティ構造の組み立てミスを避ける最も堅い方法。
3. **UUID は複製のたびに必ず新規生成する**（`uuid.uuid4()`）。UUID 重複はアノテーションやネット追跡を静かに壊す。
4. **座標はグリッド（1.27mm = 50mil）に必ず載せる。** グリッド外配置はワイヤが接続されない事故のもと。
5. **編集→保存→ERC→テスト を1編集単位ごとに回す。** 壊れた状態を持ち越さない。

### 雛形キットの収穫（スクリプトを書く前にやる）

エージェントは KiCad の書式を**推測してはならない**。生成を始める前に、**GUI で最小サンプルを作ってもらい、
KiCad が実際に書いたバイト列を書式テンプレートとして採取する**。

1. ユーザーに、空の回路図へ次を1個ずつ置いて保存してもらう: **シンボル・ローカルラベル・階層ラベル・電源シンボル・ワイヤ・NC フラグ**。
2. その `.kicad_sch` を読み、各要素の S式を**雛形（テンプレート文字列）として採取**する。
3. 以後の生成はこの雛形の**値だけを差し替える**（構造は一切考えない）。

**生成物の正しさは「KiCad GUI で開いて無変更のまま保存 → `git diff` がゼロ」をゲートにする。**
これが通れば、生成した S式は KiCad が書くものと完全に同型である（＝将来 GUI で触っても差分が暴れない）。

### ピン直付けラベル方式（座標事故の構造的排除）

長いワイヤの引き回しはエージェントには難しく、**座標のズレで「見た目は繋がっているのに未接続」**という
最悪の事故を生む。スクリプト生成の段階では **ワイヤを一切引かず、各ピンの接続点に直接ラベル／電源シンボルを置く**。

- 結線が「ラベル名の一致」だけに還元され、座標バグによる未接続が構造的に起こらない。
- **ブロック間ネットのラベル名は spec.md の「境界の契約」と完全一致**させる（仕様と実装の突合がそのまま diff でできる）。
- 電源は電源シンボル（`+3V3`, `GND` 等）を使う。
- 人間には読みにくい図になるが、それは次節の可読化工程で解消する（**機械が作る段階では正しさを優先する**）。

### sexp_helper の骨組み

```python
import uuid
from sexp_helper import SexpDoc     # agent_docs/stacks/kicad/scripts/sexp_helper.py

doc = SexpDoc.from_file(path)            # パース（全バイト保持。無編集ならバイト一致）
assert doc.serialize() == doc.text       # ラウンドトリップの確認（回帰テストにも入れる）

for node in doc.root.lists("symbol"):    # 構造の探索
    ...
doc.replace(node, new_text)              # 局所編集（触れていないバイトは不変）
#   新規要素の uuid は str(uuid.uuid4()) で必ず振り直す
#   注意: 編集すると既取得の Node は失効する（世代ガードが例外で検出）。root から取得し直す
doc.to_file(path)                        # 保存
# 保存後は必ず kicad-cli sch erc でパース・電気チェック
```

> **書く前に、対象プロジェクトの実ファイルを小さく読んで構造を確認**し、雛形コピー方式で差分最小の編集をすること。
> 大規模な一括生成をする場合は、まず1シンボルで「生成 → GUI で人間が開いて無変更保存 → diff ゼロ」を
> 1往復してから展開する。

### 回路図の可読性規約（可読化工程で満たす）

- 信号の流れは**左→右**（入力コネクタ左、出力右）。電源レール上・GND 下。
- **1ブロック＝1シート**（階層シート）。ルートシートはブロック図として読めるようにする。
- リファレンス指定子はブロック内で連番に整理（`kicad-cli` のアノテーションに頼らず、割当を spec の接続表と一致させる）。
- 定数・型番は Value フィールドに、選定根拠は parts.md に（図面に書き散らさない）。

## 4. 「生成 → 人間可読化 → 所有権移転」の2段階工程

**ピン直付けラベル方式で生成した回路図は、機械には最適だが人間には読めない**（ワイヤが無く、
ラベル名を目で追わないと回路の形が見えない）。一方でレイアウト工程・レビュー・将来の保守は
人間が図を読めることを前提にする。そこで**レイアウトに入る前に、可読化の工程を1サイクル挟む**。

| 段階 | 誰が | 何をするか | ファイルの所有 |
|---|---|---|---|
| ①生成 | エージェント（スクリプト） | ピン直付けラベルで回路を作る。接続テスト・ERC を通す | スクリプト |
| ②可読化 | **人間（GUI）** | ワイヤを引き直し、部品を意味のある配置に並べ替える | 移行中 |
| ③以降 | 人間（GUI） | 保守・修正は GUI で行う。**ジェネレータは凍結**する | GUI |

### なぜ安全に移行できるか

**検証がネットリストベース＝描画スタイル非依存**だから。ワイヤの引き方・部品の位置をどう変えても、
接続テストと ERC がそのまま無劣化で効き続ける。「人間が読みやすく描き直す」自由と「回路を壊さない」保証が両立する。

### 可読化 PR の不変条件

- **ネット名を担うラベルを、各ネットに最低1個は残す。** ワイヤで結線したなら中間のラベルは消してよいが、
  全部消すとネット名が自動名（`Net-(R1-Pad2)`）に変わる。**spec.md の「境界の契約」に出てくるネットは必ず名前を保持する。**
- **純配管ネット（spec に名前が出てこない、部品間を繋ぐだけのネット）は無名化してよい。**
  その場合、接続テストは §2 の**構造アサーション**（`shared_nets` / `is_connected`）に書き換える。
- **部品の追加・削除・定数変更をこの PR に混ぜない。** 可読化 PR は「回路変更ゼロ」であることが価値。

### 回路変更ゼロの機械証明（レビュー手法）

可読化 PR は差分が全面的になるため、目視レビューでは回路が変わっていないことを確認できない。
[`scripts/compare_netlists.py`](scripts/compare_netlists.py) で、**ネット名ではなく `(ref, pin)` の
分割（パーティション）**として比較し、等価であることを機械に証明させる。

```bash
git switch main && kicad-cli sch export netlist --format kicadxml -o /tmp/base.xml <sch>
git switch -    && kicad-cli sch export netlist --format kicadxml -o /tmp/head.xml <sch>
python agent_docs/stacks/kicad/scripts/compare_netlists.py /tmp/base.xml /tmp/head.xml
```

ネット名が変わっていても接続関係が同一なら OK（終了コード 0）。ネットの分割・併合（＝断線・短絡）や
ピンの増減があれば、その差分を表示して NG になる。**この結果を可読化 PR に貼る。**

### ジェネレータの凍結

所有権が GUI に移った後もジェネレータを回せる状態にしておくと、**人間の可読化作業を上書きで破壊する**事故が起きる。
所有権移転後は、スクリプト冒頭にガードを置いて誤実行を止める（理由と移行日を書き添える）:

```python
raise SystemExit(
    "この回路図は可読化済みで GUI が所有しています。再生成は人間の配線作業を破壊します。"
    "回路を変更する場合は GUI で編集し、接続テストで検証してください。"
)
```

## 5. KiCad の落とし穴（実運用で踏んだもの）

1. **リファレンス指定子は末尾に数字が必須。** `CN_POWER` のような数字なしのリファレンスは KiCad に
   **未アノテーション扱い**され、「基板を回路図から更新」がブロックされる。必ず `CN_POWER1` のように数字を付ける。
2. **kicadxml の `pinfunction` は `名前_番号` 形式**（例: ピン名 `K` のピン1 → `K_1`）。
   接続テストで機能名を使うと一致しないことがあるため、**ピン番号での指定が安全**。
3. **公式シンボルのピン電気型が ERC と噛み合わないことがある。** 例えばモジュール系シンボルの GND ピンが
   `power_out` になっていると、GND 同士の接続が `pin_to_pin` エラーになる。
   → **ローカルライブラリに複製し、ピンの電気型だけをパッチする**（ピン番号・名前・位置は変えない）。ADR に記録する。
4. **`extends` で派生したシンボルの空プロパティは、親の値を継承する。** 子シンボルで空にしたつもりの
   プロパティに親の値が入るため、フラット化・埋め込み時は親を解決してから確認する。

## 6. Windows 運用: GUI セッション後の改行正規化

**Windows の KiCad GUI は保存時に CRLF を書く。** リポジトリは `.gitattributes` で LF 管理しているため
コミット時に git が正規化するが、**作業ツリーには CRLF が残る**。これは次の作業を壊す:

- 生成スクリプトの出力（LF）と GUI 保存後のファイル（CRLF）がバイト比較できない
- ラウンドトリップ検証（無変更保存でバイト一致）が改行差だけで落ちる

**GUI で作業した後は必ず正規化を回す**（内容差分ゼロなので、いつ実行しても安全）:

```bash
python agent_docs/stacks/kicad/scripts/normalize_lf.py hardware/<board>
```

## 7. レイアウト（.kicad_pcb）での支援作業

配置・配線は人間の GUI 作業が既定（kicad.md 参照）。エージェントがスクリプトでやってよいのは:

- 回路図→基板のネット同期確認（`kicad-cli pcb drc` は回路図との不一致も検出する）
- DRC・出図・製造データ生成（§1 のコマンド）
- 配置方針 md（フロアプラン）の作成、出図画像による配置・シルクのレビュー

pcbnew Python API による一括操作（例: リファレンス一括整列）は可能だが、**配線そのものをエージェントが行うのは既定では禁止**。行う場合は plan.md に明記し ADR に記録する。

## 8. やってはいけないこと（再掲・追加）

- KiCad GUI が開いているファイルへの書き込み（`*.lck` を見たら停止してユーザー確認）
- フォーマットバージョンを上げる保存（ユーザー合意＋ADR なしに新バージョンの KiCad で保存しない）
- 並列エージェントによる同一ファイル編集
- `outputs/` の生成物を手で編集する（必ず元ファイル→再出図）
- **所有権が GUI に移った回路図に対してジェネレータを再実行する**（§4「ジェネレータの凍結」）
- **生成データを import した接続テストを書く**（§2。同じデータ同士の比較は何も検出しない）
