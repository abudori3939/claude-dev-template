# ci_kicad.md — GitHub Actions（ERC / DRC / 接続テスト / 出図）

「PR で合格したコードのみマージ」を KiCad でも**緑チェックで保証**するための CI 設定手順。
ローカル（workflow_sch.md §2）と**同一コマンド**を PR ごとに実行し、出図物を artifact に添付してレビュアーが図を見られるようにする。

## 前提

- 公式 Docker イメージ `kicad/kicad:<version>` を使う（プロジェクトで固定したバージョンと一致させること。例: `kicad/kicad:9.0`）。
- イメージは非 root ユーザーで動くため、checkout や pip の権限問題が出る場合は `options: --user root` を付ける。
- `<board>` はプロジェクトの基板名に置換する。

## ワークフロー例（`.github/workflows/kicad.yml`）

```yaml
name: kicad
on: [pull_request]

env:
  SCH: hardware/<board>/<board>.kicad_sch
  PCB: hardware/<board>/<board>.kicad_pcb

jobs:
  check:
    runs-on: ubuntu-latest
    container:
      image: kicad/kicad:9.0
      options: --user root
    steps:
      - uses: actions/checkout@v4

      - name: Python 依存
        run: pip install --break-system-packages kiutils pytest

      - name: ERC（lint 相当）
        run: |
          mkdir -p outputs
          kicad-cli sch erc --exit-code-violations -o outputs/erc.rpt "$SCH"

      - name: 接続テスト（テスト緑 相当）
        run: |
          kicad-cli sch export netlist --format kicadxml -o outputs/netlist.xml "$SCH"
          python3 -m pytest tests/ -v

      - name: DRC（基板がある場合）
        if: ${{ hashFiles(env.PCB) != '' }}
        run: kicad-cli pcb drc --exit-code-violations -o outputs/drc.rpt "$PCB"

      - name: 出図（レビュー用）
        if: always()
        run: |
          kicad-cli sch export pdf -o outputs/sch.pdf "$SCH"
          if [ -f "$PCB" ]; then
            kicad-cli pcb export pdf -o outputs/pcb.pdf \
              --layers "F.Cu,B.Cu,Edge.Cuts,F.Silkscreen,B.Silkscreen" "$PCB"
          fi

      - name: レビュー用 artifact
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: kicad-outputs
          path: outputs/
```

ポイント:

- **ERC / DRC は `--exit-code-violations` を付ける**（違反で非ゼロ終了 → 赤チェック）。警告を抑制する場合は理由を ADR に記録し、抑制設定はプロジェクトファイル側に持たせる。
- 出図と artifact は `if: always()` にして、**チェックが赤でも図は見られる**ようにする（レビュー・修正指示が速くなる）。
- 回路図しか無いフェーズでも動くよう、DRC は `.kicad_pcb` の有無で分岐している。

## リリース（発注用製造データ）

タグを打ったときだけ製造データ一式を生成し、Release に添付する。**発注前チェックリスト（review_checklist.md）を人間と通すまで発注はしない。**

```yaml
  fabrication:
    if: startsWith(github.ref, 'refs/tags/')
    runs-on: ubuntu-latest
    container:
      image: kicad/kicad:9.0
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

- **イメージ内で pip が拒否される** → `--break-system-packages` を付ける（上記）か、venv を作る。
- **フォント・ロケール起因で出図が崩れる** → 回路図はフィールドに標準フォントのみ使う。プロジェクト固有フォントは使わない。
- **ERC がローカルと CI で食い違う** → KiCad のバージョン不一致が典型。ローカルもイメージと同じメジャー・マイナーに固定する。
