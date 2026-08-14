# スタックガイド: RP2040 / RP2350 ファームウェア（PlatformIO + Arduino-Pico）

Raspberry Pi **RP2040 / RP2350**（Pico / Pico 2 および同系統の自作基板）のファームウェアを
**PlatformIO ＋ arduino-pico core（earlephilhower）** で開発する場合の具体的な作法。
CLAUDE.md と `agent_docs/common/coding_standards.md`（スタック非依存の原則）を、ここでファームウェア向けに具体化する。

**前提（このガイドが想定する環境）**

- ビルド環境: PlatformIO Core（CLI）。IDE は任意。
- framework: `arduino`（arduino-pico core / earlephilhower）。Pico SDK 直叩きは対象外。
- 対象 MCU: **RP2040 と RP2350 の両方**（両方ビルドが通ることを CI で保証する）。
- 並行処理: **ベアメタル単コア**（`loop()` 中心）。dual-core / FreeRTOS を使う場合は ADR に記録してから。
- 開発ホスト: Ubuntu。
- **実機への書き込み・電源投入・配線は人間が行う**（エージェントは USB に触れない前提）。

## このスタックの性格（実機が絡む TDD をどう成立させるか）

ファームウェアは「実機がないと動かない」が、**実機がないとテストできない設計にしないこと**でTDDを成立させる。
このガイドの中心はその一点にある。工程ごとの責務:

| 工程 | 主導 | エージェントの役割 |
|---|---|---|
| 要求・機能分割・ピン割当 | エージェント | 対話で引き出し plan / spec / pin_map に整形 |
| ロジック実装（変換・状態機械・プロトコル） | エージェント | **native ユニットテストで駆動**。このスタックの主戦場 |
| ハード層実装（ピン操作・バス・ライブラリ呼び出し） | エージェント | 薄く保つ。ここはテストせず、レビューと実機ゲートで担保 |
| ビルド（pico / pico2 両方） | エージェント | `pio run`。CI と同一コマンド |
| **書き込み・実機動作確認** | **人間** | エージェントは「実行するコマンド」と「何を見れば OK か」を提示し、返ってきたログを判定する |
| 静的解析・フォーマット | エージェント | `pio check` / clang-format。警告ゼロ |

> **エージェントは実機を持たない。** よって「動作確認しました」と書いてはならない。実機の判定材料は
> **人間が貼ったシリアルログ・観測結果だけ**であり、それを根拠に判断を書く。

## アーキテクチャ（2層分離）— このスタック最重要の規約

```
src/            Arduino 層（setup/loop・ピン操作・ライブラリ呼び出し）… 薄く保つ。native テスト対象外
lib/<domain>/   ロジック層（変換・状態機械・プロトコル解析・判定）    … ハード非依存。テストの本体
test/test_*/    native ユニットテスト（Unity）
```

規約:

- **ロジック層は `Arduino.h` を include しない。** `digitalWrite` / `Serial` / `Wire` などを直接呼ばない。
- **時刻は引数で受け取る。** ロジック層で `millis()` を呼ばず、`update(uint32_t now_ms, ...)` の形にする
  （時間依存の振る舞いをテストで完全に再現できるようにするため）。
- **I/O は注入する。** センサドライバは「レジスタ読み書き関数（またはバス I/F）」を注入できる形にし、
  native テストではフェイクを差す。Arduino のライブラリ型に直接依存しない。
- ブロッキング `delay()` は原則使わない（`loop()` はノンブロッキングに保つ）。使う場合は理由をコメントに書く。
- 割り込みハンドラは「フラグを立てる／リングバッファに積む」だけにし、判断はロジック層で行う。
  ISR と共有する変数は `volatile`、複数バイトの共有はクリティカルセクションで守る。
- グローバル状態を増やさない。状態は構造体／クラスに閉じ、`loop()` からは呼ぶだけにする。

> この分離ができていれば、機能の 8 割は PC 上のテストで開発でき、実機ゲートは「配線とタイミングの確認」に縮む。
> 分離が崩れた瞬間、TDD は成立しなくなり人間の実機作業が増える。**レビューで最初に見るのはここ。**

## 環境構築（Ubuntu）

```bash
# PlatformIO Core（CLI）
python3 -m pip install --user -U platformio      # または pipx install platformio
pio --version

# 静的解析ツール（pio check が呼ぶ）。clang-format は CI と同じメジャー版を入れる
sudo apt install -y cppcheck clang-format-18

# USB デバイス権限（書き込み・シリアル。人間が一度だけ実行）
curl -fsSL https://raw.githubusercontent.com/platformio/platformio-core/develop/platformio/assets/system/99-platformio-udev.rules \
  | sudo tee /etc/udev/rules.d/99-platformio-udev.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG dialout "$USER"                 # 反映には再ログインが必要
```

