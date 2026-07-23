# workflow_pptx.md — python-pptx の作業手順とコード雛形

> 前提: [`../pptx_deliverable.md`](../pptx_deliverable.md) と `agent_docs/project/format_rules.md` を読了済みであること。
> Python はプロジェクトの CLAUDE.md に記録した実行パスで呼ぶ（Windows はフルパス推奨）。

> ⛔ **汎用の pptx 生成ツール／スキルで作り直さない。**
> `.pptx` を扱うと汎用の pptx スキルが立ち上がることがあるが、本スタックでは使わない。
> それらは新規スライドをゼロから組み立てるため、**テンプレート由来の体裁（フォント・配色・
> 固有要素・配置）が失われる**。必ず本書のヘルパー（`duplicate_slide` / `set_text_keep_format` /
> `set_multiline_keep_format`）で**テンプレ由来の既存 run の書式を保ったまま**テキストだけを差し替えること。

## 全体フロー

```
1. spec.md（骨子）でスライド一覧と各スライドの本文・出典を確認
2. templates/フォーマット.pptx を outputs/ にコピー（ファイル名を決める）
3. 必要枚数ぶん本文スライドを複製し、骨子の順に並べる
4. 各スライドのタイトル・本文・固有要素のテキストを差し替え（書式維持）
5. 図・グラフは assets/ に用意し、スライドに貼付
6. review_checklist.md でセルフチェック → 修正
7. outputs/ に保存し、画像化して目視確認 → 報告
```

## STEP 1: コピー元を複製

> ⚠️ パスは**このリポジトリのルートからの相対**で扱う。過去案件の絶対パスをコピペしない。

```powershell
$root = (Get-Location).Path                                  # = このプロジェクトのルート
$src  = Join-Path $root "templates\フォーマット.pptx"
$dst  = Join-Path $root "outputs\資料名_YYYYMMDD.pptx"
Copy-Item $src $dst
```

> `templates/フォーマット.pptx` は**絶対に直接編集しない**。

## STEP 2: スライドの複製と並べ替え

`フォーマット.pptx` の想定構成: **スライド1＝タイトルスライド（空）／スライド2＝空の本文スライド**。
本文スライドが複数必要なときは、スライド2を必要枚数ぶん複製する。

python-pptx には公式の「スライド複製」API が無いため、XML コピーで行う。

```python
import copy
from pptx import Presentation

def duplicate_slide(prs, index):
    """index番目(0始まり)のスライドを複製して末尾に追加する。"""
    source = prs.slides[index]
    blank = source.slide_layout
    new_slide = prs.slides.add_slide(blank)
    # 既定で入るプレースホルダを一旦除去
    for shp in list(new_slide.shapes):
        shp._element.getparent().remove(shp._element)
    # ソースの全shapeをコピー
    for shp in source.shapes:
        new_slide.shapes._spTree.append(copy.deepcopy(shp._element))
    return new_slide
```

> 注: レイアウト由来の要素（ロゴ・ページ番号）がマスターにある場合は二重になることがある。
> 生成後に必ず目視確認（画像化）すること。

### スライドの並べ替え（重要）

`duplicate_slide` は**末尾に追加**するだけ。骨子の順序どおりに並べたいとき、
修正で本文の途中にページを挿入したいときは、`sldIdLst` 上で順序を入れ替える。

```python
def move_slide(prs, old_index, new_index):
    """old_index(0始まり)のスライドを new_index の位置へ移動する。"""
    sldIdLst = prs.slides._sldIdLst
    ids = list(sldIdLst)
    sld = ids[old_index]
    sldIdLst.remove(sld)
    sldIdLst.insert(new_index, sld)
```

> 末尾に複製 → `move_slide` で目的の位置へ、の2手で挿入する。並べ替え後はページ番号・通し順を目視確認。

## STEP 3: テキストの差し替え（書式維持が最重要）

書式（フォント・サイズ・色・太字）を壊さないよう、**既存 run のテキストだけ**を入れ替える。
`text_frame.text = "..."` への代入は run の書式をリセットするため**使わない**。
新規に run/段落を作る場合は、`format_rules.md` の書式（フォント・太字方針）を明示的に設定する。

