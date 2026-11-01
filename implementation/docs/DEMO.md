# 检索验证 Demo

入口为`/demo`。当前服务监听8028端口，可从本机打开 `http://127.0.0.1:8028/demo`；远程VSCode可转发8028端口，局域网用服务器IP访问相同路径。

1. 输入一个具体目标分子的SMILES，点击“预览查询”。目标、固定原子高亮、查询SMARTS和精确支链源端必要条件全部由RDKit生成SVG。
2. 点击“开始检索”，调用正式v3来源和检索编排；保持实际来源分数≥12门槛。可选40/100/160任务及10/30秒预算。
3. 完成或取消后，查询列表显示实际家族，包括动态补查与放宽。展开查看每个阶段的执行范围；未调度、初选流结束与独立子结构范围结束不同。
4. 推荐区按实际展示顺序绘制来源反应物→产物，显示匹配角色、来源定位、覆盖、贡献、条件与限制。较长反应图可横向滚动。试剂、催化剂及溶剂在材料详情中，不擅自归为反应物。

该页面用于人工验证，不验证抽取结构是否化学正确，也不保证来源条件可迁移到目标。覆盖率是连接覆盖，不能当作合成成功率。未明确步骤、未核实获得证据与预算截断仍显示。

启动（凭据从本机环境提供，不写入仓库）：

```bash
export RR_SOURCE_KIND=postgres
export RR_POSTGRES_TABLE=reaction_v3
# 在本机安全设置RR_POSTGRES_DSN。
export RR_STORE_PATH=/tmp/reaction-reference-demo-8028
implementation/.venv/bin/python -m reaction_reference.interfaces.cli serve --host 0.0.0.0 --port 8028
```

若设置`RR_API_TOKEN`，在页面输入同一令牌；只保留在当前页面内存，不写浏览器存储。未设置时令牌留空。临时运行目录不用于长期归档；正式使用可指定持久目录。

页面复用正式任务取消和结果快照。没有配置PostgreSQL时默认仍是包内软件示例，请按上述配置连接真实来源。接口为`POST /v1/demo/preview`和`GET /v1/search-runs/{run_id}/demo`，数据接口遵循现有内部认证。
