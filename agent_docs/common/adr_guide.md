# 設計判断記録（ADR: Architecture Decision Records）

計画ドキュメント（`agent_docs/project/plan.md`）から逸脱する設計判断、または計画に書かれていない重要な技術選択を、**`agent_docs/project/adr/` に** 1 件 1 ファイルで残す。計画ドキュメントを真実の源（source of truth）に保ち、後から参加するエージェントが「なぜこうなっているか」を追えるようにするのが目的。

## 使い方

- ファイル名: `NNNN-short-title.md`（例: `0001-imu-orientation-fallback.md`）。連番は 0001 から。
- 計画と矛盾する判断をしたら、計画ドキュメント側にも「ADR-NNNN 参照」と一言残す。
- 一度 Accepted にした ADR は書き換えず、覆す場合は新しい ADR を起こして旧 ADR を `Superseded by ADR-NNNN` にする。

## テンプレート

```markdown
# ADR-NNNN: タイトル

- ステータス: Proposed | Accepted | Superseded by ADR-XXXX
- 日付: YYYY-MM-DD
- 関連: 計画ドキュメントの該当節 / PR 番号

## 背景
何を決める必要があったか。計画ドキュメントの前提と、それが成り立たなかった点。

## 決定
採用した方針。

## 理由・トレードオフ
なぜこれを選んだか。検討した代替案と却下理由。

## 影響
パラメータ・トピック・テストへの影響。計画ドキュメントの更新有無。
```
