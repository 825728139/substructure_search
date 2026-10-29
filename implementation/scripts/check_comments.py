"""检查项目 Python 中文说明覆盖，并可重建交接用函数索引；不评价注释的化学正确性。"""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def python_files():
    """按稳定路径顺序返回源码、测试和维护脚本，不扫描虚拟环境或构建产物。"""
    return sorted(
        path
        for directory in (ROOT / "src", ROOT / "tests", ROOT / "scripts")
        for path in directory.rglob("*.py")
    )


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
    """检查每个模块、类和具名函数的 docstring 含中文，返回统计及逐文件函数索引。

    缺少说明时以非零退出码阻止交付。该检查只防止说明遗漏；说明是否准确、是否覆盖
    输入输出和关键限制，仍需在代码审查时结合实现判断。匿名回调在使用位置人工注释。
    """
    failures, entries = [], []
    counts = {"modules": 0, "classes": 0, "functions": 0}
    for path in python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(ROOT).as_posix()
        nodes = [("模块", tree), *definitions(tree)]
        for name, node in nodes:
            description = ast.get_docstring(node) or ""
            if not re.search(r"[\u3400-\u9fff]", description):
                failures.append(f"{relative}:{getattr(node, 'lineno', 1)} {name} 缺少中文说明")
            if isinstance(node, ast.Module):
                counts["modules"] += 1
            elif isinstance(node, ast.ClassDef):
                counts["classes"] += 1
            else:
                counts["functions"] += 1
                entries.append((relative, name, node.lineno, description.split("\n")[0]))
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