```python
def set_text_keep_format(shape, text):
    """最初の段落・最初のrunに書式を残したままテキストを設定する。"""
    tf = shape.text_frame
    p = tf.paragraphs[0]
    if p.runs:
        p.runs[0].text = text
        for r in p.runs[1:]:
            r.text = ""
    else:
        r = p.add_run(); r.text = text
        # 新規runは書式を持たない。format_rules.md の既定書式をここで明示する
        # 例: r.font.bold = True; r.font.name = "<標準フォント>"

def set_multiline_keep_format(shape, lines):
    """複数行を、既存runの書式（フォント・サイズ等）を引き継いで設定する。"""
    tf = shape.text_frame
    base = tf.paragraphs[0].runs[0] if tf.paragraphs[0].runs else None
    name = base.font.name if base else None
    size = base.font.size if base else None
    bold = base.font.bold if base else None
    for p in tf.paragraphs[1:]:
        p._p.getparent().remove(p._p)
    for r in tf.paragraphs[0].runs:
        r.text = ""
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        r = p.add_run(); r.text = line
        if bold is not None: r.font.bold = bold
        if name: r.font.name = name
        if size: r.font.size = size
```

### スライド内の要素の見分け方

テンプレのどのテキストボックスが「タイトル」「本文」「固有要素（まとめ帯など）」かは、
**`format_rules.md` に判別条件（位置・サイズ・塗り色・フォントサイズ）を記録**し、それに従って判別する。

```python
def fill_hex(s):
    try:
        if s.fill.type == 1:
            return str(s.fill.fore_color.rgb)
    except Exception:
        pass
    return None

# 例: format_rules.md の判別条件（タイトル=28pt / 本文=24pt・幅広 / まとめ帯=特定塗り色・全幅）
# に従って1スライドを埋める。条件は必ず自プロジェクトの format_rules.md に合わせて書き換える。
def fill_content_slide(slide, title, body_lines, summary):
    for sh in slide.shapes:
        if fill_hex(sh) == "FFFF00" and sh.width and sh.width/914400 > 10:
            set_text_keep_format(sh, summary)               # 固有要素（例: まとめ帯）
        elif sh.has_text_frame:
            sz = None
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    if r.font.size: sz = r.font.size.pt
                    break
                if sz: break
            w = sh.width/914400 if sh.width else 0
            if sz == 28.0:
                set_text_keep_format(sh, title)             # タイトル
            elif sz == 24.0 and w > 10:
                set_multiline_keep_format(sh, body_lines)   # 本文（複数行）
```

## STEP 4: 図・グラフの貼付

- 図・グラフは `assets/` に画像（PNG等）で用意してから貼る。グラフはスクリプトで生成して `assets/` へ。
- 元データの図は `data_sources.md` に記録した元ファイルから取得する（推測で描かない）。

```python
from pptx.util import Inches
slide.shapes.add_picture(r"<root>\assets\graph01.png", Inches(7.0), Inches(1.2),
                         width=Inches(5.5))
```

## STEP 5: 保存と目視確認

```python
prs.save(r"<root>\outputs\資料名_YYYYMMDD.pptx")
```

- PowerPoint があれば PDF 化→画像化して全スライドを通し見する。最低限:
  - テキストのはみ出し・重なりが無いか
  - 固有要素（まとめ帯等）が `format_rules.md` どおりか
  - 数値・型番・日付が正しいか
- 詳細チェックは [review_checklist.md](review_checklist.md) を使う。

## 機械生成パート（結果集など大量ページ）がある場合

- 骨子（spec.md）の「機械生成仕様」（元データ→ページの対応規則・命名→タイトルのマッピング・除外・欠落の扱い）に従い、スクリプトで生成する。
- **まず数ページを試作 → 目視 OK → 全量生成**の順で進める（全量生成してから崩れに気づくと手戻りが大きい）。
- 生成スクリプトは `agent_docs/project/scripts/` に置き、再実行可能に保つ。

## よくある落とし穴

- Windows で `python` 単体で実行 → ストアシムで失敗。**CLAUDE.md に記録した実行パス**で呼ぶ。
- `text_frame.text = "..."` は run の書式をリセットする。書式維持が必要な箇所は `set_text_keep_format` を使う。
- スライド複製でマスター由来要素が二重化することがある → 生成後に目視確認。
- 日本語パス・ファイル名は文字コード（UTF-8）に注意。
