# ci_kicad.md — GitHub Actions（ERC / DRC / 接続テスト / 出図）

「PR で合格したコードのみマージ」を KiCad でも**緑チェックで保証**するための CI 設定手順。
ローカル（workflow_sch.md §2）と**同一コマンド**を PR ごとに実行し、出図物を artifact に添付してレビュアーが図を見られるようにする。

## 前提

- 公式 Docker イメージ `kicad/kicad:<version>` を使う（**プロジェクトで固定したバージョン＝ローカルと必ず一致させる**。既定は最新メジャー。例: `kicad/kicad:10.0`）。
- イメージは非 root ユーザーで動くため、checkout や apt の権限問題が出る場合は `options: --user root` を付ける。
- **イメージには `pip` も `ensurepip` も入っていない**（Debian ベース）。Python 依存は apt で `python3-pip` を入れてから導入する（下記ワークフロー例）。
- 衛生チェックスクリプトは**コピーせず `agent_docs/stacks/kicad/scripts/` を直接参照する**（コピーの二重管理を避ける。テンプレート由来のリポジトリには `agent_docs/` がそのまま含まれる）。
- `<board>` はプロジェクトの基板名に置換する。

> ⭐ 下記ワークフローは `kicad/kicad:10.0` イメージ（2026-08 時点）で **CI 緑を実証済み**。

## ワークフロー例（`.github/workflows/kicad.yml`）

```yaml
name: kicad
on: [pull_request]

env:
  SCH: hardware/<board>/<board>.kicad_sch
  PCB: hardware/<board>/<board>.kicad_pcb
  # TODO(プロジェクト骨格の作成時): KiCad プロジェクトを生成したら (version ...) の実値を
  # 設定し、衛生チェックに --expect-version "$KICAD_FORMAT_VERSION" を付ける
  # （CLAUDE.md「プロジェクト概要」にも記録する）
  # KICAD_FORMAT_VERSION: "XXXXXXXX"

jobs:
  check:
    runs-on: ubuntu-latest
    container:
      image: kicad/kicad:10.0
      options: --user root
    steps:
      - uses: actions/checkout@v4

      - name: Python 依存
        # kicad/kicad イメージ（Debian）には pip / ensurepip が無いため apt で導入する
        run: |
          apt-get update -qq
          apt-get install -y -qq python3-pip
          python3 -m pip install --break-system-packages kiutils pytest

      # Windows / Ubuntu 混在対策の自動ゲート。人間が目視で追わずに済ませるための要。
      # KiCad ファイルの有無に関係なく常時実行する（最初のドキュメント PR から効かせる）
      - name: リポジトリ衛生チェック（CRLF / 一時ファイル / 絶対パス / バージョン混在）
        # コンテナは root で動くがワークスペースの所有者が異なるため、git が
        # dubious ownership で失敗する。safe.directory の登録が必要
        run: |
          git config --global --add safe.directory "$GITHUB_WORKSPACE"
          python3 agent_docs/stacks/kicad/scripts/check_repo_hygiene.py

      # 回路図がまだ無いフェーズ（フェーズ0・骨格作成）でも緑になるよう、ファイルの有無で分岐する
      - name: ERC（lint 相当）
        if: ${{ hashFiles(env.SCH) != '' }}
        run: |
          mkdir -p outputs
          kicad-cli sch erc --exit-code-violations -o outputs/erc.rpt "$SCH"

      - name: 接続テスト（テスト緑 相当）
        if: ${{ hashFiles(env.SCH) != '' && hashFiles('tests/**') != '' }}
        run: |
          mkdir -p outputs
          kicad-cli sch export netlist --format kicadxml -o outputs/netlist.xml "$SCH"
          python3 -m pytest tests/ -v

      - name: DRC（基板がある場合）
        if: ${{ hashFiles(env.PCB) != '' }}
        run: |
          mkdir -p outputs
          kicad-cli pcb drc --exit-code-violations -o outputs/drc.rpt "$PCB"

      - name: 出図（レビュー用）
        if: ${{ always() && hashFiles(env.SCH) != '' }}
        run: |
          mkdir -p outputs
          kicad-cli sch export pdf -o outputs/sch.pdf "$SCH"
          if [ -f "$PCB" ]; then
            kicad-cli pcb export pdf -o outputs/pcb.pdf \
              --layers "F.Cu,B.Cu,Edge.Cuts,F.Silkscreen,B.Silkscreen" "$PCB"
          fi

      - name: レビュー用 artifact
        if: ${{ always() && hashFiles(env.SCH) != '' }}
        uses: actions/upload-artifact@v4
        with:
          name: kicad-outputs
          path: outputs/
```

