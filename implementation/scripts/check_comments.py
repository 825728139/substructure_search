"""检查整个仓库 Python 说明及注释的中文覆盖，可重建函数索引；不评价说明的化学正确性。"""

import ast
import io
import os
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def python_files():
    """返回业务项目及仓库辅助脚本，包含 reviews、绘图脚本与无扩展名启动器。

    显式限定源码目录，避免扫描虚拟环境、缓存或第三方构建产物。
    """
    paths = {
        path
        for directory in (ROOT / "src", ROOT / "tests", ROOT / "scripts")
        for path in directory.rglob("*.py")
    }
    for directory in ("scripts", "reviews", "diagrams"):
        paths.update((ROOT.parent / directory).rglob("*.py"))
    for name in ("plan-git", "project-uv"):
        launcher = ROOT.parent / "scripts" / name
        if launcher.is_file():
            paths.add(launcher)
    return sorted(paths)


def english_prose(text, *, comment=False):
    """判断一段说明是否仍为纯英文；中文中的函数名和化学缩写可以保留。

    对注释先剥离必须保持原样的 shebang、类型检查及格式检查指令。指令后若附有
    人工解释，仍需检查解释文字，避免英文说明藏在 type: ignore 后面被漏过。
    """
    text = text.strip()
    if comment:
        if text.startswith("#!"):
            return False
        text = text.removeprefix("#").strip()
        text = re.sub(
            r"^(?:type:\s*ignore(?:\[[\w, -]+\])?|noqa(?::\s*[A-Z]\d+(?:\s*,\s*[A-Z]\d+)*)?|"
            r"fmt:\s*(?:skip|off|on)|pragma:\s*no cover)(?=\s|$)",
            "",
            text,
        ).strip(" #")
    return bool(re.search(r"[A-Za-z]{2}", text) and not re.search(r"[\u3400-\u9fff]", text))


def definitions(tree, prefix=""):
    """递归列出具名类及同步/异步函数，保留类名和闭包名，便于定位同名定义。"""
    for child in ast.iter_child_nodes(tree):
        if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            name = f"{prefix}.{child.name}" if prefix else child.name
            yield name, child
            yield from definitions(child, name)
        else:
            yield from definitions(child, prefix)


def inspect_comments():
    """检查全仓库 Python 的说明和所有注释，返回统计及逐文件函数索引。

    同时检查 docstring 每一行和 tokenize 提取的独立/行尾注释，不能仅凭某处有中文
    就放过其他英文段落。缺少说明或残留英文时以非零退出码阻止交付；准确性仍需审查。
    """
    failures, entries = [], []
    counts = {"modules": 0, "classes": 0, "functions": 0}
    for path in python_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        relative = Path(os.path.relpath(path, ROOT)).as_posix()
        nodes = [("模块", tree), *definitions(tree)]
        for name, node in nodes:
            description = ast.get_docstring(node) or ""
            if not re.search(r"[\u3400-\u9fff]", description):
                failures.append(f"{relative}:{getattr(node, 'lineno', 1)} {name} 缺少中文说明")
            for offset, line in enumerate(description.splitlines()):
                if english_prose(line):
                    failures.append(
                        f"{relative}:{node.body[0].lineno + offset} {name} 残留英文说明：{line}"
                    )
            if isinstance(node, ast.Module):
                counts["modules"] += 1
            elif isinstance(node, ast.ClassDef):
                counts["classes"] += 1
            else:
                counts["functions"] += 1
                entries.append((relative, name, node.lineno, description.split("\n")[0]))
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT and english_prose(token.string, comment=True):
                failures.append(f"{relative}:{token.start[0]} 残留英文注释：{token.string}")
    if failures:
        raise SystemExit("\n".join(failures))
    return counts, entries


def write_index(entries):
    """把具名函数的中文摘要和源码行号写入索引；行号变化后可再次运行本脚本刷新。"""
    lines = [
        "# 函数阅读索引",
        "",
        "由 `python scripts/check_comments.py --write-index` 生成；说明取自函数 docstring 首段。",
        "先读 [交接指南](HANDOVER.md)，需要定位具体函数时再查本索引。源码行号会随修改变化，",
        "提交前重新生成即可；匿名前端回调的中文说明直接写在 [页面源码](../src/reaction_reference/interfaces/static/index.html) 中。",
    ]
    previous = None
    for relative, name, lineno, description in entries:
        if relative != previous:
            lines.extend(["", f"## {relative}", "", "| 函数 | 职责 |", "|---|---|"])
            previous = relative
        lines.append(f"| [{name}](../{relative}#L{lineno}) | {description.replace('|', '／')} |")
    (ROOT / "docs" / "FUNCTION_INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    """执行中文说明覆盖检查；带 --write-index 时额外刷新 Markdown 函数索引。"""
    counts, entries = inspect_comments()
    if "--write-index" in sys.argv[1:]:
        write_index(entries)
    print(
        f"中文说明检查通过：{counts['modules']} 个模块、"
        f"{counts['classes']} 个类、{counts['functions']} 个具名函数。"
    )


if __name__ == "__main__":
    main()
