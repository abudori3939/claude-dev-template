# スタックガイド: ROS 2 / C++

プロジェクトを **ROS 2 / C++** で実装する場合の具体的な作法。
CLAUDE.md と `agent_docs/common/coding_standards.md`（スタック非依存の原則）を、ここで ROS 2 / C++ 向けに具体化する。

## ビルド・実行（colcon ワークスペース）

全コマンドはワークスペースのルートから実行する（`<package>` を置換）:

```bash
cd <colcon_ws のルート>
colcon build --packages-select <package> --symlink-install
source install/setup.bash            # ビルド後に毎回（新しいシェル）
colcon test --packages-select <package>
colcon test-result --verbose
```

## テスト（TDD）

- フレームワークは **gtest**（`ament_cmake_gtest` / `ament_add_gtest`）。
- **レッドはアサーション失敗で示す。コンパイルエラーはレッドと認めない**（CLAUDE.md のフロー参照）。
- **各処理段は ROS から独立してテスト可能にする。** ロジックは入出力が明確な純粋関数／クラスとして実装し、`rclcpp::Node` への依存を持たせない。ノードが購読・パラメータ取得・段の呼び出しを担う。
- 浮動小数比較は許容誤差付き（`EXPECT_NEAR`）。実時間・乱数・実機トピックに依存しない固定フィクスチャを使う。

## 自動品質ゲート（lint / format / 静的解析）

- ROS 2 標準の `ament_lint_auto` に加え、C++ 向けに **clang-format / clang-tidy / cppcheck** を導入し、`colcon test` で実行する。
- `ament_clang_format` / `ament_clang_tidy` / `ament_cppcheck` を `package.xml` の `<test_depend>` と `CMakeLists.txt` に追加する。
- 警告ゼロを維持。抑制する場合は理由をコメントで明記。

## コーディング規約（C++ / ROS 2）

- C++17、`rclcpp`。対象ディストリビューションはプロジェクトで指定。
- フォーマットは **clang-format**（`.clang-format` をリポジトリ直下に置き、ament のデフォルトに準拠）。手動整形より自動整形を優先。
- 命名: 型は `CamelCase`、関数・変数は `snake_case`、メンバ変数は末尾 `_`、定数は `kCamelCase` または `UPPER_SNAKE`。**ROS パラメータ名は仕様書・計画ドキュメントと完全一致**させる。
- ヘッダにインクルードガード（`#pragma once` 可）。**1 つの責務＝1 ヘッダ/ソース対**にする。
- public API（公開メソッド、ノードの入出力）に Doxygen 風コメント。

## 依存（package.xml 例）

- `rclcpp`、使用するメッセージ型（`sensor_msgs` など）、`ament_cmake`
- テスト: `ament_cmake_gtest` / lint: `ament_lint_auto`・`ament_lint_common` ほか
