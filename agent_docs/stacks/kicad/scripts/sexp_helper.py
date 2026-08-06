#!/usr/bin/env python3
"""フォーマット保持型 S式編集ヘルパ（KiCad ファイルの読み書き）.

`.kicad_sch` / `.kicad_sym` / `.kicad_pcb` 等をスクリプトから編集するための最小ヘルパ。
**kiutils は使わない**: 1.4.8 時点で KiCad 10 フォーマットに追随しておらず、パースは
通るが再出力で `generator_version` / `embedded_fonts` 等が脱落して旧書式に再整形される
（「GUI で無変更保存 → git diff ゼロ」を満たせない）。詳細は workflow_sch.md を参照。

設計方針:
  - **トークナイザが全バイトを消費する**: 空白・改行もトークンとして保持し、
    ``serialize()`` はトークン列の連結で原文を厳密に復元する（無編集なら
    ラウンドトリップはバイト一致）。この性質自体をテストで固定しておくとよい。
  - **編集は局所置換**: 編集した箇所以外のバイト列には一切触れない。
  - 編集 API は汎用の局所操作 4 つのみ（replace / insert_after / insert_into / delete）。
    「シンボルとは何か」等の回路図の意味論は持ち込まない（呼び出し側の責務）。

使い方:
    doc = SexpDoc.from_file(path)
    assert doc.serialize() == doc.text          # ラウンドトリップ
    for node in doc.root.children:              # 構造の探索
        if node.head == "symbol":
            ...
    doc.replace(node, new_text)                 # 局所編集（原文の他部分は不変）
    doc.to_file(path)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Token:
    """原文の連続した1区間。kind: 'lparen' | 'rparen' | 'atom' | 'string' | 'space'."""

    kind: str
    text: str
    start: int  # 原文でのバイト（文字）位置


@dataclass
class Node:
    """S式のリストノード。leaf（atom/string）は Token のまま children に入る。"""

    tokens_start: int  # このノードの '(' のトークン索引
    tokens_end: int  # 対応する ')' のトークン索引（含む）
    children: list["Node | Token"] = field(default_factory=list)
    generation: int = 0  # 取得元 SexpDoc の世代（編集で失効。SexpDoc._check 参照）

    @property
    def head(self) -> str | None:
        """リスト先頭のアトム名（例: 'symbol'）。無ければ None。"""
        for child in self.children:
            if isinstance(child, Token):
                if child.kind == "space":
                    continue
                return child.text
            return None
        return None

    def strings(self) -> list[str]:
        """直下の文字列リテラル（クォート除去済み）を順に返す。"""
        result = []
        for child in self.children:
            if isinstance(child, Token) and child.kind == "string":
                result.append(unquote(child.text))
        return result

    def lists(self, head: str | None = None) -> list["Node"]:
        """直下のリストノード（head 指定で絞り込み）."""
        return [
            c for c in self.children if isinstance(c, Node) and (head is None or c.head == head)
        ]


def unquote(text: str) -> str:
    """S式の文字列リテラルをデコードする.

    注意: 復号するのは \\" と \\\\ のみ（KiCad の識別子・パス比較用途には十分）。
    \\n 等の制御文字エスケープは復号しない。原文の保持はトークンが担うため、
    このデコード結果を書き戻しに使ってはならない。
    """
    assert text.startswith('"') and text.endswith('"')
    return text[1:-1].replace('\\"', '"').replace("\\\\", "\\")


def quote(value: str) -> str:
    """文字列を S式リテラルにエンコードする."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


ATOM_END = set(' \t\r\n()"')


def tokenize(text: str) -> list[Token]:
    """全バイトをトークン化する（どの文字も必ずいずれかのトークンに属する）."""
    tokens: list[Token] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            j = i
            while j < n and text[j] in " \t\r\n":
                j += 1
            tokens.append(Token("space", text[i:j], i))
            i = j
        elif ch == "(":
            tokens.append(Token("lparen", "(", i))
            i += 1
        elif ch == ")":
            tokens.append(Token("rparen", ")", i))
            i += 1
        elif ch == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    break
                j += 1
            if j >= n:
                raise ValueError(f"閉じていない文字列リテラル (位置 {i})")
            tokens.append(Token("string", text[i : j + 1], i))
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in ATOM_END:
                j += 1
            tokens.append(Token("atom", text[i:j], i))
            i = j
    return tokens


