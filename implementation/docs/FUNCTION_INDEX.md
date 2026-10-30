# 函数阅读索引

由 `python scripts/check_comments.py --write-index` 生成；说明取自函数 docstring 首段。
先读 [交接指南](HANDOVER.md)，需要定位具体函数时再查本索引。源码行号会随修改变化，
提交前重新生成即可；匿名前端回调的中文说明直接写在 [页面源码](../src/reaction_reference/interfaces/static/index.html) 中。

## scripts/check_comments.py

| 函数 | 职责 |
|---|---|
| [python_files](../scripts/check_comments.py#L14) | 返回业务项目及仓库辅助脚本，包含 reviews、绘图脚本与无扩展名启动器。 |
| [english_prose](../scripts/check_comments.py#L33) | 判断一段说明是否仍为纯英文；中文中的函数名和化学缩写可以保留。 |
| [definitions](../scripts/check_comments.py#L53) | 递归列出具名类及同步/异步函数，保留类名和闭包名，便于定位同名定义。 |
| [inspect_comments](../scripts/check_comments.py#L64) | 检查全仓库 Python 的说明和所有注释，返回统计及逐文件函数索引。 |
| [write_index](../scripts/check_comments.py#L101) | 把具名函数的中文摘要和源码行号写入索引；行号变化后可再次运行本脚本刷新。 |
| [main](../scripts/check_comments.py#L119) | 执行中文说明覆盖检查；带 --write-index 时额外刷新 Markdown 函数索引。 |

## scripts/check_deployment.py

| 函数 | 职责 |
|---|---|
| [fetch](../scripts/check_deployment.py#L13) | 发送有超时的 HTTP 请求并返回原始响应体；令牌只放在请求头中。 |
| [check](../scripts/check_deployment.py#L25) | 验证包内示例服务的完整请求链，返回有限验收结果；不会改动来源反应数据。 |
| [main](../scripts/check_deployment.py#L110) | 读取地址和可选预期代码哈希，运行验收并输出 JSON；访问令牌从环境读取。 |

## scripts/probe_source.py

| 函数 | 职责 |
|---|---|
| [main](../scripts/probe_source.py#L12) | 读取 RR_POSTGRES_DSN，执行只读常量化学探针和索引就绪检查并打印 JSON。 |

## src/reaction_reference/adapters/annotations.py

| 函数 | 职责 |
|---|---|
| [AnnotatedSource.__init__](../src/reaction_reference/adapters/annotations.py#L28) | 读取有限 JSONL 审核文件并建立 record_id 索引，继承被包装来源的能力。 |
| [AnnotatedSource._apply](../src/reaction_reference/adapters/annotations.py#L57) | 将审核信息应用到一个来源记录的副本并缓存结果。 |
| [AnnotatedSource.candidate_page](../src/reaction_reference/adapters/annotations.py#L117) | 原样委托底层来源分页，不在候选召回时提前给产品赋予审核证据。 |
| [AnnotatedSource.hydrate](../src/reaction_reference/adapters/annotations.py#L121) | 先委托底层加载详情，再按记录哈希附加审核信息，返回新的或原有记录。 |
| [AnnotatedSource.close](../src/reaction_reference/adapters/annotations.py#L125) | 关闭被包装来源，其连接与缓存仍归原适配器管理。 |

## src/reaction_reference/adapters/execution.py

| 函数 | 职责 |
|---|---|
| [_worker](../src/reaction_reference/adapters/execution.py#L17) | 在独立进程中恢复请求和来源、执行检索，通过单向管道发送进度/结果或受限错误。 |
| [_receive_packages](../src/reaction_reference/adapters/execution.py#L59) | 阻塞读取完整管道消息，再交给有界本地队列；监督线程不直接等待消息体。 |
| [RunManager.__init__](../src/reaction_reference/adapters/execution.py#L113) | 获取目录协调锁、恢复中断状态，再按设置创建有界工作并发的监督线程池。 |
| [RunManager.validate_lab_context](../src/reaction_reference/adapters/execution.py#L139) | 统一校验检索及重排中的排除结构，不依赖结果池是否为空，也不创建任务。 |
| [RunManager.submit](../src/reaction_reference/adapters/execution.py#L148) | 验证目标和排除材料结构后接纳检索，保存 queued 状态并返回 RunState。 |
| [RunManager._release](../src/reaction_reference/adapters/execution.py#L209) | 保存未启动任务的取消终态，再清除内存登记和取消事件。 |
| [RunManager._execute](../src/reaction_reference/adapters/execution.py#L222) | 执行监督边界并兜底保存 failed，避免启动/监督异常把状态永远留在 running。 |
| [RunManager._supervise](../src/reaction_reference/adapters/execution.py#L240) | 监督独立进程及其接收线程，截止时间从启动准备开始计算。 |
| [RunManager._finish](../src/reaction_reference/adapters/execution.py#L340) | 在锁内把非终态 run 写为给定终态并返回状态。 |
| [RunManager.cancel](../src/reaction_reference/adapters/execution.py#L364) | 请求取消 owner 范围内的运行，短暂等待监督器停止工作后返回实际状态。 |
| [RunManager.wait](../src/reaction_reference/adapters/execution.py#L387) | 等待本管理器登记的 future 结束，再从磁盘返回真实 RunState。 |
| [RunManager.active_writer](../src/reaction_reference/adapters/execution.py#L406) | 登记同步写操作的生命周期；计算期间释放协调锁，关闭等待已登记操作完成后再释放目录锁。 |
| [RunManager.close](../src/reaction_reference/adapters/execution.py#L419) | 停止接纳任务，向所有登记作业发取消信号，等待监督线程清理后释放目录锁。 |

## src/reaction_reference/adapters/export.py

| 函数 | 职责 |
|---|---|
| [export_sample](../src/reaction_reference/adapters/export.py#L10) | 只读按主键导出 after_id 后至多 limit 条反应到新的 JSONL 文件。 |

## src/reaction_reference/adapters/run_store.py

| 函数 | 职责 |
|---|---|
| [FileRunStore.__init__](../src/reaction_reference/adapters/run_store.py#L25) | 建立运行根目录和线程锁；跨进程互斥需额外调用 acquire_coordinator。 |
| [FileRunStore.acquire_coordinator](../src/reaction_reference/adapters/run_store.py#L33) | 获取运行目录的非阻塞排他文件锁；已有协调器占用时抛出 RuntimeError。 |
| [FileRunStore.close](../src/reaction_reference/adapters/run_store.py#L48) | 释放当前持有的协调器文件锁；未持锁或已关闭时不做操作。 |
| [FileRunStore._directory](../src/reaction_reference/adapters/run_store.py#L56) | 校验 run_id 是 32 位小写十六进制字符串，返回对应目录路径。 |
| [FileRunStore._snapshot_path](../src/reaction_reference/adapters/run_store.py#L66) | 校验快照标识为至多 64 位的非空小写十六进制字符串，返回受限文件路径。 |
| [FileRunStore._atomic](../src/reaction_reference/adapters/run_store.py#L78) | 把文本写入同目录临时文件，经 fsync 后原子替换目标，再同步目录。 |
| [FileRunStore.create](../src/reaction_reference/adapters/run_store.py#L100) | 创建一个新运行目录并持久化初始 RunState；同 ID 目录存在时拒绝覆盖。 |
| [FileRunStore.load](../src/reaction_reference/adapters/run_store.py#L107) | 读取并校验指定 run 的状态，返回 RunState。 |
| [FileRunStore.update](../src/reaction_reference/adapters/run_store.py#L126) | 按 expected_revision 更新非终态运行并返回递增 revision 后的状态。 |
| [FileRunStore.save_package](../src/reaction_reference/adapters/run_store.py#L141) | 保存不可变 ReferencePackage 快照，并原子更新 latest 指针。 |
| [FileRunStore.package](../src/reaction_reference/adapters/run_store.py#L158) | 读取指定快照，或在未指定时读取 latest 指向的资料包。 |
| [FileRunStore.idempotency](../src/reaction_reference/adapters/run_store.py#L186) | 查找或绑定 owner 范围内的幂等键，返回先前 run_id 或 None。 |
| [FileRunStore.interrupt_snapshot](../src/reaction_reference/adapters/run_store.py#L214) | 为中断任务保存带停止原因的部分范围快照，返回新快照 ID 或 None。 |
| [FileRunStore.recover_interrupted](../src/reaction_reference/adapters/run_store.py#L235) | 逐任务恢复遗留 queued/running；坏状态和快照隔离到 recovery_issues，保留原文件。 |

## src/reaction_reference/adapters/sources.py

| 函数 | 职责 |
|---|---|
| [_locator_value_present](../src/reaction_reference/adapters/sources.py#L26) | 检查定位字段是否有明确非空值；整数零有效，布尔值及含缺失项的数组无效。 |
| [_compound_source_id](../src/reaction_reference/adapters/sources.py#L38) | 为复合来源标识转义百分号和冒号，避免字段边界碰撞；普通标识保持原有可读格式。 |
| [import_native](../src/reaction_reference/adapters/sources.py#L43) | 把本项目 ReactionRecord JSON 或现有反应表导出行转换为统一记录。 |
| [JsonlSource.__init__](../src/reaction_reference/adapters/sources.py#L163) | 读取有限 JSONL，建立来源快照及材料/指纹缓存，隔离脏记录。 |
| [JsonlSource.candidate_page](../src/reaction_reference/adapters/sources.py#L235) | 返回家族、角色、选择阶段和目标共同限定范围的一页 CandidatePage。 |
| [JsonlSource.close](../src/reaction_reference/adapters/sources.py#L281) | 清空按家族/角色/目标/选择阶段缓存的候选顺序；无外部连接需要关闭。 |
| [JsonlSource.hydrate](../src/reaction_reference/adapters/sources.py#L285) | 返回已在内存完整加载的 ReactionRecord，不发起额外 I/O。 |
| [PostgresSource.__init__](../src/reaction_reference/adapters/sources.py#L318) | 建立只读 Repeatable Read 会话、SQL 超时及指纹/手性参数，核对有效索引。 |
| [PostgresSource._has_index](../src/reaction_reference/adapters/sources.py#L365) | 检查指定列是否为有效 GiST 的真实键列，返回 bool。 |
| [PostgresSource._assert_index](../src/reaction_reference/adapters/sources.py#L372) | 要求指定化学列具备 GiST；缺失时抛出 ValueError，明确来源能力未就绪。 |
| [PostgresSource._items](../src/reaction_reference/adapters/sources.py#L377) | 把轻量 SQL 行展开为指定角色的具体材料候选并保留原行用于详情加载。 |
| [PostgresSource.candidate_page](../src/reaction_reference/adapters/sources.py#L411) | 在同一只读会话中读取一页候选，返回实例及范围标签。 |
| [PostgresSource.hydrate](../src/reaction_reference/adapters/sources.py#L477) | 对已命中的轻量记录按需读取详情、重建统一记录并缓存。 |
| [PostgresSource._fetch_details](../src/reaction_reference/adapters/sources.py#L496) | 按完整来源组合键或 reaction_id 查询至多一条详情 JSON。 |
| [PostgresSource.close](../src/reaction_reference/adapters/sources.py#L538) | 回滚并关闭只读会话，同时释放其服务端游标；旧游标不能跨新会话续用。 |

## src/reaction_reference/analogs/transfer.py

| 函数 | 职责 |
|---|---|
| [source_rules](../src/reaction_reference/analogs/transfer.py#L14) | 返回可用于当前来源的有序回放规则：合法 radius-2 来源模板优先，其后为注册规则。 |
| [replay](../src/reaction_reference/analogs/transfer.py#L48) | 对一组输入 Mol 执行 RDKit 反应，保留每次回放的完整产品组。 |
| [generate_proposals](../src/reaction_reference/analogs/transfer.py#L67) | 从一个来源参考生成只替换一个完整反应物的有限建议。 |

## src/reaction_reference/application/budget.py

| 函数 | 职责 |
|---|---|
| [Budget.__init__](../src/reaction_reference/application/budget.py#L17) | 接收 BudgetConfig，以当前单调时钟建立执行截止时间并将计数归零。 |
| [Budget.check](../src/reaction_reference/application/budget.py#L29) | 检查当前时间是否达到 deadline；超时抛出 BudgetExceeded，无返回值。 |
| [Budget.task](../src/reaction_reference/application/budget.py#L34) | 检查时间和任务额度后记入一条 TaskEvent。 |
| [Budget.candidate](../src/reaction_reference/application/budget.py#L51) | 在逐候选处理前检查时间和候选上限，然后增加接收计数。 |
| [Budget.reaction](../src/reaction_reference/application/budget.py#L61) | 在首次分析一个反应前检查时间和反应上限，然后增加分析计数。 |

## src/reaction_reference/application/search.py

| 函数 | 职责 |
|---|---|
| [search](../src/reaction_reference/application/search.py#L40) | 执行一次目标导向的参考检索，返回 ReferencePackage，并可发布阶段快照。 |
| [search.package](../src/reaction_reference/application/search.py#L81) | 将当前累计状态排序、汇总并封装为一个新的结果快照。 |
| [search.publish](../src/reaction_reference/application/search.py#L257) | 按需向 on_progress 发布当前资料包；force=True 时跳过约 0.5 秒的节流。 |
| [search.retain_proposal](../src/reaction_reference/application/search.py#L267) | 立即保留已验证且唯一的建议并发布进度，返回是否还有全局建议名额。 |

## src/reaction_reference/bootstrap.py

| 函数 | 职责 |
|---|---|
| [open_source](../src/reaction_reference/bootstrap.py#L10) | 根据 Settings 创建 JSONL 或只读 PG 来源，并可包装审核证据适配器。 |
| [create_manager](../src/reaction_reference/bootstrap.py#L31) | 使用给定或默认 Settings 创建 RunManager，供 SDK/API 共享同一装配方式。 |

## src/reaction_reference/chemistry/markush.py

| 函数 | 职责 |
|---|---|
| [compile_family](../src/reaction_reference/chemistry/markush.py#L11) | 从 QueryFamily 的 SMARTS/CXSMARTS 恢复查询 Mol 和原生 generic 属性。 |
| [_predicates](../src/reaction_reference/chemistry/markush.py#L28) | 检查某一次固定核心映射下的全部 R 条件，返回 bool。 |
| [match_family](../src/reaction_reference/chemistry/markush.py#L101) | 在一个具体来源分子上核验家族并返回 MatchResult 与一致的匹配见证。 |
| [coverage_summary](../src/reaction_reference/chemistry/markush.py#L252) | 汇总已得到的见证，分别返回最佳单见证联合覆盖和跨见证位点并集。 |

## src/reaction_reference/chemistry/structures.py

| 函数 | 职责 |
|---|---|
| [digest](../src/reaction_reference/chemistry/structures.py#L16) | 为可 JSON 序列化的数据生成稳定 SHA-256 摘要。 |
| [parse](../src/reaction_reference/chemistry/structures.py#L28) | 将 SMILES 解析为 RDKit Mol；无效或空结构抛出 StructureError。 |
| [parse_material](../src/reaction_reference/chemistry/structures.py#L56) | 解析一个来源材料，拒绝多组分、虚原子和当前不支持的增强立体组。 |
| [without_maps](../src/reaction_reference/chemistry/structures.py#L73) | 复制 Mol 并清除反应原子映射号，返回新分子。 |
| [canonical](../src/reaction_reference/chemistry/structures.py#L84) | 为 SMILES 或 Mol 生成去映射号的规范 SMILES 身份键。 |
| [meets_target](../src/reaction_reference/chemistry/structures.py#L96) | 判断候选是否满足完整目标的连接、同位素、电荷及已指定的立体要求。 |
| [similarity](../src/reaction_reference/chemistry/structures.py#L116) | 返回两个 Mol 的 radius=2、2048 位 Morgan 指纹 Tanimoto 相似度。 |
| [descriptors](../src/reaction_reference/chemistry/structures.py#L129) | 计算具体 Mol 的平均摩尔质量（g/mol）和重原子数，返回字典。 |
| [atom_table](../src/reaction_reference/chemistry/structures.py#L140) | 按传入 Mol 的原子顺序生成目标原子表，含 target:index、元素、同位素和电荷。 |
| [fragment_key](../src/reaction_reference/chemistry/structures.py#L157) | 把指定片段转为带边界虚原子的结构签名，用于比较完整 R 块。 |
| [outside_blocks](../src/reaction_reference/chemistry/structures.py#L209) | 从给定核心外提取完整连通 R 块及其所有连接位点。 |

## src/reaction_reference/domain/models.py

| 函数 | 职责 |
|---|---|
| [LabContext.check_range](../src/reaction_reference/domain/models.py#L68) | 拒绝下限高于上限的温度范围，校验通过返回当前对象。 |
| [ReactionRecord.check_instances](../src/reaction_reference/domain/models.py#L171) | 验证材料 ID 唯一、观察确实指向产品、明确步骤有引文且不承载多步计数。 |
| [QueryFamily.check_correspondence](../src/reaction_reference/domain/models.py#L230) | 要求非空且唯一的目标原子对应，校验 R 位置不超出核心长度。 |

## src/reaction_reference/evaluation/runner.py

| 函数 | 职责 |
|---|---|
| [MaskedSource.__init__](../src/reaction_reference/evaluation/runner.py#L26) | 从固定样本已核验的产品候选找出满足 target 的记录 ID，建立派生来源快照。 |
| [MaskedSource.candidate_page](../src/reaction_reference/evaluation/runner.py#L43) | 委托原来源取页后移除被屏蔽记录，保留原范围、耗尽状态与游标。 |
| [MaskedSource.hydrate](../src/reaction_reference/evaluation/runner.py#L53) | 委托底层来源加载一个未被屏蔽的已命中记录，不创建新证据。 |
| [MaskedSource.close](../src/reaction_reference/evaluation/runner.py#L57) | 不关闭底层共享来源；评测主函数负责在两种任务完成后统一释放。 |
| [select_targets](../src/reaction_reference/evaluation/runner.py#L62) | 从有限非合成产品中用最远优先的指纹距离选出结构多样的目标。 |
| [evaluate](../src/reaction_reference/evaluation/runner.py#L113) | 逐目标运行保留来源与屏蔽全部目标产物记录两种任务并写入 JSON 报告。 |

## src/reaction_reference/evidence/claims.py

| 函数 | 职责 |
|---|---|
| [evidence_for](../src/reaction_reference/evidence/claims.py#L7) | 判断一个材料实例的来源支持，返回（制备命中、获得命中、使用命中、Claim 列表）。 |
| [summary_items](../src/reaction_reference/evidence/claims.py#L69) | 把选中参考和建议转为受 UTF-8 字节预算约束的 JSON 摘要。 |

## src/reaction_reference/evidence/relations.py

| 函数 | 职责 |
|---|---|
| [material_relations](../src/reaction_reference/evidence/relations.py#L10) | 连接不同来源记录中同身份的产品与反应物，返回（关系列表、范围内枚举是否完成）。 |

## src/reaction_reference/interfaces/api.py

| 函数 | 职责 |
|---|---|
| [create_app](../src/reaction_reference/interfaces/api.py#L25) | 装配 FastAPI 应用、共享 Client、内部认证和快照分页接口，返回 app。 |
| [create_app.lifespan](../src/reaction_reference/interfaces/api.py#L36) | 应用启动后接管共享客户端的生命周期，关闭时在线程池中等待清理。 |
| [create_app.index](../src/reaction_reference/interfaces/api.py#L52) | 返回随包分发的内部查看页面 HTML；页面本身不包含业务证据或访问令牌。 |
| [create_app.owner](../src/reaction_reference/interfaces/api.py#L56) | 验证可选内部 Bearer 令牌，返回固定 internal 访问范围。 |
| [create_app.encode_cursor](../src/reaction_reference/interfaces/api.py#L69) | 将运行、owner、snapshot 和 offset 编码并附加 HMAC 签名，返回分页令牌。 |
| [create_app.decode_cursor](../src/reaction_reference/interfaces/api.py#L78) | 校验分页令牌长度和 HMAC 后恢复游标字段，非法内容返回 422。 |
| [create_app.missing](../src/reaction_reference/interfaces/api.py#L95) | 把不存在或不可见的运行/快照 KeyError 转为 404 JSON。 |
| [create_app.conflict](../src/reaction_reference/interfaces/api.py#L100) | 把 revision、幂等或快照冲突转为 409 JSON。 |
| [create_app.capacity](../src/reaction_reference/interfaces/api.py#L105) | 把协调器容量不足转换为 429 JSON，不在 HTTP 层继续排无限任务。 |
| [create_app.invalid](../src/reaction_reference/interfaces/api.py#L110) | 把业务输入 ValueError 转为 422，截断消息长度，不返回原生堆栈。 |
| [create_app.live](../src/reaction_reference/interfaces/api.py#L117) | 返回进程存活标志，不检查来源连接，因此不代表检索已就绪。 |
| [create_app.ready](../src/reaction_reference/interfaces/api.py#L122) | 校验规则并尝试打开/关闭来源，返回 ready 或 503。 |
| [create_app.get_capabilities](../src/reaction_reference/interfaces/api.py#L142) | 返回当前规则版本、支持查询/分析能力及未支持范围，受内部认证保护。 |
| [create_app.preview](../src/reaction_reference/interfaces/api.py#L147) | 调用 SDK 生成初始查询家族并序列化返回，不读取来源反应。 |
| [create_app.submit](../src/reaction_reference/interfaces/api.py#L152) | 校验幂等键长度后提交检索，返回 202 和初始 RunState。 |
| [create_app.status](../src/reaction_reference/interfaces/api.py#L166) | 读取访问范围内的运行状态，并附上最新已保存快照的统计与完整性。 |
| [create_app.results](../src/reaction_reference/interfaces/api.py#L181) | 按已发布的展示 ID 顺序返回参考卡片和建议卡片及下页游标。 |
| [create_app.evidence](../src/reaction_reference/interfaces/api.py#L235) | 在指定 run 的最新资料包中查找 Claim 或实验绑定 Witness。 |
| [create_app.export_package](../src/reaction_reference/interfaces/api.py#L257) | 返回访问范围内的完整 JSON 资料包，可指定固定 snapshot。 |
| [create_app.structure](../src/reaction_reference/interfaces/api.py#L269) | 为运行内的指定参考生成带原子高亮的 SVG，可指定固定 snapshot。 |
| [create_app.cancel](../src/reaction_reference/interfaces/api.py#L293) | 请求协调器停止运行并返回其真实终态或当前状态，不在接口层伪造取消成功。 |
| [create_app.rerank](../src/reaction_reference/interfaces/api.py#L298) | 在当前访问范围内创建冻结证据重排 run，返回 202 和派生状态。 |

## src/reaction_reference/interfaces/cli.py

| 函数 | 职责 |
|---|---|
| [_write](../src/reaction_reference/interfaces/cli.py#L20) | 把可 JSON 序列化数据写入指定文件或标准输出，保留中文并缩进。 |
| [main](../src/reaction_reference/interfaces/cli.py#L33) | 解析 argv 并分派 CLI 命令，返回进程退出码。 |

## src/reaction_reference/interfaces/depiction.py

| 函数 | 职责 |
|---|---|
| [reference_svg](../src/reaction_reference/interfaces/depiction.py#L8) | 绘制 Reference 的具体材料，按最佳已发现单见证高亮覆盖原子。 |

## src/reaction_reference/interfaces/sdk.py

| 函数 | 职责 |
|---|---|
| [Client.__init__](../src/reaction_reference/interfaces/sdk.py#L18) | 通过统一装配入口创建 RunManager，读取 Settings 或使用传入配置。 |
| [Client.search](../src/reaction_reference/interfaces/sdk.py#L25) | 提交 SearchRequest 并等待执行完成，返回保留的 ReferencePackage。 |
| [Client.preview](../src/reaction_reference/interfaces/sdk.py#L38) | 仅解析目标并生成与真实检索相同的初始家族列表，不查询来源。 |
| [Client.rerank](../src/reaction_reference/interfaces/sdk.py#L49) | 在 owner 范围内，从已有资料快照创建一个立即完成的重排派生 run。 |
| [Client.close](../src/reaction_reference/interfaces/sdk.py#L129) | 关闭协调器，停止其未完成任务并释放运行目录锁。 |
| [Client.__enter__](../src/reaction_reference/interfaces/sdk.py#L133) | 返回当前客户端，供 with 语句复用同一个协调器。 |
| [Client.__exit__](../src/reaction_reference/interfaces/sdk.py#L137) | 退出 with 时关闭客户端；不吞掉业务块抛出的异常。 |

## src/reaction_reference/ports/sources.py

| 函数 | 职责 |
|---|---|
| [CompoundSource.candidate_page](../src/reaction_reference/ports/sources.py#L35) | 读取家族在指定角色和选择阶段中的一页候选，返回 CandidatePage。 |
| [CompoundSource.close](../src/reaction_reference/ports/sources.py#L50) | 释放来源连接、游标或缓存；使用方应在 finally 中调用。 |
| [CompoundSource.hydrate](../src/reaction_reference/ports/sources.py#L54) | 为已命中的轻量记录补读详情并返回 ReactionRecord。 |

## src/reaction_reference/ranking/engine.py

| 函数 | 职责 |
|---|---|
| [lab_fit](../src/reaction_reference/ranking/engine.py#L7) | 将参考条件与 LabContext 的温度、压力、设备和排除材料要求比较。 |
| [_priority](../src/reaction_reference/ranking/engine.py#L78) | 返回参考的方法/证据优先级，数值越小越优先。 |
| [rank_references](../src/reaction_reference/ranking/engine.py#L102) | 返回（全部已评估参考的排序副本、选中展示的参考 ID 列表）。 |
| [rank_references.key](../src/reaction_reference/ranking/engine.py#L136) | 为单个参考生成可传递且稳定的排序元组。 |

## src/reaction_reference/ranking/features.py

| 函数 | 职责 |
|---|---|
| [_feature](../src/reaction_reference/ranking/features.py#L9) | 把一个特征值封装为状态、支持依据和限制的统一字典。 |
| [condition_issues](../src/reaction_reference/ranking/features.py#L17) | 标记来源中的倒置温度范围和负时长；保留原始数值供核查，正常低温和零时长有效。 |
| [features](../src/reaction_reference/ranking/features.py#L31) | 为具体 Reference 提取九方向解释信息，返回特征字典。 |

## src/reaction_reference/reaction_analysis/analyze.py

| 函数 | 职责 |
|---|---|
| [_bonds](../src/reaction_reference/reaction_analysis/analyze.py#L11) | 返回以排序后的正映射号对为键、键型字符串为值的字典。 |
| [_atoms](../src/reaction_reference/reaction_analysis/analyze.py#L25) | 建立正原子映射号到 Atom 的查找表，忽略 map=0 的原子。 |
| [_resonance_pairs](../src/reaction_reference/reaction_analysis/analyze.py#L30) | 识别已限定的硝基/羧酸根末端氧共振交换，返回可作为表示变化处理的键对。 |
| [_cycle_rank](../src/reaction_reference/reaction_analysis/analyze.py#L95) | 计算分子图的独立环数 E−V+C，用于环变化诊断。 |
| [analyze_reaction](../src/reaction_reference/reaction_analysis/analyze.py#L103) | 分析一个 ReactionRecord 的映射端点，返回 ReactionAnalysis。 |
| [project_changes](../src/reaction_reference/reaction_analysis/analyze.py#L296) | 把来源产物上的实际变化，通过一个 Witness 投影到目标原子编号。 |

## src/reaction_reference/retrieval/planner.py

| 函数 | 职责 |
|---|---|
| [functional_matches](../src/reaction_reference/retrieval/planner.py#L12) | 按规则优先级识别官能团，返回（规则名、目标原子元组、优先级）列表。 |
| [_close_units](../src/reaction_reference/retrieval/planner.py#L28) | 把与 seed 相交的功能单元补入核心原子集合并返回新集合。 |
| [_core_smarts](../src/reaction_reference/retrieval/planner.py#L47) | 为选定目标原子构造带目标映射号的固定核心 SMARTS。 |
| [plan_families](../src/reaction_reference/retrieval/planner.py#L83) | 自动生成整体、核心、分片三层的有限 QueryFamily 列表。 |
| [directed_family](../src/reaction_reference/retrieval/planner.py#L195) | 针对缺失核心位点，将目标实际 R 块加为精确约束后返回子家族。 |
| [exact_family](../src/reaction_reference/retrieval/planner.py#L224) | 构造完整目标补查家族，保留 SMARTS 序列化后的目标原子对应。 |
| [initial_families](../src/reaction_reference/retrieval/planner.py#L247) | 组合初始三层家族与可选的严格目标补查，返回有顺序的列表。 |

## src/reaction_reference/rules.py

| 函数 | 职责 |
|---|---|
| [code_fingerprint](../src/reaction_reference/rules.py#L45) | 对包内 Python、规则/示例 JSON 和 HTML 的路径与原始内容计算 SHA-256。 |
| [load_rules](../src/reaction_reference/rules.py#L59) | 读取随包 rules.json，严格校验契约并编译官能团及双向回放规则。 |
| [capabilities](../src/reaction_reference/rules.py#L95) | 返回与当前规则版本绑定的查询形式、来源、分析能力和未支持清单。 |

## src/reaction_reference/schema_export.py

| 函数 | 职责 |
|---|---|
| [export_schemas](../src/reaction_reference/schema_export.py#L18) | 把请求、家族、反应、证据审核、资料包与状态 Schema 及 OpenAPI 写入 directory。 |

## src/reaction_reference/settings.py

| 函数 | 职责 |
|---|---|
| [Settings.worker_config](../src/reaction_reference/settings.py#L31) | 提取子进程建立来源所需的可序列化配置，返回普通字典。 |

## tests/conftest.py

| 函数 | 职责 |
|---|---|
| [fixture_path](../tests/conftest.py#L11) | 返回随包分发的合成示例路径，确保默认测试不访问真实来源。 |
| [source](../tests/conftest.py#L17) | 为测试创建有限穷尽 JSONL 来源，yield 后清空来源缓存。 |
| [amide](../tests/conftest.py#L25) | 从合成来源挑出乙胺酰胺化记录，供映射与单输入替换测试使用。 |
| [request_factory](../tests/conftest.py#L31) | 提供统一请求构造器，允许测试仅覆盖与当前场景相关的字段。 |
| [request_factory.create](../tests/conftest.py#L34) | 将目标 SMILES 和覆盖参数构造成严格 SearchRequest，返回测试请求。 |
| [settings](../tests/conftest.py#L42) | 为每个测试分配独立临时运行目录，避免协调锁与作业状态互相污染。 |

## tests/test_annotations.py

| 函数 | 职责 |
|---|---|
| [annotation](../tests/test_annotations.py#L11) | 构造绑定记录哈希的测试审核行；updates 用于模拟哈希错误或特定审核输入。 |
| [test_review_bound_to_record_hash](../tests/test_annotations.py#L27) | 确认来源哈希不符时拒绝旧审核，原记录保留并记录局部问题。 |
| [test_review_does_not_erase_synthetic_origin](../tests/test_annotations.py#L36) | 确认有效审核也不能把合成示例升级为真实文献制备证据。 |
| [test_overlay_accepts_the_declared_minimum_source_protocol](../tests/test_annotations.py#L46) | 审核装饰器必须支持已声明的最小来源协议，不能强制访问协议外的可选能力属性。 |
| [test_overlay_accepts_the_declared_minimum_source_protocol.MinimalSource.candidate_page](../tests/test_annotations.py#L56) | 提供一个合法空页，验证包装后仍可正常委托查询。 |
| [test_overlay_accepts_the_declared_minimum_source_protocol.MinimalSource.hydrate](../tests/test_annotations.py#L60) | 完整来源无需额外加载，返回原记录。 |
| [test_overlay_accepts_the_declared_minimum_source_protocol.MinimalSource.close](../tests/test_annotations.py#L64) | 记录调用方释放了来源。 |

## tests/test_architecture.py

| 函数 | 职责 |
|---|---|
| [test_domain_and_chemical_layers_do_not_import_adapters_or_interfaces](../tests/test_architecture.py#L13) | 检查领域、化学与应用模块不反向导入具体适配器/接口；领域也不依赖 RDKit、HTTP 或 PG。 |
| [test_rules_compile_and_have_regression_scope](../tests/test_architecture.py#L39) | 确认随包规则可编译、含内容哈希并显式列出未支持范围。 |
| [test_contract_schema_is_exported](../tests/test_architecture.py#L46) | 比较已提交请求 Schema 与当前模型导出，防止接口契约悄然漂移。 |

## tests/test_browser_integration.py

| 函数 | 职责 |
|---|---|
| [browser_server](../tests/test_browser_integration.py#L22) | 启动私有运行目录和二十条合成记录的服务，监听预先分配的本机端口并统一清理。 |
| [chromium](../tests/test_browser_integration.py#L90) | 打开本机已安装的 Chromium；缺少浏览器时明确跳过，不自动访问外部站点。 |
| [browser_page](../tests/test_browser_integration.py#L104) | 为每项用例创建独立页面，默认提供正确内部令牌。 |
| [test_fractional_temperature_can_submit](../tests/test_browser_integration.py#L117) | 后端允许的小数温度必须能通过浏览器表单校验，并按原数值发送请求。 |
| [test_browser_pagination_structures_rerank_and_download](../tests/test_browser_integration.py#L128) | 真实页面的分页、图片、重排和下载必须始终绑定当前运行及快照。 |
| [test_browser_can_retry_after_authentication_failure](../tests/test_browser_integration.py#L160) | 错误令牌得到可见错误后，修正令牌可再次提交，不沿用失败任务状态。 |
| [test_browser_download_preserves_original_integer_metadata](../tests/test_browser_integration.py#L176) | 下载完整资料包时不能经过 JavaScript 数值重编码，避免合法大整数被舍入。 |

## tests/test_chemistry.py

| 函数 | 职责 |
|---|---|
| [family](../tests/test_chemistry.py#L15) | 为单一化学边界构造最小 QueryFamily，避免自动规划掩盖核验错误。 |
| [test_auto_queries_preserve_target](../tests/test_chemistry.py#L32) | 多类目标生成三层家族后应能自匹配，且最佳一致见证覆盖完整目标连接。 |
| [test_functional_oxygen_role_is_preserved](../tests/test_chemistry.py#L43) | 确认目标羟基约束不会把醚氧当作同一角色而放行。 |
| [test_whole_r_not_just_first_atom](../tests/test_chemistry.py#L50) | 确认 R 类别与长度检查整个连接块，支链后部杂原子和超长碳链不能漏检。 |
| [test_symmetric_core_checks_all_orientations_before_dedup](../tests/test_chemistry.py#L66) | 确认核心对称方向先逐一检查 R；映射截断时未发现的方向只可返回未知。 |
| [test_extra_internal_edge_is_not_a_chain_witness](../tests/test_chemistry.py#L85) | 确认环的额外内部边不会被当作严格的线性核心见证。 |
| [test_explicit_deuterium_is_not_heavy_sidechain](../tests/test_chemistry.py#L94) | 确认显式氘不计重原子支链，但完整目标身份仍保留其同位素要求。 |
| [test_target_stereo_is_a_requirement](../tests/test_chemistry.py#L102) | 确认指定目标构型排除反构型/未指定候选，未指定目标可接受相应具体构型。 |
| [test_equality_checks_entire_substituents](../tests/test_chemistry.py#L111) | 确认 R 相等比较完整支链，不把乙基和丙基判为相等。 |
| [test_atom_order_does_not_change_canonical_identity](../tests/test_chemistry.py#L120) | 用属性测试确认原子重排不改变规范身份和完整目标满足关系。 |
| [test_input_validation_rejects_unknown_and_coerced_budget](../tests/test_chemistry.py#L130) | 确认未知收费字段、布尔预算和字符串布尔开关被契约拒绝。 |
| [test_isotopic_hydrogen_is_retained_in_core_and_r_signature](../tests/test_chemistry.py#L140) | 确认核心及支链签名保留同位素氢，普通氢候选不能冒充氘目标。 |
| [test_native_generic_query_restores_properties_after_ir_roundtrip](../tests/test_chemistry.py#L153) | 确认家族 JSON 往返恢复 ARY generic 属性，芳基可匹配而环烷基不可混入。 |
| [test_sitewise_union_is_not_joint_coverage](../tests/test_chemistry.py#L162) | 确认对称映射的位点并集即使达到 100%，也不能伪造单见证双支链联合覆盖。 |

## tests/test_cli.py

| 函数 | 职责 |
|---|---|
| [test_cli_source_selection_honors_environment_and_explicit_flags](../tests/test_cli.py#L25) | 未显式选择来源时尊重环境；显式示例使用包内数据，显式文件路径选择 JSONL。 |
| [test_cli_source_selection_honors_environment_and_explicit_flags.SearchClient.__init__](../tests/test_cli.py#L37) | 记录当前命令选择的来源配置。 |
| [test_cli_source_selection_honors_environment_and_explicit_flags.SearchClient.__enter__](../tests/test_cli.py#L41) | 返回检索客户端替身。 |
| [test_cli_source_selection_honors_environment_and_explicit_flags.SearchClient.__exit__](../tests/test_cli.py#L45) | 替身没有需要释放的外部资源。 |
| [test_cli_source_selection_honors_environment_and_explicit_flags.SearchClient.search](../tests/test_cli.py#L49) | 返回空资料包，使本例只观察检索命令的配置选择。 |
| [test_cli_rejects_incompatible_source_path](../tests/test_cli.py#L79) | 示例或 PG 模式不能同时指定 JSONL 路径，避免悄悄使用与命令含义不同的来源。 |
| [test_inspect_run_reads_while_coordinator_is_active](../tests/test_cli.py#L87) | 服务持有协调锁时，命令行仍能只读查看任务，且不更改任务生命周期。 |
| [test_preview_does_not_acquire_coordinator_or_recover_runs](../tests/test_cli.py#L109) | 预览在服务运行时可用，在服务停止时也不能把遗留任务标记为恢复失败。 |

## tests/test_data_boundaries.py

| 函数 | 职责 |
|---|---|
| [empty_snapshot](../tests/test_data_boundaries.py#L22) | 保存无命中资料包，让校验测试不依赖任何化学匹配结果。 |
| [test_incomplete_source_locator_does_not_merge_different_records](../tests/test_data_boundaries.py#L65) | 实验定位不完整时按来源记录身份计数，不能把不同反应拼成同一实验。 |
| [test_complete_source_locator_still_groups_duplicate_experiment_records](../tests/test_data_boundaries.py#L78) | 完整文献、段落与反应序号仍表示同一实验，序号零是合法值。 |
| [test_native_record_components_cannot_collide_at_delimiters](../tests/test_data_boundaries.py#L86) | 命名空间和记录编号中的分隔符不能把不同合法记录拼成同一个 ID 并一起丢弃。 |
| [test_experiment_components_cannot_collide_at_delimiters](../tests/test_data_boundaries.py#L109) | 不同命名空间及文档的完整实验定位也必须保持唯一，字面转义符不能产生新碰撞。 |
| [test_missing_native_record_id_is_rejected](../tests/test_data_boundaries.py#L126) | 导出行缺少有效记录 ID 时应隔离该行，不能转换成共享的 None 或空身份。 |
| [test_empty_rerank_validates_exclusions_before_creating_run](../tests/test_data_boundaries.py#L132) | 即使没有参考项触发排序循环，无效实验排除结构仍应拒绝且不创建派生任务。 |
| [test_stored_identity_must_match_requested_file](../tests/test_data_boundaries.py#L143) | 文件内容误放到其他任务或快照路径时必须报冲突，不能返回错配资料。 |
| [SampleConnection.__init__](../tests/test_data_boundaries.py#L165) | 准备两条具有非 ASCII 文本的记录，供完整导出和半途失败使用。 |
| [SampleConnection.__enter__](../tests/test_data_boundaries.py#L169) | 返回受上下文管理的连接替身。 |
| [SampleConnection.__exit__](../tests/test_data_boundaries.py#L173) | 内存连接没有外部资源。 |
| [SampleConnection.execute](../tests/test_data_boundaries.py#L177) | 接受只读查询并保留统一的结果读取入口。 |
| [SampleConnection.fetchone](../tests/test_data_boundaries.py#L181) | 返回固定快照标识。 |
| [SampleConnection.fetchall](../tests/test_data_boundaries.py#L185) | 返回有限样本记录。 |
| [sample_connection](../tests/test_data_boundaries.py#L190) | 替换连接函数，保证导出回归只访问本地临时文件。 |
| [sample_connection.connect](../tests/test_data_boundaries.py#L194) | 返回已准备的内存连接。 |
| [test_failed_export_is_not_published_and_can_retry](../tests/test_data_boundaries.py#L202) | 第二条记录序列化失败时，不能留下看似完整的最终文件，并且允许同路径重试。 |
| [test_failed_export_is_not_published_and_can_retry.fail_second](../tests/test_data_boundaries.py#L208) | 只模拟第二条记录写入前的失败，使旧实现已经写出第一行。 |
| [test_export_never_overwrites_existing_file](../tests/test_data_boundaries.py#L227) | 同名文件已存在时保持原样，不论其内容是否是有效 JSONL。 |
| [test_concurrent_export_keeps_the_first_published_file](../tests/test_data_boundaries.py#L237) | 另一写入者在最终发布前抢先创建文件时，不覆盖它，并清理本次临时文件。 |
| [test_concurrent_export_keeps_the_first_published_file.publish_race](../tests/test_data_boundaries.py#L243) | 模拟检查路径为空后，另一进程恰好先发布结果。 |
| [test_export_publication_failure_does_not_leave_output](../tests/test_data_boundaries.py#L255) | 最终发布失败时也应删除临时文件，避免无效导出占用目标路径。 |
| [test_export_publication_failure_does_not_leave_output.failed_publish](../tests/test_data_boundaries.py#L260) | 模拟目标文件发布时的权限错误。 |

## tests/test_evaluation.py

| 函数 | 职责 |
|---|---|
| [test_masking_removes_target_records_and_unreviewed_is_not_scored](../tests/test_evaluation.py#L8) | 确认屏蔽移除全部目标来源产品，未审核相关性标签不会产生伪召回得分。 |

## tests/test_frontend.py

| 函数 | 职责 |
|---|---|
| [test_frontend_task_isolation_and_current_results](../tests/test_frontend.py#L11) | 运行乱序状态、分页、异常、下载精度与错误、正常显示及串行轮询八个场景。 |

## tests/test_global_review.py

| 函数 | 职责 |
|---|---|
| [symmetric_reduction](../tests/test_global_review.py#L31) | 构造有完整输入/产物依据的对称酮还原示例，触发等价模板映射。 |
| [test_symmetric_replay_returns_unique_proposals](../tests/test_global_review.py#L57) | 两个等价逆向映射不能占用两个建议名额或产生相同建议 ID。 |
| [test_search_counts_and_displays_symmetric_proposal_once](../tests/test_global_review.py#L78) | 端到端资料包、统计与展示列表只能保留一次相同替换建议。 |
| [test_evaluation_rejects_malformed_method_labels](../tests/test_global_review.py#L103) | 错误标签格式不能被 set 隐式转换成字符或字典键，再当作人工审核正例计分。 |
| [test_minimum_task_budget_can_complete_one_reference](../tests/test_global_review.py#L130) | 合法的四/五任务预算足够取页、核验、可选详情和一次分析，不能在取页前耗尽。 |
| [test_minimum_task_budget_can_complete_one_reference.Source.candidate_page](../tests/test_global_review.py#L148) | 一次返回完整有限来源，确保本例预算只需覆盖一次处理链。 |
| [test_minimum_task_budget_can_complete_one_reference.Source.hydrate](../tests/test_global_review.py#L152) | 返回原记录，详情动作是否单独计数由来源能力声明控制。 |
| [test_verified_proposal_survives_later_replay_budget_exhaustion](../tests/test_global_review.py#L176) | 首条建议已通过正向回放后，下一条规则耗尽预算不能抹掉这条有效部分结果。 |
| [test_verified_proposal_survives_later_replay_budget_exhaustion.Source.candidate_page](../tests/test_global_review.py#L204) | 一次返回酰胺产物，检索链只使用三个任务额度。 |
| [test_verified_proposal_survives_later_replay_budget_exhaustion.Source.hydrate](../tests/test_global_review.py#L210) | 完整示例无需额外详情读取。 |
| [test_invalid_evaluation_row_is_rejected_before_source_access](../tests/test_global_review.py#L237) | 非法目标行在读取来源前得到输入错误，不泄漏类型异常或启动无效评测。 |
| [test_valid_evaluation_labels_preserve_reviewed_only_scoring](../tests/test_global_review.py#L246) | 合法标签只在已审核时计分，屏蔽组剔除被屏蔽正例且不伪造零或满分。 |
| [test_reordered_target_self_matches_keep_complete_joint_coverage](../tests/test_global_review.py#L271) | 对环系、无环、同位素及立体目标改变原子遍历顺序，核对预筛、身份和联合覆盖。 |

## tests/test_pipeline.py

| 函数 | 职责 |
|---|---|
| [test_end_to_end_package](../tests/test_pipeline.py#L12) | 检查目标到三层参考/替换/摘要的完整流程，合成示例不能增加文献命中。 |
| [test_budgets_return_usable_partial_results](../tests/test_pipeline.py#L29) | 确认小任务/候选预算会停止扩展并保留部分包，不超限或伪报完整。 |
| [test_cached_matches_never_reuse_wrong_atom_indices](../tests/test_pipeline.py#L38) | 确认同结构不同 SMILES 原子顺序的缓存不会错用目标到来源的索引。 |
| [test_bad_record_isolated](../tests/test_pipeline.py#L69) | 确认一条损坏 JSON 不阻断其他参考，局部问题仍使结果范围保持部分。 |
| [test_lab_unknown_not_easy_or_safe](../tests/test_pipeline.py#L79) | 确认缺温度与步骤归属的来源返回实验适配未知，而非通过或低风险。 |
| [test_imported_arrays_do_not_claim_preparation](../tests/test_pipeline.py#L88) | 确认来源产品/输入数组本身不构成制备或实际使用的报告证据。 |
| [test_atom_properties_and_ring_analysis_do_not_require_method_name](../tests/test_pipeline.py#L103) | 确认没有人工反应名称也能从实际键级与 H 变化识别修饰，支持仍标合成示例。 |
| [test_dirty_string_field_is_not_split_into_atom_materials](../tests/test_pipeline.py#L116) | 确认误写成字符串的 SMILES 数组被拒绝，不按字符生成材料实例。 |
| [test_later_fragment_witness_can_upgrade_reaction_contribution](../tests/test_pipeline.py#L124) | 确认后来的分片成键见证能升级已有核心结构线索，并保存正确方法见证。 |
| [test_mapping_incompleteness_is_accumulated_across_source_pages](../tests/test_pipeline.py#L167) | 确认前页映射截断不会被后页正常耗尽覆盖成完整匹配范围。 |
| [test_mapping_incompleteness_is_accumulated_across_source_pages.Source.candidate_page](../tests/test_pipeline.py#L194) | 按 cursor 返回两页，分别触发映射截断和流耗尽，供跨页完整性回归使用。 |
| [test_mapping_incompleteness_is_accumulated_across_source_pages.Source.hydrate](../tests/test_pipeline.py#L210) | 返回模拟记录本身；此测试不引入额外详情 I/O。 |
| [test_small_summary_budget_does_not_hide_full_evidence_or_claim_complete](../tests/test_pipeline.py#L233) | 确认摘要预算不足时标不可用且保留完整候选，不截断半条证据或伪报摘要完成。 |
| [test_detail_names_are_bound_by_structure_not_array_position](../tests/test_pipeline.py#L244) | 确认详情名称按结构身份绑定，材料数组顺序变化不会错配名称。 |
| [test_failed_similarity_selection_keeps_independent_substructure_opportunity](../tests/test_pipeline.py#L261) | 确认相似初选超时后仍有独立子结构补查机会，局部失败不会被隐藏。 |
| [test_failed_similarity_selection_keeps_independent_substructure_opportunity.Source.candidate_page](../tests/test_pipeline.py#L289) | stage=0 故意抛超时，其余阶段返回一个真实结构候选，验证独立补查分支。 |
| [test_failed_similarity_selection_keeps_independent_substructure_opportunity.Source.hydrate](../tests/test_pipeline.py#L301) | 返回模拟记录本身；此测试不引入额外详情 I/O。 |
| [test_duplicate_record_ids_cannot_mix_materials_and_reaction_analysis](../tests/test_pipeline.py#L321) | 确认同 ID 冲突记录整体隔离，完全重复记录去重，不混用实验材料与分析。 |
| [test_shared_structure_witness_is_bound_to_each_actual_experiment](../tests/test_pipeline.py#L339) | 确认结构核验可复用，但返回见证 ID 必须分别绑定不同实验来源。 |
| [test_missing_operation_fields_do_not_rank_as_easy_conditions](../tests/test_pipeline.py#L375) | 确认缺失温度/时长不能在操作偏好下获得比已知条件更容易的优势。 |
| [test_operation_preference_does_not_assume_zero_celsius_is_room_temperature](../tests/test_pipeline.py#L400) | 确认操作偏好以公开的 25°C 为参照，不把需要制冷的 0°C 当作室温。 |

## tests/test_postgres_integration.py

| 函数 | 职责 |
|---|---|
| [postgres_cluster](../tests/test_postgres_integration.py#L18) | 使用本机二进制启动私有 Unix socket 测试库，退出时停止，不接受外部连接配置。 |
| [indexed_source_dsn](../tests/test_postgres_integration.py#L79) | 为每项测试重建临时反应表、化学索引和三条示例，字段与生产适配器投影一致。 |
| [carbon_family](../tests/test_postgres_integration.py#L137) | 构造固定一个碳的家族，用于区分来源分页与应用层完整核验的职责。 |
| [test_indexed_cursor_pages_and_read_only_session](../tests/test_postgres_integration.py#L151) | 真实服务端游标按页返回全部材料，严格只读事务拒绝写入。 |
| [test_knn_selection_and_detail_hydration](../tests/test_postgres_integration.py#L178) | 真实指纹近邻首项命中乙醇，详情名称通过结构对应，并可切换独立子结构通道。 |
| [test_query_timeout_preserves_independent_query](../tests/test_postgres_integration.py#L202) | 真正的表锁等待触发查询超时，回滚保存点后另一个家族仍可使用同一来源会话。 |
| [test_repeatable_read_keeps_material_fields_frozen](../tests/test_postgres_integration.py#L217) | 来源建立快照后其他会话更新原行，本次查询和详情仍必须对应旧材料结构。 |
| [test_sql_row_paging_survives_dirty_and_multiple_materials](../tests/test_postgres_integration.py#L231) | SQL 游标按行推进，脏行不提前终结流，多产物行也不能跳过后一行。 |
| [test_indexed_source_runs_the_full_search_pipeline](../tests/test_postgres_integration.py#L257) | 真实 PG 候选、结构核验和详情共同生成资料包，产品字段不升级成制备证据。 |
| [test_incomplete_source_keys_do_not_attach_unidentified_details](../tests/test_postgres_integration.py#L293) | 两侧同为空定位不构成可靠实验关联，不能把未知归属的详情接到反应上。 |
| [test_direct_reaction_id_link_does_not_require_paragraph_locator](../tests/test_postgres_integration.py#L321) | 明确反应 ID 已建立可靠关联时，段落定位缺失不应阻止读取对应详情。 |

## tests/test_reactions.py

| 函数 | 职责 |
|---|---|
| [analysis](../tests/test_reactions.py#L13) | 用给定映射式重建测试两侧材料，再调用实际分析，隔离端点归属与键变化场景。 |
| [test_connection_and_leaving_fragment_not_all_broken](../tests/test_reactions.py#L26) | 确认酰胺新键与离去边界正确分账，缺少副产物不导致虚构大量断键。 |
| [test_invalid_mapping_is_unknown](../tests/test_reactions.py#L44) | 确认重复正映射、同位素冲突或非法反应式明确返回未知及原因。 |
| [test_map_zero_never_establishes_cross_side_identity](../tests/test_reactions.py#L50) | 确认 map=0 原子不参与跨侧身份，不从未映射区域制造成断键。 |
| [test_resonance_swap_not_transformation](../tests/test_reactions.py#L57) | 确认限定硝基氧共振交换记为表示变化，不计真实键级转化。 |
| [test_real_proton_transfer_not_suppressed_as_resonance](../tests/test_reactions.py#L64) | 确认羧酸的实际 H 迁移不会被共振规则抹除。 |
| [test_observed_ring_changes](../tests/test_reactions.py#L71) | 确认从实际命中反应变化识别闭环和开环，不依赖检索前虚构切环位置。 |
| [test_synthetic_sources_never_become_literature](../tests/test_reactions.py#L81) | 确认合成示例有演示 Claim，但没有真实制备/获得/使用命中。 |
| [test_product_presence_alone_not_preparation](../tests/test_reactions.py#L89) | 确认有产品结构不等于制得，实际输入使用只归属于对应反应物。 |
| [test_conflict_cancels_positive_outcome](../tests/test_reactions.py#L97) | 确认同产品的明确冲突会取消阳性制备标记。 |
| [reference](../tests/test_reactions.py#L112) | 为回放测试构造带来源映射分析的最小 Reference。 |
| [test_single_reactant_change_core_or_branch](../tests/test_reactions.py#L126) | 确认支链或母核差异都能在来源自回放后仅替换一个输入，并满足完整目标。 |
| [test_two_changes_and_unassigned_step_do_not_transfer](../tests/test_reactions.py#L142) | 确认需要同时改两个输入或来源未明确分步时不自动给出单输入迁移。 |
| [test_source_endpoint_conflict_is_not_a_validated_mapping](../tests/test_reactions.py#L154) | 确认映射端点不属于记录实际材料时不能作为已校验反应分析。 |
| [test_source_radius2_template_can_transfer_a_non_registry_reaction](../tests/test_reactions.py#L162) | 确认合法来源 radius-2 模板经自回放可生成注册酰胺规则以外的单输入建议。 |
| [test_replay_retains_product_sets_and_independent_enumeration_limit](../tests/test_reactions.py#L201) | 确认回放保留整组产品，并把结构有效和枚举截断分开。 |

## tests/test_recovery_isolation.py

| 函数 | 职责 |
|---|---|
| [test_corrupt_idempotency_binding_cannot_be_treated_as_a_new_request](../tests/test_recovery_isolation.py#L19) | 幂等文件中的任务编号损坏时明确报冲突，不能把空编号视为未绑定而重复创建任务。 |
| [test_malformed_idempotency_file_has_a_controlled_error](../tests/test_recovery_isolation.py#L35) | 非法 JSON 或错误对象类型应转换为统一冲突错误，不泄漏解析异常和类型异常。 |
| [test_api_rejects_corrupt_idempotency_binding_without_creating_run](../tests/test_recovery_isolation.py#L44) | 重试遇到损坏的幂等关联返回 409，不能再次接纳同一业务请求。 |
| [test_invalid_row_is_isolated_and_valid_rows_survive](../tests/test_recovery_isolation.py#L77) | 非法行类型和伪空数组必须记录问题，随后合法记录继续进入候选池。 |
| [test_optional_missing_or_null_source_fields_remain_supported](../tests/test_recovery_isolation.py#L92) | 可选字段缺失、显式 null 和合法空数组仍按既有来源约定接受。 |
| [running_state](../tests/test_recovery_isolation.py#L100) | 保存可正常恢复的运行中状态。 |
| [test_corrupt_run_is_reported_without_blocking_other_runs](../tests/test_recovery_isolation.py#L115) | 一个坏状态文件不能阻断另一有效任务的重启收尾，原坏文件保持原样。 |
| [test_unrelated_directory_does_not_participate_in_recovery](../tests/test_recovery_isolation.py#L135) | 运行根目录下的备忘或备份目录不是任务，不能因同名状态文件阻断启动。 |
| [test_corrupt_snapshot_does_not_block_terminal_recovery](../tests/test_recovery_isolation.py#L149) | 状态有效但阶段包损坏时仍能标记任务中断，明确快照不可读且不改写原坏文件。 |
| [test_health_reports_isolated_recovery_issues](../tests/test_recovery_isolation.py#L185) | 服务就绪响应应披露被隔离的旧任务，不能静默掩盖本地损坏。 |
| [test_real_storage_io_failure_still_blocks_startup](../tests/test_recovery_isolation.py#L201) | 真实权限或存储 I/O 错误不能当作单条数据损坏忽略，应明确阻止不可靠启动。 |
| [test_real_storage_io_failure_still_blocks_startup.unreadable](../tests/test_recovery_isolation.py#L206) | 模拟文件系统拒绝读取。 |

## tests/test_request_races.py

| 函数 | 职责 |
|---|---|
| [test_simultaneous_idempotent_submissions_create_only_one_run](../tests/test_request_races.py#L19) | 十二个线程同时使用同一幂等键，只能创建一个任务；不同请求必须明确冲突。 |
| [test_simultaneous_idempotent_submissions_create_only_one_run.held](../tests/test_request_races.py#L26) | 暂停唯一已接纳任务，防止完成速度影响并发提交验证。 |
| [test_simultaneous_idempotent_submissions_create_only_one_run.submit](../tests/test_request_races.py#L31) | 同时提交相同或冲突请求，保留结果与本次请求的对应关系。 |
| [test_shutdown_cancelled_wait_returns_terminal_before_release_callback](../tests/test_request_races.py#L59) | 关闭取消排队任务时，即使完成回调尚未执行，wait 也不能返回旧的 queued 状态。 |
| [test_shutdown_cancelled_wait_returns_terminal_before_release_callback.blocked](../tests/test_request_races.py#L71) | 占用唯一执行线程，使后一个任务确定地停在队列中。 |
| [test_shutdown_cancelled_wait_returns_terminal_before_release_callback.delayed_release](../tests/test_request_races.py#L77) | 暂停取消后的完成回调，暴露 Future 唤醒早于持久化终态的窗口。 |
| [test_shutdown_cancelled_wait_returns_terminal_before_release_callback.wait_for_run](../tests/test_request_races.py#L84) | 收集等待结果和异常，供主线程检查实际返回的生命周期。 |
| [test_shutdown_cancelled_wait_returns_terminal_before_release_callback.observed_result](../tests/test_request_races.py#L101) | 确认 wait 已取得 Future，并进入其正常等待路径。 |
| [test_submitted_request_is_detached_from_caller](../tests/test_request_races.py#L130) | 修改原请求或返回状态中的嵌套列表，都不能改变已经接纳的后台请求。 |
| [test_submitted_request_is_detached_from_caller.hold](../tests/test_request_races.py#L138) | 暂停工作线程，捕获外部修改之后实际执行所见的请求。 |
| [test_client_settings_are_detached_from_caller](../tests/test_request_races.py#L159) | 调用方修改传入 Settings 不能悄悄改变已有客户端的来源和执行配置。 |
| [test_api_auth_configuration_is_detached_from_caller](../tests/test_request_races.py#L168) | 外部复用配置对象并清空令牌时，已创建应用仍必须拒绝未认证请求。 |
| [test_api_readiness_uses_the_same_source_as_worker](../tests/test_request_races.py#L182) | 外部修改来源路径时，就绪探测仍须检查应用实际执行任务所用的原配置。 |
| [test_rerank_freezes_request_before_computation](../tests/test_request_races.py#L192) | 重排正在计算时外部改变请求列表，不能改变派生任务保存的实验要求。 |
| [test_rerank_freezes_request_before_computation.mutate_during_rank](../tests/test_request_races.py#L221) | 模拟另一调用方在排序过程中修改原请求，仍执行真实排序函数。 |
| [test_final_message_cannot_override_interrupt_during_receive](../tests/test_request_races.py#L234) | 结果在等待消息期间触及截止或收到取消时，不得绕过二次检查标记成功。 |
| [test_final_message_cannot_override_interrupt_during_receive.Channel.close](../tests/test_request_races.py#L266) | 端点关闭不影响本例的接收时序。 |
| [test_final_message_cannot_override_interrupt_during_receive.Process.start](../tests/test_request_races.py#L273) | 模拟已启动。 |
| [test_final_message_cannot_override_interrupt_during_receive.Process.is_alive](../tests/test_request_races.py#L277) | 结果已就绪，没有仍在运行的进程。 |
| [test_final_message_cannot_override_interrupt_during_receive.Process.close](../tests/test_request_races.py#L281) | 模拟句柄清理。 |
| [test_final_message_cannot_override_interrupt_during_receive.Context.Pipe](../tests/test_request_races.py#L288) | 构造独立收发端。 |
| [test_final_message_cannot_override_interrupt_during_receive.Context.Process](../tests/test_request_races.py#L292) | 提供不消耗真实时间的进程。 |
| [test_final_message_cannot_override_interrupt_during_receive.Messages.__init__](../tests/test_request_races.py#L299) | 兼容有界队列初始化。 |
| [test_final_message_cannot_override_interrupt_during_receive.Messages.get](../tests/test_request_races.py#L303) | 返回结果之前推进时钟或设置取消事件。 |
| [test_final_message_cannot_override_interrupt_during_receive.no_receiver](../tests/test_request_races.py#L311) | 本地队列已控制接收结果，不需要独立读取。 |

## tests/test_result_completeness.py

| 函数 | 职责 |
|---|---|
| [test_usage_status_respects_actual_evaluated_scope](../tests/test_result_completeness.py#L15) | 输入通道已读完但核验、来源范围或详情有缺口时，只能声明部分完成。 |
| [test_usage_status_respects_actual_evaluated_scope.Source.candidate_page](../tests/test_result_completeness.py#L36) | 返回已经耗尽的一页，可单独标记输入选择范围不完整。 |
| [test_usage_status_respects_actual_evaluated_scope.Source.hydrate](../tests/test_result_completeness.py#L47) | 按用例模拟详情失败，其余情况返回同一个完整材料记录。 |
| [test_material_relation_limit_only_marks_real_omission](../tests/test_result_completeness.py#L73) | 实际关联少于、恰好等于或超过默认上限时，只有确实遗漏关联才报告截断。 |

## tests/test_review_regressions.py

| 函数 | 职责 |
|---|---|
| [core_family](../tests/test_review_regressions.py#L37) | 构造只固定中心原子的查询，暴露重复支链与边界键约束问题。 |
| [reference_for](../tests/test_review_regressions.py#L51) | 构造仅用于证据和实验适配判断的产品参考，不虚构结构见证。 |
| [test_repeated_r_blocks_cover_the_same_target_completely](../tests/test_review_regressions.py#L67) | 同一核心外的重复甲基必须一一对应，目标自身的联合覆盖应为百分之百。 |
| [test_directed_r_constraints_preserve_multiplicity](../tests/test_review_regressions.py#L78) | 目标要求两个相同甲基时，只有一个甲基的候选不能重复使用同一支链满足条件。 |
| [test_alkyl_constraint_checks_the_attachment_bond](../tests/test_review_regressions.py#L87) | 烷基的核心连接键必须为单键，不能把双键或三键连接的碳误判为烷基。 |
| [test_enriched_outcome_cannot_override_conflicting_observations](../tests/test_review_regressions.py#L100) | 同一产品有富集与失败、普通回收或冲突证据时，不能计算合格获得命中。 |
| [test_dirty_material_does_not_hide_known_excluded_material](../tests/test_review_regressions.py#L122) | 某个材料解析失败时，仍须保留另一个已识别材料触发的明确禁用结论。 |
| [test_only_explicit_boolean_inventory_completeness_can_pass_exclusions](../tests/test_review_regressions.py#L140) | 自由元数据中的真值字符串、数字和容器不能冒充已确认的完整材料清单。 |
| [test_explicit_complete_inventory_still_passes_unmatched_exclusion](../tests/test_review_regressions.py#L148) | 明确的布尔完整标记和可识别清单仍可用于判断未出现被排除材料。 |
| [test_whitespace_input_citation_does_not_create_use_evidence](../tests/test_review_regressions.py#L156) | 只有空白字符的审核引用不能把未知投料升级为确认使用。 |
| [test_masking_uses_validated_products_and_skips_dirty_ones](../tests/test_review_regressions.py#L179) | 脏产品先于有效目标产品时，评测屏蔽仍应排除整条目标记录而非崩溃。 |
| [test_source_index_capability_uses_indexed_columns](../tests/test_review_regressions.py#L198) | 索引名称提到产品列不能冒充该列已建索引，必须匹配实际索引键列。 |
| [test_source_files_are_read_with_a_memory_bound](../tests/test_review_regressions.py#L212) | 来源和证据文件必须先限定读取字节数，不能把整个大文件读入内存后才检查大小。 |
| [test_source_files_are_read_with_a_memory_bound.BoundedReader.read](../tests/test_review_regressions.py#L220) | 允许在声明大小上限内读取并留出一个溢出哨兵字节。 |
| [test_source_files_are_read_with_a_memory_bound.open_file](../tests/test_review_regressions.py#L227) | 只替换被检查的输入路径，其余文件读取仍使用真实文件。 |
| [saved_running_package](../tests/test_review_regressions.py#L238) | 保存仍在运行但已有完整范围快照的任务，模拟发布包后进程异常退出。 |
| [test_restart_marks_retained_snapshot_partial](../tests/test_review_regressions.py#L262) | 重启恢复必须同步标记保留快照的范围和停止原因，并保留原快照不变。 |
| [test_supervisor_exception_marks_retained_snapshot_partial](../tests/test_review_regressions.py#L278) | 监督过程自身异常时，兜底失败处理也必须更新已经保存的快照范围。 |
| [test_supervisor_exception_marks_retained_snapshot_partial.fail_supervision](../tests/test_review_regressions.py#L285) | 模拟阶段包落盘后监督器自身发生异常。 |
| [test_non_ascii_authorization_is_rejected_without_server_error](../tests/test_review_regressions.py#L297) | 错误令牌包含非 ASCII 字符时应返回未认证，不能触发字符串比较的服务器异常。 |
| [test_rerank_succeeds_only_after_snapshot_is_saved](../tests/test_review_regressions.py#L306) | 重排必须在快照落盘后才标记成功；写盘失败时任务不能留下虚假的成功状态。 |
| [test_rerank_succeeds_only_after_snapshot_is_saved.save_snapshot](../tests/test_review_regressions.py#L318) | 记录落盘前的任务状态，并可模拟文件写入失败。 |
| [test_progress_snapshot_does_not_complete_unstarted_phases](../tests/test_review_regressions.py#L339) | 初始阶段包不能把尚未开始的输入检索或替换回放标记为已完成。 |

## tests/test_round1_chemistry.py

| 函数 | 职责 |
|---|---|
| [ring_family](../tests/test_round1_chemistry.py#L12) | 用完整苯环构造核心，并固定目标所有外围支链。 |
| [test_exact_r_preserves_double_bond_requirements](../tests/test_round1_chemistry.py#L29) | 精确支链要求指定双键构型时，反构型或未指定构型不能混入。 |
| [test_r_stereo_signature_is_invariant_to_hydrogens_and_atom_order](../tests/test_round1_chemistry.py#L40) | 加显式氢或改变局部原子编号后，同一支链的立体签名应保持一致。 |
| [test_exact_chiral_r_accepts_explicit_hydrogen_view](../tests/test_round1_chemistry.py#L54) | 精确四面体支链在显式氢视图下仍应匹配原目标，反构型仍被排除。 |

## tests/test_round2_reactions.py

| 函数 | 职责 |
|---|---|
| [graph_record](../tests/test_round2_reactions.py#L21) | 构造明确标记为合成示例的两侧图，用于验证图解释而非实验可行性。 |
| [test_unresolved_ring_changes_are_not_reported_as_retained](../tests/test_round2_reactions.py#L47) | 未映射区域或未跟踪片段涉及环变化时，不能宣称全反应保留环拓扑。 |
| [test_fully_mapped_unchanged_ring_is_retained](../tests/test_round2_reactions.py#L55) | 完整映射且环图不变时，仍可报告环拓扑保留。 |
| [test_projected_formation_must_be_an_actual_target_bond](../tests/test_round2_reactions.py#L68) | 来源成键投影必须在目标中存在且键型一致，宽泛核心匹配不能制造目标成键。 |
| [amide_reference](../tests/test_round2_reactions.py#L90) | 构造已有来源酰胺反应的最小回放参考。 |
| [test_failed_source_replays_consume_attempt_budget](../tests/test_round2_reactions.py#L104) | 自回放即使没有复现来源产物也必须计入尝试预算，不能无额度继续调用。 |
| [test_failed_source_replays_consume_attempt_budget.rules](../tests/test_round2_reactions.py#L108) | 提供只返回原输入、无法得到酰胺产物的受控规则。 |
| [test_documented_step_requires_nonblank_citation](../tests/test_round2_reactions.py#L121) | 步骤引用只有空白时，不能将记录校验为明确的单步反应。 |
| [test_transfer_rechecks_blank_step_citation](../tests/test_round2_reactions.py#L129) | 即使调用方通过复制构造了未重校验记录，回放仍应拒绝空白步骤引用。 |

## tests/test_round3_boundaries.py

| 函数 | 职责 |
|---|---|
| [overlay](../tests/test_round3_boundaries.py#L15) | 应用只包含调用方提供字段的审核补丁。 |
| [test_partial_input_review_preserves_existing_outcome_and_step](../tests/test_round3_boundaries.py#L28) | 仅审核实际输入时，已有产品观察和步骤依据不应被默认空值删除。 |
| [test_omitted_review_field_differs_from_explicit_clear](../tests/test_round3_boundaries.py#L52) | 未提供产品观察与明确清空观察是不同操作，内容和审核哈希都应体现区别。 |
| [reference](../tests/test_round3_boundaries.py#L64) | 构造方法和证据资格相同的参考，隔离操作条件对排序的影响。 |
| [test_inverted_temperature_range_is_not_a_capability_pass](../tests/test_round3_boundaries.py#L78) | 下限高于上限的来源温度范围不能被用于判定实验能力已满足。 |
| [test_invalid_conditions_do_not_receive_easy_operation_priority](../tests/test_round3_boundaries.py#L102) | 倒置温度和负时长应保持异常/未知，不得优于有完整可信数值的同等参考。 |
| [test_subzero_temperature_and_zero_duration_remain_valid](../tests/test_round3_boundaries.py#L129) | 正常低温和零时长不应被当作倒置范围或负时长处理。 |
| [test_constructor_failure_releases_coordinator_lock](../tests/test_round3_boundaries.py#L144) | 初始化异常被调用方保留时，目录锁仍需立即释放，允许修复后再次初始化。 |
| [test_constructor_failure_releases_coordinator_lock.fail](../tests/test_round3_boundaries.py#L148) | 模拟读取遗留状态时的初始化错误。 |
| [test_invalid_exclusion_is_rejected_before_creating_job](../tests/test_round3_boundaries.py#L161) | 无效排除结构必须在提交入口报错，不能先保存和调度一个必然失败的任务。 |
| [test_invalid_exclusion_is_rejected_before_creating_job.unexpected_submission](../tests/test_round3_boundaries.py#L165) | 一旦越过请求校验进入调度，立即暴露回归。 |
| [test_rerank_records_current_implementation_without_erasing_origin](../tests/test_round3_boundaries.py#L176) | 旧资料重排后须同时保留检索版本和本次排序版本，避免把新结果归给旧代码。 |

## tests/test_rule_validation.py

| 函数 | 职责 |
|---|---|
| [install_rules](../tests/test_rule_validation.py#L11) | 把受控回放规则写入临时资源根目录，保留其他已验证的规则配置。 |
| [test_duplicate_transfer_ids_are_rejected](../tests/test_rule_validation.py#L21) | 重复回放规则 ID 会混淆建议去重与来源追溯，必须在加载时拒绝。 |
| [test_transfer_arity_matches_single_target_runtime](../tests/test_rule_validation.py#L40) | 语法可编译但目标/输入数量不符合实际调用方式的规则不能被报告为有效。 |
| [test_multiple_forward_products_remain_supported](../tests/test_rule_validation.py#L51) | 单目标逆向回放并不要求正向只生成一个产物，合法副产物不能被错误禁止。 |
| [test_rule_validation_command_rejects_unsupported_replay](../tests/test_rule_validation.py#L64) | 命令行校验不能对运行时不支持的多目标逆向规则打印有效结果。 |

## tests/test_runtime_integrity.py

| 函数 | 职责 |
|---|---|
| [seed_run](../tests/test_runtime_integrity.py#L31) | 保存最小任务和资料包，隔离执行协议测试与化学计算。 |
| [test_submission_failure_leaves_no_queued_ghost](../tests/test_runtime_integrity.py#L58) | 幂等落盘或调度失败后，任务应结束为失败并清除内存登记。 |
| [test_submission_failure_leaves_no_queued_ghost.rejected](../tests/test_runtime_integrity.py#L64) | 模拟线程池拒绝任务。 |
| [test_submission_failure_leaves_no_queued_ghost.broken_binding](../tests/test_runtime_integrity.py#L68) | 只在写入幂等绑定时模拟失败，读取仍正常。 |
| [test_queued_cancel_frees_capacity_immediately](../tests/test_runtime_integrity.py#L93) | 一个任务占满执行线程时，另一个排队任务取消后应立即结束并释放接纳名额。 |
| [test_queued_cancel_frees_capacity_immediately.blocked](../tests/test_runtime_integrity.py#L99) | 占住唯一工作线程，直到测试明确释放。 |
| [test_default_wait_includes_queue_time](../tests/test_runtime_integrity.py#L120) | 默认等待不能使用独立于排队时长的固定 130 秒上限；显式上限仍传递。 |
| [test_default_wait_includes_queue_time.WaitingFuture.__init__](../tests/test_runtime_integrity.py#L128) | 保存观察到的等待上限。 |
| [test_default_wait_includes_queue_time.WaitingFuture.result](../tests/test_runtime_integrity.py#L132) | 记录调用方是否强加了隐藏等待上限。 |
| [test_atomic_write_failure_removes_temporary_file](../tests/test_runtime_integrity.py#L147) | 原子写失败应保留旧文件，并清除未发布的临时文件。 |
| [test_atomic_write_failure_removes_temporary_file.fail](../tests/test_runtime_integrity.py#L152) | 模拟替换或同步失败。 |
| [test_snapshot_identifier_is_validated_before_io](../tests/test_runtime_integrity.py#L164) | 读写快照都应在文件系统调用前拒绝非法或超长标识。 |
| [test_closed_client_cannot_write_reranked_run](../tests/test_runtime_integrity.py#L175) | 旧客户端关闭后不能越过新协调器的目录锁继续写重排结果。 |
| [test_close_waits_for_inflight_rerank](../tests/test_runtime_integrity.py#L186) | 同步重排尚未落盘时，关闭不能提前释放协调器锁。 |
| [test_close_waits_for_inflight_rerank.blocked_rank](../tests/test_runtime_integrity.py#L196) | 将重排暂停在持久化前。 |
| [test_close_waits_for_inflight_rerank.rerank](../tests/test_runtime_integrity.py#L202) | 在线程中执行重排并保存异常，供主测试检查。 |
| [test_close_waits_for_inflight_rerank.close](../tests/test_runtime_integrity.py#L209) | 通知测试已开始关闭，再等待关闭完成。 |
| [test_lifespan_exception_still_releases_resources](../tests/test_runtime_integrity.py#L233) | 应用生命周期因异常退出时，仍需关闭客户端并释放目录锁。 |
| [test_lifespan_exception_still_releases_resources.failing_lifespan](../tests/test_runtime_integrity.py#L237) | 模拟生命周期内部异常，而非普通 HTTP 业务错误。 |
| [TrackedChannel.__init__](../tests/test_runtime_integrity.py#L255) | 初始化未关闭状态。 |
| [TrackedChannel.close](../tests/test_runtime_integrity.py#L259) | 记录资源已释放。 |
| [TrackedChannel.cancel_join_thread](../tests/test_runtime_integrity.py#L263) | 兼容旧队列接口，使反例观察实际资源清理。 |
| [BrokenProcess.__init__](../tests/test_runtime_integrity.py#L271) | 记录尚未关闭的进程句柄。 |
| [BrokenProcess.start](../tests/test_runtime_integrity.py#L275) | 抛出受控启动失败。 |
| [BrokenProcess.is_alive](../tests/test_runtime_integrity.py#L279) | 失败启动没有存活进程。 |
| [BrokenProcess.close](../tests/test_runtime_integrity.py#L283) | 记录进程对象资源关闭。 |
| [BrokenContext.__init__](../tests/test_runtime_integrity.py#L291) | 保存实际分配的资源。 |
| [BrokenContext.Queue](../tests/test_runtime_integrity.py#L296) | 兼容旧实现的队列分配。 |
| [BrokenContext.Pipe](../tests/test_runtime_integrity.py#L302) | 创建两端独立的通信句柄替身。 |
| [BrokenContext.Process](../tests/test_runtime_integrity.py#L308) | 创建启动必然失败的进程替身。 |
| [test_process_start_failure_closes_allocated_resources](../tests/test_runtime_integrity.py#L316) | 配置或启动失败时，任务失败状态之外还必须关闭已分配通信与进程资源。 |
| [test_process_start_failure_closes_allocated_resources.bad_config](../tests/test_runtime_integrity.py#L326) | 模拟序列化配置构造失败。 |
| [partial_frame_worker](../tests/test_runtime_integrity.py#L337) | 发送消息头和不完整消息体后停住，模拟真实进程通信半包。 |
| [partial_frame_scenario](../tests/test_runtime_integrity.py#L346) | 在隔离进程中验证半包消息不能阻止硬超时；不执行化学检索。 |
| [test_incomplete_process_message_cannot_block_timeout](../tests/test_runtime_integrity.py#L360) | 真实管道只收到半包时，外层监督仍须按预算结束；测试自身另有进程级兜底。 |
| [test_cancelled_waiter_receives_terminal_state](../tests/test_runtime_integrity.py#L385) | 已经开始等待排队任务的调用方，应收到取消终态而非 Future 的取消异常。 |
| [test_cancelled_waiter_receives_terminal_state.blocked](../tests/test_runtime_integrity.py#L392) | 占住唯一工作线程，让第二个任务保持排队。 |
| [test_cancelled_waiter_receives_terminal_state.wait_for_run](../tests/test_runtime_integrity.py#L398) | 收集真实等待调用的返回或异常。 |
| [test_cancelled_waiter_receives_terminal_state.observed_result](../tests/test_runtime_integrity.py#L414) | 确认等待线程已捕获该 future，再允许主线程发起取消。 |
| [test_rerank_does_not_block_cancelling_other_job](../tests/test_runtime_integrity.py#L432) | 保护重排生命周期时不能持有全局协调锁做计算，从而阻塞另一任务的取消。 |
| [test_rerank_does_not_block_cancelling_other_job.running](../tests/test_runtime_integrity.py#L442) | 模拟会响应取消信号的运行中任务。 |
| [test_rerank_does_not_block_cancelling_other_job.blocked_rank](../tests/test_runtime_integrity.py#L448) | 暂时阻塞排序，让取消请求与同步写操作重叠。 |
| [test_rerank_does_not_block_cancelling_other_job.rerank](../tests/test_runtime_integrity.py#L454) | 捕获并发排序错误，确保测试不会忽略后台失败。 |
| [test_lifespan_cancellation_still_closes_client](../tests/test_runtime_integrity.py#L478) | 取消作用域已取消时，生命周期的清理仍须完整执行。 |
| [test_lifespan_cancellation_still_closes_client.cancelled_scope](../tests/test_runtime_integrity.py#L484) | 在应用生命周期内部取消作用域并交出控制权。 |
| [test_deadline_includes_process_startup](../tests/test_runtime_integrity.py#L500) | 启动准备已经耗尽预算时，即使结果已可读取，也不能获得额外运行时间。 |
| [test_deadline_includes_process_startup.ReadyChannel.recv](../tests/test_runtime_integrity.py#L511) | 返回最小结果包。 |
| [test_deadline_includes_process_startup.ReadyChannel.get](../tests/test_runtime_integrity.py#L515) | 兼容旧队列，确保反例源于预算起点。 |
| [test_deadline_includes_process_startup.SlowStart.start](../tests/test_runtime_integrity.py#L522) | 启动耗时超过当前预算。 |
| [test_deadline_includes_process_startup.SlowStart.join](../tests/test_runtime_integrity.py#L526) | 模拟已完成的进程等待。 |
| [test_deadline_includes_process_startup.ReadyContext.Queue](../tests/test_runtime_integrity.py#L533) | 为旧实现提供相同就绪结果。 |
| [test_deadline_includes_process_startup.ReadyContext.Pipe](../tests/test_runtime_integrity.py#L537) | 为当前实现提供收发端。 |
| [test_deadline_includes_process_startup.ReadyContext.Process](../tests/test_runtime_integrity.py#L541) | 返回慢启动对象。 |
| [test_receiver_stops_when_local_queue_is_full](../tests/test_runtime_integrity.py#L551) | 监督循环已结束时，接收线程不能因等待本地队列空位而泄漏。 |
| [large_result_worker](../tests/test_runtime_integrity.py#L577) | 生成大于管道缓冲区的完整消息后立即退出，验证末包不会因进程退出而丢失。 |
| [test_large_final_message_survives_worker_exit](../tests/test_runtime_integrity.py#L596) | 完整的大结果必须成功落盘，不能把正常进程退出误判为缺失结果。 |
| [test_closed_manager_rejects_even_an_existing_idempotency_key](../tests/test_runtime_integrity.py#L605) | 关闭后的提交入口不能因幂等缓存命中而绕过生命周期检查。 |

## tests/test_serialization_integrity.py

| 函数 | 职责 |
|---|---|
| [test_unserializable_native_metadata_is_isolated](../tests/test_serialization_integrity.py#L13) | 自由元数据中的非有限数和无效 Unicode 不得静默变值，也不能阻断下一条有效记录。 |
| [test_supported_native_metadata_survives_json_roundtrip](../tests/test_serialization_integrity.py#L31) | 有限数、大整数、中文及空值在合法原生记录的 JSON 往返后保持内容与摘要一致。 |

## tests/test_service.py

| 函数 | 职责 |
|---|---|
| [test_sdk_process_and_frozen_rerank](../tests/test_service.py#L16) | 确认 SDK 在独立进程检索后可对冻结候选重排，重排不能调用来源配置或重查。 |
| [test_single_coordinator_lock](../tests/test_service.py#L36) | 确认同运行目录只允许一个协调器，关闭后另一实例才可接管。 |
| [test_api_lifecycle_auth_idempotency_and_cursor](../tests/test_service.py#L44) | 确认真实 API 的认证、幂等、任务、固定快照分页、SVG/导出及严格重排输入。 |
| [test_cancel_stops_job_and_is_terminal](../tests/test_service.py#L107) | 确认取消返回已落盘的实际终态，迟到完成不能再修改状态。 |
| [test_supervisor_start_failure_does_not_leave_running](../tests/test_service.py#L116) | 确认监督器启动异常会落为 failed，不把作业永远留在 running。 |
| [test_restart_preserves_snapshot_and_fails_interrupted](../tests/test_service.py#L130) | 确认重启标记遗留运行失败并拒绝终态改写，不伪造恢复旧来源会话。 |
| [test_hard_timeout_is_terminal_and_subprocess_stops](../tests/test_service.py#L150) | 确认极短硬预算结束子进程并保持 timed_out 终态。 |

## tests/test_traceability.py

| 函数 | 职责 |
|---|---|
| [test_partial_review_preserves_unmodified_input_citations](../tests/test_traceability.py#L17) | 只更新产品观察或另一个输入时，已审核且未修改的底物引用必须保留。 |
| [test_absent_or_unrelated_citations_do_not_create_evidence_text](../tests/test_traceability.py#L58) | 缺失、旧格式或属于其他实例的引用保持未知，不把其他材料的引用填进当前结论。 |
| [test_observation_claim_keeps_its_specific_source_location](../tests/test_traceability.py#L67) | 观察的精确出处不能被整条来源记录的粗定位替换，原记录也不能被改写。 |
| [test_input_citations_survive_claim_and_summary_export](../tests/test_traceability.py#L85) | 已有审核输入引用应进入对应使用结论及模型摘要，不能被丢掉或串到另一底物上。 |
| [test_jsonl_error_line_uses_physical_file_location](../tests/test_traceability.py#L120) | 空白行可以忽略，但坏记录诊断行号必须指向文件中的实际位置。 |

## ../reviews/audit_reaction_snapshot.py

| 函数 | 职责 |
|---|---|
| [audit](../../reviews/audit_reaction_snapshot.py#L16) | 读取有限 JSONL 样本，检查字段、材料身份与份数、映射及模板自回放，返回计数和问题定位；不连接来源。 |
| [audit.record](../../reviews/audit_reaction_snapshot.py#L27) | 累计指定检查项的通过次数；失败时把来源记录编号加入对应问题列表。 |
| [audit.canon](../../reviews/audit_reaction_snapshot.py#L33) | 解析结构并移除映射号，返回保留立体的规范 SMILES；无效输入抛出 ValueError。 |

## ../reviews/check_acyclic_and_ring_changes.py

| 函数 | 职责 |
|---|---|
| [mol](../../reviews/check_acyclic_and_ring_changes.py#L9) | 将示例 SMILES 解析为 RDKit 分子；解析失败触发断言，返回有效分子。 |
| [bonds](../../reviews/check_acyclic_and_ring_changes.py#L14) | 返回按原子映射号对索引的键型字典，供受控示例比较端点图变化。 |
| [summary](../../reviews/check_acyclic_and_ring_changes.py#L18) | 返回重原子、键、组分和独立环数量，供无环与环变化示例比较。 |
| [changes](../../reviews/check_acyclic_and_ring_changes.py#L22) | 对受控的两侧映射图取键集合差，返回成键、断键和键级变化；不指认反应机理。 |
| [plain](../../reviews/check_acyclic_and_ring_changes.py#L27) | 复制分子并移除映射号，返回保留立体与同位素信息的规范结构字符串。 |

## ../reviews/check_attachment_methods.py

| 函数 | 职责 |
|---|---|
| [bond_set](../../reviews/check_attachment_methods.py#L14) | 返回按原子映射号对索引的键型字典，供受控示例比较端点图变化。 |
| [key](../../reviews/check_attachment_methods.py#L17) | 把从零开始的两个局部原子索引转为本例所用的正映射号，并排序为键对。 |
| [unmapped](../../reviews/check_attachment_methods.py#L20) | 复制分子并移除映射号，返回保留立体与同位素信息的规范结构字符串。 |

## ../reviews/check_chemical_edge_cases.py

| 函数 | 职责 |
|---|---|
| [mol](../../reviews/check_chemical_edge_cases.py#L11) | 将示例 SMILES 解析为 RDKit 分子；解析失败触发断言，返回有效分子。 |
| [scaffold](../../reviews/check_chemical_edge_cases.py#L16) | 提取示例分子的 Murcko 骨架并返回规范 SMILES，用于比较结构表示的差异。 |
| [add](../../reviews/check_chemical_edge_cases.py#L19) | 向当前报告追加一个带中文案例名称的结构检查结果。 |

## ../reviews/check_mapping_and_stereo.py

| 函数 | 职责 |
|---|---|
| [mol](../../reviews/check_mapping_and_stereo.py#L9) | 将示例 SMILES 解析为 RDKit 分子；解析失败触发断言，返回有效分子。 |
| [plain](../../reviews/check_mapping_and_stereo.py#L15) | 复制分子并移除映射号，返回保留立体与同位素信息的规范结构字符串。 |
| [bonds](../../reviews/check_mapping_and_stereo.py#L21) | 要求示例中所有原子的映射号为唯一正整数，再返回映射键对到键型的字典；不满足时抛出 ValueError。 |
| [edits](../../reviews/check_mapping_and_stereo.py#L30) | 比较两侧受控映射图，返回新成键、消失键和共同键的键级差异。 |
| [nuclear_signature](../../reviews/check_mapping_and_stereo.py#L101) | 返回固定映射下的元素、同位素、氢、自由基、连边及总电荷签名，用于核对共振示例。 |
| [controlled_resonance_forms](../../reviews/check_mapping_and_stereo.py#L111) | 有限枚举受控示例的共振形式，可统一芳香性；断言原子签名不变且未触及示例枚举上限。 |
| [charge_changes](../../reviews/check_mapping_and_stereo.py#L127) | 比较共同映射原子的形式电荷，返回发生变化的映射号及两侧电荷。 |

## ../reviews/check_markush_queries.py

| 函数 | 职责 |
|---|---|
| [mol](../../reviews/check_markush_queries.py#L9) | 将示例 SMILES 解析为 RDKit 分子；解析失败触发断言，返回有效分子。 |
| [evaluate](../../reviews/check_markush_queries.py#L33) | 核验示例核心与完整 R2 烷基组成、长度和连接边界，返回原始命中、家族命中及合法见证。 |
| [labeled_sites_match](../../reviews/check_markush_queries.py#L137) | 在一次固定苯环映射下核验指定位置外接 F 和 Cl，返回是否满足带位置标签的条件。 |
| [labeled_sites_match.exterior_symbols](../../reviews/check_markush_queries.py#L140) | 返回当前核心映射中指定位置所连接的核心外原子元素集合。 |

## ../reviews/check_reaction_relevance.py

| 函数 | 职责 |
|---|---|
| [mol](../../reviews/check_reaction_relevance.py#L10) | 将示例 SMILES 解析为 RDKit 分子；解析失败触发断言，返回有效分子。 |
| [boundary_components](../../reviews/check_reaction_relevance.py#L16) | 从核心外提取完整连通组分，返回各组分原子数及其连接核心的边界键。 |
| [bonds](../../reviews/check_reaction_relevance.py#L69) | 返回按原子映射号对索引的键型字典，供受控示例比较端点图变化。 |

## ../reviews/check_single_reactant_transfer.py

| 函数 | 职责 |
|---|---|
| [as_mol](../../reviews/check_single_reactant_transfer.py#L15) | 解析 SMILES 或复制已有分子，断言结构有效后返回，避免修改调用方对象。 |
| [canonical](../../reviews/check_single_reactant_transfer.py#L20) | 复制或解析结构、清除映射号，返回保留立体和同位素的规范 SMILES。 |
| [replay](../../reviews/check_single_reactant_transfer.py#L25) | 对两个示例输入执行有上限的反应回放，保留完整产物组与枚举状态；结构校验失败直接抛错。 |
| [contains](../../reviews/check_single_reactant_transfer.py#L41) | 判断某个完整产物组是否包含指定具体目标，返回布尔值；不合并不同组来凑目标。 |

## ../scripts/verify_environment.py

| 函数 | 职责 |
|---|---|
| [main](../../scripts/verify_environment.py#L39) | 核对 Python 与依赖、运行本地接口和化学检查、隔离渲染设计图，并将环境报告写入缓存目录。 |
| [main.smoke](../../scripts/verify_environment.py#L64) | 解析请求中的 SMILES，返回是否有效及原子数，仅供环境联调检查。 |
| [main.check_api](../../scripts/verify_environment.py#L72) | 使用内存 ASGI 客户端检查合法结构与错误字段类型的响应，受十秒异步超时限制。 |
