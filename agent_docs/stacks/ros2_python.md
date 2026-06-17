# スタックガイド: ROS 2 / Python

プロジェクトを **ROS 2 / Python（rclpy）** で実装する場合の具体的な作法。
CLAUDE.md と `agent_docs/common/coding_standards.md`（スタック非依存の原則）を、ここで ROS 2 / Python 向けに具体化する。

## ビルド・実行（colcon ワークスペース / ament_python）

全コマンドはワークスペースのルートから実行する（`<package>` を置換）:

```bash
cd <colcon_ws のルート>
colcon build --packages-select <package> --symlink-install   # symlink で再ビルド不要に
source install/setup.bash            # ビルド後に毎回（新しいシェル）
ros2 run <package> <entry_point>     # または ros2 launch <package> <launch_file>
colcon test --packages-select <package>
colcon test-result --verbose
```

> `--symlink-install` により Python ソースの編集はビルドし直さず反映される（テスト/lint は `colcon test`）。

## テスト（TDD）

- フレームワークは **pytest**（`ament_python` パッケージの `test/` 配下）。`colcon test` から実行される。
- **レッドはアサーション失敗で示す。import / 構文エラーはレッドと認めない**（CLAUDE.md のフロー参照）。テストが収集・実行されたうえで `assert` が失敗していること。
- **各処理段は ROS から独立してテスト可能にする。** ロジックは入出力が明確な純粋関数／クラスとして実装し、`rclpy.node.Node` への依存を持たせない。ノードが購読・パラメータ取得・段の呼び出しを担う。
- 数値比較は `pytest.approx` / `math.isclose` / `numpy.testing.assert_allclose` を使う。実時間・乱数・実機トピックに依存しない固定フィクスチャを使う。

## 自動品質ゲート（lint / format / 型）

- ROS 2 標準の lint を `colcon test` で実行する: **`ament_flake8` / `ament_pep257` / `ament_copyright` / `ament_xmllint`**（`test/` にテストを置き、`package.xml` の `<test_depend>` に追加）。
- 加えて **ruff（lint+format）/ black / mypy** を導入すると効果が高い。`pyproject.toml` に設定を集約。
- 警告ゼロを維持。抑制する場合は理由をコメント（`# noqa: <code> 理由`）で明記。

## コーディング規約（Python / ROS 2）

- Python 3（対象 ROS 2 ディストリビューションに準拠）、`rclpy`。
- スタイルは **PEP 8**（フォーマットは black / ruff format に従い、手動整形より自動整形を優先）。型ヒントを付け、`mypy` を通す。
- 命名: 関数・変数・モジュールは `snake_case`、クラスは `CapWords`、定数は `UPPER_SNAKE`。**ROS パラメータ名は仕様書・計画ドキュメントと完全一致**させる。
- public API（公開関数・クラス、ノードの入出力）に docstring を付ける。
- マジックナンバー禁止。閾値などは ROS パラメータか名前付き定数に。

## 依存（package.xml / setup.py 例）

- ビルドタイプ: `ament_python`。実行: `rclpy`、使用するメッセージ型（`sensor_msgs` など）。
- テスト: `python3-pytest` / lint: `ament_flake8`・`ament_pep257`・`ament_copyright`・`ament_xmllint`
- エントリポイントは `setup.py` の `console_scripts` に定義する。