ポイント:

- **ERC / DRC は `--exit-code-violations` を付ける**（違反で非ゼロ終了 → 赤チェック）。警告を抑制する場合は理由を ADR に記録し、抑制設定はプロジェクトファイル側に持たせる。
- 出図と artifact は `always()` を併用して、**チェックが赤でも図は見られる**ようにする（レビュー・修正指示が速くなる）。
- **各ステップは対象ファイルの有無で分岐する。** フェーズ0（ドキュメントのみの PR）や骨格作成時には `.kicad_sch` も `tests/` もまだ存在しないため、ガードが無いと CI が赤くなり「PR ごとに必ず実行・必ず緑」が最初の PR から破綻する。**衛生チェックだけは常時実行**する（KiCad ファイルの有無に関係なく効く検査のため）。
- **`--expect-version` は段階導入する。** フォーマットバージョンの実値は KiCad プロジェクトを一度生成するまで分からない。仮の値を置くと KiCad ファイル追加と同時に CI が赤くなるため、**生成後に設定する**（`check_repo_hygiene.py` は `--expect-version` 省略時「検出値の報告のみ」となり、残り3検査は機能する）。

## リリース（発注用製造データ）

タグを打ったときだけ製造データ一式を生成し、Release に添付する。**発注前チェックリスト（review_checklist.md）を人間と通すまで発注はしない。**

> ⚠ **このジョブは未検証**（上の `check` ジョブと違い、実プロジェクトでの実行実績がまだ無い）。初回のタグ打ち前に一度動かして確認すること。なお Python を使わないため `python3-pip` の導入は不要だが、`zip` がイメージに無い場合は `apt-get install -y -qq zip` を足す。

```yaml
  fabrication:
    if: startsWith(github.ref, 'refs/tags/')
    runs-on: ubuntu-latest
    container:
      image: kicad/kicad:10.0
      options: --user root
    steps:
      - uses: actions/checkout@v4
      - name: 製造データ生成
        run: |
          mkdir -p outputs/gerbers
          kicad-cli pcb export gerbers -o outputs/gerbers/ "$PCB"
          kicad-cli pcb export drill   -o outputs/gerbers/ "$PCB"
          kicad-cli pcb export pos     -o outputs/pos.csv --format csv "$PCB"
          kicad-cli sch export bom     -o outputs/bom.csv \
            --fields "Reference,Value,Footprint,MPN,Datasheet" "$SCH"
          cd outputs && zip -r "fab-${GITHUB_REF_NAME}.zip" gerbers pos.csv bom.csv
      - uses: softprops/action-gh-release@v2
        with:
          files: outputs/fab-*.zip
```

## トラブルシュート

- **`pip: not found`（exit 127）/ `No module named pip` / `No module named ensurepip`** → `kicad/kicad` イメージには pip が同梱されておらず、Debian は `ensurepip` を無効化しているため自力導入もできない。**apt で `python3-pip` を入れる**（上記ワークフロー例）。
- **イメージ内で pip が拒否される（externally-managed-environment）** → `--break-system-packages` を付ける（上記）か、venv を作る。
- **`fatal: detected dubious ownership in repository`** → コンテナが root で動く一方、checkout したワークスペースの所有者が異なるため。git を呼ぶステップの前に `git config --global --add safe.directory "$GITHUB_WORKSPACE"` を実行する。
- **KiCad ファイルがまだ無いフェーズで CI が赤くなる** → 各ステップに `hashFiles(...)` のガードが付いているか確認する（上記ワークフロー例）。
- **KiCad ファイル追加と同時に衛生チェックが赤くなる** → `--expect-version` に仮の値が入っている。プロジェクト生成後の実値に更新する（段階導入）。
- **フォント・ロケール起因で出図が崩れる** → 回路図はフィールドに標準フォントのみ使う。プロジェクト固有フォントは使わない。
- **ERC がローカルと CI で食い違う** → KiCad のバージョン不一致が典型。ローカルもイメージと同じメジャー・マイナーに固定する。
- **`actions/checkout@v4` に Node.js 20 非推奨の警告が出る**（2026-08 時点）→ 動作には影響しない。解消するなら `@v5` に上げる（コンテナジョブでは Node 24 が動く必要があるため、上げたら1回 CI を通して確認すること）。`upload-artifact` も同様に追従を確認する。