## platformio.ini（雛形）

```ini
[platformio]
default_envs = pico

; ---- 実機共通 ----
[mcu_base]
; RP2350（Pico 2）は PlatformIO 公式 platform では扱えない（下記「RP2040 / RP2350 の差分」参照）。
; fork をコミット SHA で固定して再現性を確保する。更新は独立した PR で行う。
platform = https://github.com/maxgerhardt/platform-raspberrypi.git#<commit-sha>
framework = arduino
board_build.core = earlephilhower
; build_flags は core / 外部ライブラリを含む「すべてのソース」に効く。ここに -Werror を置くと
; 他人のコードの警告でビルドが落ちるため、-Werror は自分のコードにだけ効く build_src_flags に置く。
build_flags = -Wall -Wextra
build_src_flags = -Werror
monitor_speed = 115200
check_tool = cppcheck
; 既定の検査対象は src/ と include/ のみ。ロジックは lib/ にあるので明示的に含める（最重要）
check_patterns = src, lib
check_flags = cppcheck: --enable=warning,style,performance --inline-suppr
check_severity = medium, high

[env:pico]                 ; RP2040
extends = mcu_base
board = pico

[env:pico2]                ; RP2350（Cortex-M33）
extends = mcu_base
board = rpipico2

; ---- ホスト（PC）テスト用。ここが TDD の主戦場 ----
[env:native]
platform = native
test_framework = unity
build_flags = -std=c++17 -Wall -Wextra -DUNIT_TEST   ; Unity 本体にも効くため -Werror は入れない
check_patterns = src, lib
```

- **core のバージョン固定**が必要なら `platform_packages` で指定する
  （`framework-arduinopico@https://github.com/earlephilhower/arduino-pico.git#<tag-or-sha>`）。
  ツールチェーンを `platform_packages` で注入する古い作法は非推奨なので使わない。
- 外部ライブラリは `lib_deps` で**バージョンを固定**する（`@^1.2.3` ではなく `@1.2.3`）。
- 自作基板を使う場合はボード定義を `boards/<board>.json` に置き、`board = <board>` で参照する。
- **`build_src_flags` は `src/` にしか効かない。** `lib/<domain>/` は「ライブラリ」として別途ビルドされるため、
  自作ロジック層にも `-Werror` を効かせたい場合は `lib/<domain>/library.json` に
  `{"build": {"flags": ["-Werror"]}}` を書く（外部ライブラリには波及しない）。

## ビルド・テスト・実行コマンド

```bash
pio test -e native            # ★ ユニットテスト（TDD のレッド／グリーンはここで判定）
pio run -e pico               # ビルド（RP2040）
pio run -e pico2              # ビルド（RP2350）
pio check -e pico             # 静的解析（cppcheck。check_patterns で src/ と lib/ を対象にすること）

# フォーマット。CI と同一の対象集合にするため git ls-files で列挙する
#（bash の ** は既定で再帰しないため src/**/*.cpp のような glob は使わない）
git ls-files '*.h' '*.hpp' '*.c' '*.cc' '*.cpp' | xargs -r clang-format -i

# ↓ 実機。エージェントは実行せず、人間に依頼する
pio run -e pico -t upload     # 書き込み
pio device monitor -b 115200  # シリアルログ確認
```

## テスト（TDD）

- フレームワークは **Unity**（PlatformIO 標準）。テストは `test/test_<対象>/test_main.cpp` に置く。
- **レッドは `pio test -e native` のアサーション失敗で示す。ビルドエラーはレッドと認めない**（CLAUDE.md 共通）。
- フェイク（時刻・バス・センサ応答）は `test/` 配下または `lib/<domain>/` 内のインターフェースとして用意し、
  実機の応答バイト列をテーブルで与える形にする。
- 浮動小数比較は許容誤差付き（`TEST_ASSERT_FLOAT_WITHIN`）。実時間・乱数に依存させない。
- テスト対象は**ロジック層**。`src/`（Arduino 層）は native ではビルドしない（既定の `test_build_src = no` のまま）。

### 実機ゲート（人間が行う確認。このスタック固有の DoD）

native テストが緑でも、実機で動く保証にはならない。**1 サイクルの最後に必ず実機ゲートを通す。**

