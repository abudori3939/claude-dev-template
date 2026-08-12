# リモート準備手順書（再利用可能ランブック）

PR ベースの開発フロー（CLAUDE.md「開発フロー」参照）を成立させるための GitHub リモート準備手順。
`OWNER` / `REPO` を置き換えて使う。

前提ツール: `git`, `gh`（GitHub CLI, 認証済み: `gh auth status` で確認）。

## 1. リポジトリ作成（未作成の場合のみ）

```bash
# 既存ローカルリポジトリを GitHub に新規作成＋push まで一括
gh repo create OWNER/REPO --private --source=. --remote=origin --push

# あるいはリモートだけ手動で紐付け
git remote add origin git@github.com:OWNER/REPO.git
git push -u origin main
```

## 2. デフォルトブランチを main に

```bash
gh repo edit OWNER/REPO --default-branch main
```

## 3. main への直接変更をどう防ぐか（ブランチ保護は前提としない）

**このテンプレートは GitHub のブランチ保護（Repository Ruleset / Branch protection）を前提としない。**
無料プランでは利用できない場合があるため、`main` 直編集の禁止は**運用ルールで担保する**。

担保のしかた:
- **CLAUDE.md「セッション開始時の判定 / 手順0」** … 何かを書き込む前に必ず作業ブランチを切る（ドキュメントだけの変更も例外なし）。
- **CLAUDE.md「ブランチ・PR・レビュー」** … 変更は作業ブランチ → PR → レビュー → マージ経由でのみ反映する。
- **CI（GitHub Actions）** … PR ごとに build + test + lint を実行し、緑でない PR はマージしない（人手の確認ではなく緑チェックで判断する）。

> 仕組みで強制していない以上、**エージェントもユーザーも「まずブランチを切る」を毎回守ることが唯一の防波堤**になる。
> 迷ったらブランチを切る。うっかり `main` で編集を始めたら、その時点でコミット前に作業ブランチへ退避する（`git switch -c <branch>`）。

（有料プラン等でブランチ保護を使える環境なら設定してもよいが、本テンプレートの必須手順ではない。）

## 4. 確認

```bash
git rev-parse --abbrev-ref HEAD    # 作業前: main でないことを確認
gh pr list                         # PR 経由で変更が流れているかを確認
```

## 日常の作業フロー

```bash
git switch -c feature/xxx          # 作業ブランチを切る（main では作業しない）
# ... 実装・コミット ...
git push -u origin feature/xxx
gh pr create --fill                # PR を作成 → レビュー → マージ
```