def parse(tokens: list[Token]) -> list["Node | Token"]:
    """トークン列から S式ツリー（トップレベル要素のリスト）を組む."""
    top: list[Node | Token] = []
    stack: list[Node] = []
    for idx, token in enumerate(tokens):
        if token.kind == "lparen":
            node = Node(tokens_start=idx, tokens_end=-1)
            (stack[-1].children if stack else top).append(node)
            stack.append(node)
        elif token.kind == "rparen":
            if not stack:
                raise ValueError(f"対応しない ')' (位置 {token.start})")
            stack.pop().tokens_end = idx
        else:
            (stack[-1].children if stack else top).append(token)
    if stack:
        raise ValueError("閉じていない '(' があります")
    return top


class SexpDoc:
    """1ファイル分の S式ドキュメント。原文＋トークン列＋ツリーを保持する."""

    def __init__(self, text: str):
        # 編集のたびに世代を進め、編集前に取得した Node の使い回し（古いトークン索引で
        # 別の場所を壊す事故）を検出する
        self._generation = getattr(self, "_generation", 0) + 1
        self.text = text
        self.tokens = tokenize(text)
        top = parse(self.tokens)
        roots = [n for n in top if isinstance(n, Node)]
        if len(roots) != 1:
            raise ValueError(f"トップレベルのリストが {len(roots)} 個あります（KiCad ファイルは 1 個）")
        self.root = roots[0]
        stack = [self.root]
        while stack:
            node = stack.pop()
            node.generation = self._generation
            stack.extend(c for c in node.children if isinstance(c, Node))

    def _check(self, node: Node) -> None:
        if node.generation != self._generation:
            raise ValueError(
                "編集前に取得した古い Node が渡されました。編集後は root からノードを取得し直すこと"
            )

    @classmethod
    def from_file(cls, path: str | Path) -> "SexpDoc":
        # newline="" で改行変換を止める（open() 経由。Path.read_text の newline 引数は 3.13+）
        with open(path, encoding="utf-8", newline="") as f:
            return cls(f.read())

    def serialize(self) -> str:
        """トークン列の連結で原文を復元する（全バイト消費の証明を兼ねる）."""
        return "".join(t.text for t in self.tokens)

    def node_text(self, node: Node) -> str:
        """ノードの原文スライスを返す."""
        self._check(node)
        start = self.tokens[node.tokens_start].start
        last = self.tokens[node.tokens_end]
        return self.text[start : last.start + len(last.text)]

    def replace(self, node: Node, new_text: str) -> None:
        """ノードの区間だけを new_text に置換する（他のバイトは不変）."""
        self._check(node)
        start = self.tokens[node.tokens_start].start
        last = self.tokens[node.tokens_end]
        end = last.start + len(last.text)
        self.__init__(self.text[:start] + new_text + self.text[end:])

    def insert_after(self, node: Node, new_text: str) -> None:
        """ノードの直後に new_text を挿入する（改行・インデントは呼び出し側が含める）."""
        self._check(node)
        last = self.tokens[node.tokens_end]
        end = last.start + len(last.text)
        self.__init__(self.text[:end] + new_text + self.text[end:])

    def insert_into(self, node: Node, new_text: str) -> None:
        """ノードの閉じ括弧の直前に new_text を挿入する.

        空リスト（例: ``(lib_symbols)``）への子要素追記に使う。改行・インデントは
        呼び出し側が new_text に含める。
        """
        self._check(node)
        close = self.tokens[node.tokens_end]
        self.__init__(self.text[: close.start] + new_text + self.text[close.start :])

    def delete(self, node: Node) -> None:
        """ノードと直前の空白トークンを削除する.

        雛形や再生成対象の既存要素の掃除に使う。直前トークンが空白（改行＋インデント）
        であればまとめて消し、行ごと除去した見た目になるようにする。
        """
        self._check(node)
        start_tok = self.tokens[node.tokens_start]
        start = start_tok.start
        if node.tokens_start > 0 and self.tokens[node.tokens_start - 1].kind == "space":
            start = self.tokens[node.tokens_start - 1].start
        last = self.tokens[node.tokens_end]
        end = last.start + len(last.text)
        self.__init__(self.text[:start] + self.text[end:])

    def to_file(self, path: str | Path) -> None:
        """改行変換なしで書き出す（LF は LF のまま）."""
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(self.text)