1. **エージェント**: `pio test -e native` 緑 ／ `pio run -e pico` `-e pico2` 緑 を確認し、
   人間向けに次を提示する。
   - 実行するコマンド（`pio run -e pico -t upload` など）
   - 配線・準備（接続する部品、必要な電源、BOOTSEL の要否）
   - **合否の判定基準**（「シリアルに `temp=25.3` 形式で 1 秒ごとに出れば OK」など、見れば判断できる形）
2. **人間**: 書き込み・実行し、シリアルログや観測結果を PR にコメントで貼る。
3. **エージェント**: ログを判定し、合否と根拠を PR に記録する。失敗なら原因の仮説と次の手を出す。

> 実機で見つかった不具合は、**まず native テストで再現させてから直す**（再発防止のテストが残る）。
> 再現できないなら、それはロジック層に落とせていないサイン。設計を見直す。

## 自動品質ゲート

- ビルド警告ゼロ（自分のコードは `-Werror`。core / 外部ライブラリの警告で落とさないよう `build_src_flags` に置く）。
- `pio check`（cppcheck）の指摘ゼロ。**`check_patterns = src, lib` を必ず設定する**（既定では `lib/` が検査されず、
  ロジック層を一度も読まないまま「指摘ゼロ」になる）。
- `clang-format` 済み（`.clang-format` をリポジトリ直下に置く。CI では `--dry-run --Werror` で検査）。
  ローカルと CI で**同じバージョン・同じ対象ファイル集合**を使う。
- **Flash / RAM 使用量**をビルドログから PR に記載する（回帰の早期発見用。必須ゲートにはしない）。

## CI（GitHub Actions）

実機テストは CI では行わない（self-hosted runner に実機を繋がない限り不可能）。CI の責務は
**「両 MCU でビルドが通る」「native テストが緑」「静的解析が綺麗」**の 3 点。

```yaml
name: firmware
on: [push, pull_request]

jobs:
  build-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Cache PlatformIO
        uses: actions/cache@v4
        with:
          path: |
            ~/.platformio
            ~/.cache/pip
          key: pio-${{ runner.os }}-${{ hashFiles('platformio.ini') }}
      - name: Install
        run: |
          # ツールもバージョンを固定する（勝手な更新で無関係の PR が赤くなるのを防ぐ）。
          # 版は「実際に手元で通したもの」に置き換える。clang-format はランナーの OS で入手可能な版に合わせる。
          pip install platformio==<ver>
          sudo apt-get update && sudo apt-get install -y cppcheck clang-format-18
      - name: Unit tests (host)
        if: ${{ hashFiles('test/**') != '' }}
        run: pio test -e native
      - name: Build (RP2040 / RP2350)
        if: ${{ hashFiles('platformio.ini') != '' }}
        run: pio run -e pico -e pico2
      - name: Static analysis
        if: ${{ hashFiles('platformio.ini') != '' }}
        run: pio check -e pico --fail-on-defect medium --fail-on-defect high
      - name: Format check
        run: |
          files=$(git ls-files '*.h' '*.hpp' '*.c' '*.cc' '*.cpp')
          [ -z "$files" ] || clang-format-18 --dry-run --Werror $files
```

- **各ステップに `hashFiles(...)` のガードを付ける。** フェーズ0（`plan.md` / `spec.md` だけの PR）では
  `platformio.ini` も `test/` もまだ存在せず、ガードが無いと「直しようのない赤」になる。
- `pip install platformio==<ver>` と `clang-format-<N>` は**バージョンを固定**する。特に clang-format は
  メジャー更新で既定の整形結果が変わり、無関係の PR が一斉に赤くなる。**ローカルでも同じメジャー版を使う**こと。
- フォーマット検査の対象は**ローカルのコマンドと同一の集合**にする（片方だけ拡張子が漏れると検知できない）。
- 初回ビルドは platform / toolchain のダウンロードで数分かかる。キャッシュキーは `platformio.ini` の
  ハッシュにしてあるので、依存を更新した PR ではキャッシュミスが起きる（想定どおり）。

## リポジトリ構成（このスタックで追加するもの）

```
├── platformio.ini
├── src/
│   └── main.cpp                ← Arduino 層。setup/loop と配線だけ。薄く保つ
├── lib/
│   └── <domain>/               ← ロジック層（ハード非依存）。テストの本体
├── test/
│   └── test_<対象>/test_main.cpp  ← native ユニットテスト（Unity）
├── boards/                     ← 自作基板のボード定義（必要時）
├── .clang-format
└── agent_docs/project/
    └── pin_map.md              ← ピン割当表（下記）
```

### `pin_map.md`（ピン割当表）

