# claude-dev-template

Claude Code で **ドキュメント駆動 × TDD × PR レビュー**の小さなフローを安定して回すための、ROS 2 / C++ プロジェクト用テンプレート。エージェントが入れ替わっても品質が揃い、人間の監視コストが低く保たれることを狙う。

## ディレクトリ構成

- `CLAUDE.md` — ルール本体（セッション開始時の判定・開発フロー・品質ルール）。エージェントが最初に読む。
- `agent_docs/` — **開発エージェント向け**の文書。
  - `common/` — ROS 2 実装に共通の作法（再利用・基本いじらない）: `coding_standards.md` / `remote_setup.md` / `spec_format.md` / `adr_guide.md`
  - `project/` — **このプロジェクト固有**のドメイン設計（クローン後に育てる）: `plan.md` / `spec.md` / `progress.md` / `adr/`
  - `getting_started.md` — クローン後にまず読む手順書（フェーズ0）
- `docs/` — （任意）**エンドユーザー向け**のプロジェクト説明。配布時に作成する。agent_docs とは別物。

## 使い方

1. このテンプレートから新規リポジトリを作成
   （GitHub の「Use this template」または `gh repo create <name> --template <owner>/claude-dev-template --private`）。
2. `agent_docs/getting_started.md` を開き、**フェーズ0（ドメイン設計）**から始める。
   エージェントはセッション開始時にフェーズ0を検知し、要件定義を主導する。
3. `plan.md` / `spec.md` が固まったら、`agent_docs/common/remote_setup.md` で `main` のブランチ保護を設定。
4. 以後は `CLAUDE.md` の**着手ゲート**から TDD サイクルを回す。

## 設計思想（最小・シンプル）

- 仕様書は「入力・出力が明確であれば十分」。制約や確認項目を増やしすぎず、**人間の監視コストを最優先で下げる**。
- フォーマットを固定して品質を安定させつつ、量は最小に保つ。厳密化（EARS・ID 体系など）は必要な機能にだけ段階導入する。
