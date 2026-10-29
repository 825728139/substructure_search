"""python -m reaction_reference 的进程入口；调用 CLI 并以其返回值退出。"""

from reaction_reference.interfaces.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