ピン割当は**仕様であってコードのコメントではない**。`agent_docs/project/pin_map.md` に表で持ち、
`spec.md` の外部インターフェース（層1）から参照する。

| GPIO | 用途 | 方向 | 備考（プル・電圧・接続先） |
|---|---|---|---|
| GP2 | I2C0 SDA | 双方向 | 外部 4.7k プルアップ、センサ X |

- 自作基板の場合は **KiCad スタック（`kicad.md`）の回路図と一致していること**をレビュー項目にする。
  食い違ったら回路図が正。
- ピン番号をコード中に直書きせず、`constexpr uint8_t kPinSda = 2;` のように名前付き定数へ集約する。

## 開発フローの読み替え（CLAUDE.md のフロー ↔ このスタック）

| CLAUDE.md | このスタックでの実体 |
|---|---|
| plan.md | 機能分割＝**ペリフェラル／ドライバ単位**の実装順（Phase） |
| spec.md 層1（Phase 0） | 外部 I/O（電源・ピン割当・通信プロトコル・LED/UI）＋モジュール間の公開 I/F |
| spec.md 層2（着手時） | ドライバ／ロジックの関数 I/O・状態遷移・エラー時の振る舞い |
| **レッド** | `pio test -e native` のアサーション失敗（ビルドエラーは不可） |
| テスト承認 | テストコードと**ピン割当・プロトコル前提**をユーザーが承認 |
| **グリーン** | native テスト緑 ＋ `pio run -e pico` `-e pico2` 両方ビルド成功 |
| **リファクタリング** | ロジック層の責務整理・Arduino 層の薄化。テスト緑のまま |
| lint / 静的解析 | `-Werror` ＋ `pio check` ＋ clang-format |
| レビュー（PR） | コード diff ＋ **実機ゲートのログ** |
| 粒度 | **1 サイクル（＝1 PR）＝1 ペリフェラル／ドライバ**（M 相当） |

## RP2040 / RP2350 の差分と注意

- **RP2350 は PlatformIO 公式 platform では扱えない。** 公式 `platformio/platform-raspberrypi`（v1.20.0 時点）が
  同梱するボード定義は `pico` と `nanorp2040connect` の 2 つだけで、`rpipico2` が存在しない。
  arduino-pico 公式ドキュメントの案内どおり **maxgerhardt の fork を使う**（上記 ini 参照）。
  将来公式が対応したら、乗り換えを ADR に記録して platform 行を差し替える。
- `board = pico` では `board_build.core = earlephilhower` の明示が必要（`rpipico` 等では不要）。
- RP2350 の RISC-V コアを使う場合は `board_build.mcu = rp2350-riscv`。**既定では使わない**（使うなら ADR）。
- MCU 差分の条件コンパイルは最小限に留め、必要な場合はロジック層ではなく Arduino 層に閉じる。
- **RP2350 erratum E9（入力時のリーク電流）**: GPIO を入力（入力バッファ有効）にしてパッド電圧が
  中間電位にあると、リーク電流が最大 120 µA 程度流れる。内部プルダウンだけに頼った入力は
  中間電位で張り付くことがある。**外部プルダウン（8.2 kΩ 以下）を使う**か、読み出し時だけ入力バッファを
  有効化する。自作基板を設計する場合はこの前提を回路図側（KiCad スタック）に反映する。

## 依存の更新方針

- `platform` の commit SHA、`lib_deps` のバージョンは**固定**し、更新は**独立した PR**で行う
  （更新 PR では両 env のビルドと native テストが緑であることに加え、実機ゲートを 1 回通す）。
- 更新理由（バグ修正・新ボード対応など）を PR 本文に書く。惰性のバージョン上げはしない。

## レビューチェックリスト（PR を出す前に自己点検）

- [ ] `pio test -e native` 緑 ／ `pio run -e pico -e pico2` 両方ビルド成功 ／ `pio check` 指摘ゼロ（`lib/` も検査対象に入っているか）
- [ ] **ロジック層に `Arduino.h` 依存が漏れていない**（`millis()` 直呼び・`Serial` 直叩きが無い）
- [ ] 新しい振る舞いに対応するテストが追加されている（実機で見つけた不具合は再現テスト付き）
- [ ] ピン番号が定数化され、`pin_map.md`（自作基板なら回路図）と一致している
- [ ] `loop()` にブロッキング処理を持ち込んでいない（理由付きの例外を除く）
- [ ] Flash / RAM 使用量を PR に記載した
- [ ] **実機ゲートのログが PR にあり、判定結果を記録した**
- [ ] `progress.md` を更新した
