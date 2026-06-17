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

## 3. ブランチ保護（main への直接変更を禁止＝フローの要）

GitHub の **Repository Ruleset** を使う（private リポジトリでも無料で利用可）。
`main` に対し「PR 経由必須・force push 禁止・削除禁止」を全員に強制する。

```bash
gh api -X POST /repos/OWNER/REPO/rulesets --input ruleset-main.json
```

`ruleset-main.json`（雛形）:

```json
{
  "name": "protect-main",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["refs/heads/main"], "exclude": [] } },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false,
        "allowed_merge_methods": ["merge", "squash", "rebase"]
      }
    }
  ],
  "bypass_actors": []
}
```

要点:
- `pull_request` … `main` への変更は必ず PR 経由（直接 push をブロック）
- `non_fast_forward` … force push をブロック
- `deletion` … ブランチ削除をブロック
- `bypass_actors: []` … 管理者も含め例外なし（エージェントの直接変更を確実に防ぐ）

### 承認数についての注意（重要）

雛形では `required_approving_review_count: 0` にしている。理由:

- **エージェントとユーザーが同一 GitHub アカウントを共有している場合、自分の PR を自分で承認できず、必須承認数を 1 以上にするとマージできなくなる**（デッドロック）。
- そのため承認は「必須レビュー数」ではなく**プロセス上のルール**（CLAUDE.md のフロー）で担保し、保護ルールは「PR 経由の強制」のみ行う。
- レビュー専用の別アカウント／チームが用意できる場合は `required_approving_review_count` を 1 に上げ、`bypass_actors` でレビュアーのみ例外設定するとより厳格にできる。

### CI 必須化（GitHub Actions 導入後に追加）

CI ワークフローを追加したら、ruleset に `required_status_checks` ルールを足し、
build/test/lint のチェックが緑でない PR をマージ不可にする（CLAUDE.md「CI」参照）。

## 4. 確認

```bash
gh api /repos/OWNER/REPO/rulesets                 # ruleset 一覧
git push origin main 2>&1 | head                  # 保護後は直接 push が拒否されることを確認
```

## 日常の作業フロー（保護後）

```bash
git switch -c feature/xxx          # 作業ブランチを切る（main では作業しない）
# ... 実装・コミット ...
git push -u origin feature/xxx
gh pr create --fill                # PR を作成 → レビュー → マージ
```
