# 规划版本记录

当前运行环境将 `.git` 目录设为只读，因此 Git 元数据位于项目内的 `.plan-history.git/`。

在项目目录使用以下命令查看正常的 Git 提交、状态和差异：

```bash
./scripts/plan-git status
./scripts/plan-git log --oneline
./scripts/plan-git show <commit>
./scripts/plan-git diff
```

也可直接执行 `git --git-dir=.plan-history.git --work-tree=. <command>`。
保留 `.plan-history.git/` 才能保留历史；它是实际仓库元数据，不被提交到自身。
