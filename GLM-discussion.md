正常一个合成化学家，是如何设计一个反应的？拿到一个确定的有机分子后，先检索scifinder吗，如果scifinder上没有检索到目标分子后应该怎么做？

# 化学家是怎么设计一个反应的：从文献检索到无路可走时的破局
**是的，你猜对了——绝大多数化学家拿到目标分子的第一件事就是打开 SciFinder 或 Reaxys 做结构检索，而不是马上画逆合成箭头。** 合成路线设计本质上是"先查、再想、实在没有再创造"的递归过程，MOSAIC 那 2,498 个专家想模仿的就是这套人类决策链。下面把真实的工作流和"查不到怎么办"的破局思路一次讲清楚。
## 一、真实工作流：数据库优先，而不是一上来就推逆合成
有经验的老化学家拿到一个目标结构，常规顺序大致是这样：
1. **画结构 → 直接查 SciFinder-n 或 Reaxys**,把目标作为"product"检索制备反应；同时拿 Registry Number、分子式、化学名交叉验证，避免命名歧义；
2. **同时查子结构/相似结构**：如果目标本身没报道，先看它的骨架有没有相似化合物(相似度阈值调低，或做子结构包含关系搜索)，相似的骨架往往能套用已发表的条件；
3. **Reaxys 和 SciFinder 各查一遍**——两者索引的期刊范围和收录规则不同，Reaxys 精度高、条件过滤强(可按收率、温度、溶剂、催化剂筛选)，SciFinder 对 1986 年以来有机反应的召回更广，做完整性检索两者缺一不可;
4. **顺手翻专利**(SciFinder 收录了海量专利反应)，很多中间体的工艺藏在专利而非期刊里;
5. **查完文献才轮到逆合成分析**：如果文献直接给了路线，就评估收率、条件是否温和、原料是否可及、总步数是否经济，稍作改良就开工；
6. **查不到完整路线，才开始真正意义上的"设计"**——进入逆合成思维。
也就是说，**文献检索是第一反应，逆合成分析是第二反应**。逆合成是被"没有现成答案"倒逼出来的创造性工作。
## 二、逆合成分析：化学家脑子里的基本套路
E. J. Corey 在 1960 年代提出逆合成方法论，到今天化学家脑子里跑的还是那几条核心启发式:
- **识别关键官能团**:羰基、胺、醇、杂环等是最天然的切断点，因为每个官能团都对应一整套成熟的构筑反应；
- **战略键切断**:优先断 C–X 杂原子键(比 C–C 容易重建)、优先在支链点断、优先把环从链上剥下来、利用分子对称性、把分子切成大小相近的两块；
- **官能团互变(FGI)**:如果目标官能团不方便直接构建，就在脑子里把它"假装"换成一个更容易形成的官能团——比如醇换卤代烃、羰基换烯烃、胺通过还原胺化间接引入；
- **合成等价物匹配**:切断后得到一个"合成子"(虚幻的带电片段)，再用真实试剂替换(比如负碳合成子换成格氏试剂或有机锂)；
- **收敛式合成优先**:从两条分支分别做到中间体再汇合，比一条直线做到底收率高、操作灵活；
- **向商品化原料收敛**：每一步切断都问一句"这个前体买得到吗？"——买得到就停，买不到就继续往回切。
这一套思路在化学家脑子里是几十年的肌肉记忆，在计算机里就被形式化成了 CASP(计算机辅助合成规划)——MOSAIC、Chematica、AiZynthFinder、Synthia 都属于这一脉。
## 三、SciFinder 上目标分子没报道时，怎么办？
这是这个问题最有实操价值的部分。**直接检索扑空并不罕见——天然产物新结构、药物候选的衍生物、杂环骨架变体、专利未覆盖的中间体都可能查不到现成路线。** 真实做法是分四层往下挖，按优先级推进：
### 策略 1:相似结构检索，借力骨架 analog
把目标的**子结构或相似度 70–90% 的类似物**再查一遍。类似物的合成路线中，90% 的骨架构筑步骤往往可以照搬，只需要在最后一步改官能团化。这是最高效的路径——相当于"用文献的 80% 自己补 20%"。
### 策略 2:逆合成切断，检索中间体而不是目标
对目标做 1–2 步切断，得到几个**关键中间体**，分别去数据库查这些中间体有没有报道：
- 如果中间体有路线 → 目标本身只差最后一步，补一个官能团化反应就闭环；
- 如果中间体也查不到 → 继续往回切，直到某一级中间体有报道或可购买。
这一步本质上是在数据库和自己的脑子之间**交替推进**，而不是一口气推到底。Reaxys 2026 年新加的 Predictive Retrosynthesis 就是在自动化这件事：预测路线遇到非商品化中间体时，自动接续文献报道过的合成步骤，把断掉的链条续上。
### 策略 3:Forward synthesis 思维 + 模块化拼装
从简单商品化原料出发，用**已知的、高可靠性的反应**(Suzuki、酰胺缩合、还原胺化、醛醇缩合、Diels-Alder 等)正向搭建。关键思路是：
- 把分子拆成几个**合成砌块**,每一块都从商品化原料出发用 1–2 步做成；
- 最后用一次高可靠性的**成键反应**把砌块连起来；
- 收敛式的两分支拼装往往比直线式推 8 步更省力。
这条路对复杂杂环、多取代芳环尤其有效——很多骨架就是靠"先搭杂环母核、再逐步官能团化"正向推出来的。
### 策略 4:AI/CASP 工具 + 化学直觉兜底
文献 + 人脑都不够时，把目标喂给 **CAS SciFinder 的 AI 逆合成预测**、**Reaxys Predictive Retrosynthesis**、**Synthia(CBA)**、**AiZynthFinder**(开源)、或者 ACS 上的 ICSYNTH 等工具。这些工具基于反应规则库或神经网络，能给出人类可能忽略的切断方案，但**每条建议都需要化学家人工把关**——位阻、稳定性、选择性、官能团相容性这些事模型会出错。
如果连 AI 都给不出可信路线，那就是硬仗，要靠化学家基于机理判断做**策略性创新**——换骨架策略、用重排反应、引入保护基调节选择性，或者干脆设计一条文献里从来没有过的新路线。
## 四、一张表：检索扑空后的决策树
| 情况 | 下一步动作 |
|---|---|
| 目标分子有报道 | 直接评估路线，微调条件开工 |
| 目标无报道、相似物有报道 | 借用类似物路线，改最后一步官能团化 |
| 相似物也没有 | 逆合成切断 1–2 步，分别查中间体 |
| 中间体有报道 | 补齐末端步骤闭环 |
| 中间体也没有 | 继续往回切，直到撞到商品化原料或已知中间体 |
| 一路都查不到 | Forward synthesis:商品化原料 + 可靠反应正向搭块 |
| 正向也推不通 | 用 CASP 工具(AiZynthFinder/Synthia/CAS 预测)提建议 |
| AI 也卡壳 | 机理判断 + 策略创新，人工设计全新路线 |
## 五、收尾时化学家还会做的几件事
无论哪条路推出来的路线，开工前都会再过一遍筛：
- **总步数与总收率**:8 步每步 80% 的总收率(17%)和 4 步每步 70% 的总收率(24%),后者实际更香；
- **原料可及性与价格**:Sigma-Aldrich、TCI、Combi-Blocks 是否有货、多少钱一克；
- **条件温和度**：是否需要 −78 °C、高压氢化、剧毒试剂(氰化物、CO)、易爆炸的叠氮化物——工艺化时这些全是雷；
- **官能团相容性**：底物上敏感基团(缩醛、酯、裸露胺)是否需要在某一步加保护；
- **手性问题**：消旋体要不要拆分？不对称催化还是手性源诱导？
---
把这套人类工作流跟上一轮聊的 MOSAIC 对照着看就很有意思：化学家"查 SciFinder 找类似物"的动作，在 MOSAIC 里变成了"用核度量网络在 Voronoi 空间里找最近邻专家"；"借类似物路线、改最后一步"的动作，对应"该专家基于它见过的专利反应，给出这条骨架的构筑方案"；而"AI 给出的建议要人工把关"这件事，MOSAIC 论文也没绕过——最终挑路线、判断位阻和选择性的还是人类化学家。**数据库 + 启发式切断 + 经验兜底**这三层结构，从 1960 年代 Corey 提出逆合成，到今天的大模型专家系统，底层逻辑没有变过。






如果数据库里没有骨架类似物的报道   那在这次合成中数据库就没有用了吗  拆分出来的中间体也没有报道

# 不是——数据库只是从“查分子”切换成了“查反应”
你抓到了那张图的一个简化失真：我把数据库的角色压缩成了“目标/类似物/中间体有没有报道”这种**结构检索**，所以看起来一旦结构全查不到，数据库就退场了。实际不是。**即使分子、类似物、中间体全都查不到，数据库依然是核心工具——只是查询对象从“分子”换成了“反应、转化、条件”。**
## 关键认知：合成化学是“局部化学”
逆合成切断的是**一个键**，重建它需要的先例不是“整个分子有人做过”，而是“**这一类键在类似的官能团环境下能不能形成**”。你的目标分子作为整体可能全世界没人碰过，但构成它的每一个键形成事件(成环、偶联、缩合、氧化)，几乎每一种都有成百上千条先例散落在别的分子上。数据库就是检索这些先例的工具。
## 数据库的六种用法(结构检索只是其一)
| 检索模式 | 回答的问题 | 图中的对应位置 |
|---|---|---|
| 精确结构检索 | 目标本身有没有报道 | ① |
| 子结构 / 相似度检索 | 有没有骨架类似物 | ② |
| **反应转化检索** ★ | "A 类片段 → B 类片段"这个转化有没有先例 | ③ 递归泵的每一步 |
| **条件 / 选择性挖掘** | 这个反应用什么溶剂、催化剂、温度？容忍哪些官能团？ | 选定转化后细化条件 |
| 商品化目录检索 | 这个"查不到"的中间体是不是其实有现货 | Q4"可购买?"的真实实现 |
| 性质 / 表征数据 | 熔点、NMR、MS——合成出来后对照验证 | 实验执行环节 |
**反应转化检索**就是那个被图省略的关键武器：Reaxys 和 SciFinder 都支持画一个“反应物子结构 → 产物子结构”的反应式，**忽略分子其余部分**去搜。比如你的中间体是个全新取代模式的三取代噁唑——没人做过这个具体分子——但你检索“α-卤代羰基化合物 + 酰胺 → 噁唑”这个转化，能翻出几千条先例，再按“底物带酯基/苄醚/卤素”过滤，挑出官能团相容的条件直接借来用。
## 把“全查不到”的场景真实走一遍
目标 T:精确检索无报道 ✓;骨架类似物无报道 ✓;切断后中间体 M:也无报道 ✓。此时化学家的动作不是把数据库关掉，而是：
1. **顺手查 M 有没有现货**——大量“文献查不到”的化合物其实在 Combi-Blocks、Enamine 这种库存化合物商那里一克几十美元；
2. **查“构筑 M 骨架的反应转化”**——M 是四取代呋喃？就检索 Feist–Bénary、Paal–Knorr 这类呋喃合成在类似取代模式下的先例，借条件；
3. **M 的环系本身是全新的？** 检索最接近的已知环系当年是怎么构筑的，做机理类比，迁移到你的体系；
4. **用反应检索逐条验证切断方案**：每切一个键就问数据库“这个键，在带这些官能团的底物上，有人用什么条件做成过？”——先例充足说明切断可靠，先例稀少说明这刀切在危险区，换个位置切。
所以图里那条 `Q5 无报道 → 回到 R1 继续切` 的回路，化学家走的时候手里始终握着数据库——**数据库不是递归循环外面的入口检查，而是递归每一步的可行性验证器**。这是那张图最该补上的一条线。
## 数据库真正“没辙”的极少数情况
只有当你要的反应类型在文献里**完全不存在**时(等于要发明新反应)，数据库才接近失效——比如某种全新骨架重排、前无古人的环化模式。这种事在全合成历史上偶有发生(Woodward、Corey 时代靠纸质文献和机理直觉硬啃)，但即便如此，新反应的设计依然靠数据库提供的**相邻机理类比**：类似试剂在其他底物上的行为、相邻反应类型的边界在哪。今天因为数据库覆盖了 200 多年的文献，“彻底无先例”比任何时代都罕见。
这也正是 CASP 软件的底层设计逻辑：Chematica 的规则库、MOSAIC 的 2,498 个专家、AiZynthFinder 的模板网络，形式化的都是“**局部转化先例**”这个概念——它们假设的恰恰是：分子级先例可以没有，键级/官能团级先例几乎永远存在。










怎么从已有本地数据库挖掘有价值的反应

# 从本地数据库挖有价值反应：核心思路
**一句话先立框架:反应挖掘的本质不是"把分子存进数据库",而是"把反应中心抽出来,用产率和条件做价值刻度,再按官能团环境聚类成可检索的先例库"。** 结构检索(上一轮讲的"查分子")只是这套库的最浅层用法,真正值钱的是键级/官能团级的先例检索。整条流水线是:**数据清洗 → 原子映射 → 反应中心提取 → 分类聚类 → 产率/条件挖掘 → 模板/先例库落地**。
## 一、先把"有价值"定义清楚
本地库里值钱的反应分四类,后面所有操作都是冲着它们去的:
| 价值类型 | 判定标准 | 用途 |
|---|---|---|
| **高产率先例** | 某类转化在库中收率 > 80% 且可重复 | 直接借用的"放心反应" |
| **官能团相容先例** | 底物带 X 官能团(比如裸露胺/醛/缩醛)时,该反应仍高收率 | 设计路线时的相容性预判 |
| **骨架构筑先例** | 某成环/成键方式在类似取代模式下的已知实例 | 全新骨架的逆合成依据 |
| **条件对照先例** | 同一转化在不同温度/溶剂/催化剂下的收率差 | 条件优化参考 |
## 二、数据准备:从"一坨文本"到"结构化反应表"
**起点几乎一定是脏的。** USPTO 最早那 1.8M 条是从 1976–2013 年专利全文里 NLP 抽取的,存在冗余条目、错误 SMILES、条件缺失等大量噪声。所以要做的第一件事是规整化:
- **格式统一**:把 ELN 导出、CSV、SDF 全部转成 `反应SMILES + 条件(温度/溶剂/试剂/催化剂) + 收率 + 产率表征` 的统一表格——其实这就是 MOSAIC 那个 DataFrame 的前身;
- **结构校验**:RDKit 逐条跑 `Chem.MolFromSmiles`,能 parse 的留,不能的丢弃;
- **反应平衡检查**:原子守恒(元素计数)、电荷守恒、无幽灵产物;
- **去重**:USPTO 类专利库有大量重复/近似重复(同一反应多专利),按反应 SMILES 规范化后去重;
- **条件字段的额外痛点**:USPTO 早期版收率字段覆盖不全,需要 NER(命名实体识别)从 `paragraphText` 里再抽温度/溶剂/当量——这正是 HazELNut 那套工具在药企 ELN 上做的事。
社区里现成的规整化产物可以直接拿来做参照:ORDerly、各种 curated USPTO 版本都处理过这些问题。
## 三、反应中心提取:整条流水线的地基
**这一步是反应挖掘的分水岭。** 关键工具是原子-原子映射:
1. **跑 RXNMapper**:用 IBM 的 transformer 模型,把反应 SMILES 里每个反应物原子标号,与产物原子对上。在 1,851 条人工标注的 Golden 测试集上,它的正确率约 83.74%,是各类 AAM 工具里最稳的一个(v2 在评估上又有改进);
2. **提取反应中心**:有了原子映射,对比反应物和产物的键变化——**哪些键断开、哪些键形成**,这就是反应中心。提取之后,反应 SMILES 里的"非参与"原子可以砍掉,得到只含反应中心的**模板**;
3. **模板 = 反应的抽象骨架**:模板分层级——保留 1 层相邻原子是"窄模板"(适用范围小、可靠性高),保留 0 层是"宽模板"(覆盖广、准确性差)。逆合成规划用的就是这套模板库。
没有原子映射,后面所有挖掘都退化为"盲人摸象式的全分子结构搜索";有了它,你才具备"键级检索"的能力。
## 四、分类与聚类:把库变成可导航的反应空间
原子映射和反应中心拿到后,做两件事:
- **规则分类**:用 **NameRXN** 这类基于 SMIRKS 词典的分类器,给每条反应打上"这个名字的反应"标签(Suzuki 偶联 / Paal–Knorr 环化 / 酯化…),同时关联 RXNO 本体。这是文本级检索的入口——你不用画结构,直接搜"Diels-Alder"就能拉出该类的所有实例;
- **指纹聚类**:用 **RXNFP**(IBM 的 BERT 基反应指纹,基于 Transformer attention 学出来的)把每条反应编码成向量,再做 tmap 可视化或直接做 K-means 层次聚类,把整个库自动切成几大类、几百小类,反应空间一目了然。MOSAIC 的 Voronoi 分区,本质上就是这条路线的进阶版(用核度量网络替代 RXNFP 相似度)。
## 五、挖掘动作:把"有价值的反应"筛出来
数据结构化 + 中心提取 + 分类聚类之后,挖掘动作才有的放矢:
1. **按价值维度切片**:在分类标签上叠条件过滤,比如"库中 Suzuki 偶联 + 催化剂 = Pd(dppf)Cl₂ + 溶剂 = dioxane"的收率分布;Reaxys 界面里那些"按收率、温度、催化剂过滤"的功能,本地库现在同样能做到;
2. **官能团相容性挖掘**:给库中反应物按 SMARTS 匹配官能团(裸露胺/醛/氰基/缩醛…),统计"该反应在带 X 官能团底物上的平均收率 vs 不带的",输出相容性表——这是设计新路线时最有用的"避雷图";
3. **类似物先例检索**(对应上一轮流程图的 ② 步):给一个目标,用 RDKit 算 Morgan 指纹,在库里做相似度/子结构搜索,找出骨架类似物的成键先例——**结构检索只是键级检索的入口形式之一**;
4. **逆合成模板提取**(对应 ③ 步):每个反应中心提取出的模板,按窄→宽分层入库,配上该模板下的所有实例反应及其条件,就构成了一个自建 Chematica 式的规则库;
5. **条件推荐**:拿某类转化 + 底物官能团组合,检索"历史最优条件"(收率 × 步数 × 条件温和度),可以直接喂给 MOSAIC 式的专家模型当训练监督信号,也可以作为人查表的速查手册。
## 六、给一个最小可跑的代码骨架
库里最基本的"反应中心 → 成键键对"的提取可以这么起步:
<details>
<summary>代码片段:RXNMapper + RDKit 提取反应中心</summary>
```python
from rxnmapper import RXNMapper
from rdkit import Chem
from rdkit.Chem import rdChemReactions
# 1. 原子映射
rxn_mapper = RXNMapper()
mapped = rxn_mapper.get_attention_guided_atom_maps(
    ["CC(=O)O.CN>>CC(=O)NC"])[0]['mapped_rxn']
# 2. RDKit 解析反应
rxn = rdChemReactions.ReactionFromSmarts(
    mapped, useSmiles=True)
# 3. 遍历键,找出反应中心(变化的键)
#   —— 断键: 在反应物有、产物没有
#   —— 成键: 在产物有、反应物没有
# 核心逻辑:利用 atom map number 对齐原子,比较键集合差异
# (rdkit.Chem.rdChemReactions 有现成 API 可进一步提取模板)
```
</details>
上面这一小段,就是整条"键级检索"流水线里最小、但最核心的一环——**有了成键/断键键对的标注,每条反应才从"分子描述"变成"反应描述"。**
## 七、落地形态:挖出来之后怎么用
从本地库挖出的价值,最终三种形态:
- **类似物路线推荐库**(② 步的加速):目标分子相似度检索 + 类似反应条件包;
- **条件推荐速查表**(⑤ 步的对照):按反应类别 + 官能团环境索引的"历史最优条件";
- **自建模板库 → 逆合成规划输入**(③ 步的落点):模板 + 实例 + 条件三合一,可喂给 AiZynthFinder 这类开源工具,或干脆作为 MOSAIC 式微调模型的训练素材。
---
把整条链和上一轮那个流程图对起来看就一目了然:**反应挖掘的产物,正是流程图里"② 相似结构检索"、"Q5 中间体有没有文献"以及"反应转化有没有先例"这三个判断节点的真正支撑。** 数据库里没有目标分子不等于没有用——只要库被挖过、反应中心被抽出来过,"键级先例"就永远在那儿。而这一切的地基,是原子-原子映射这一步看似枯燥的标注工作。








# 用 PGSQL + RDKit Cartridge 复刻化学家的检索决策链
**整体思路先立起来:数据库要建三张表(产物分子表、反应表、指纹表),检索程序的本质是把人类流程图里的 5 个决策节点逐一翻译成 SQL,Python 只做“先查哪个、查不到就降级到哪个”的编排器。** 核心操作符就三个:`@>`(子结构)、`@=`(完全匹配)、`<%>`(相似度排序)——人类的“精确检索 → 相似结构 → 子结构 → 反应转化”四级降级,全部靠它们组合实现。
## 一、数据库层:三张表把“分子”和“反应”分开存
化学家脑子里“查分子”和“查反应”是两个动作,数据库也该分开建:
```sql
create extension if not exists rdkit;
-- ① 产物分子表(结构检索的主战场)
create table products (
    id        serial primary key,
    smiles    text,
    m         mol,              -- mol 对象,挂 GiST 索引后可做子结构
    inchikey  text              -- 精确匹配的文本级兜底
);
create index molidx on products using gist(m);
create index inchikey_idx on products(inchikey);
-- ② 反应表(键级/转化检索的主战场)
create table reactions (
    id            serial primary key,
    rxn_smiles    text,          -- 反应物>>产物的完整 SMILES
    product_id    int references products(id),
    conditions    jsonb,         -- {溶剂, 催化剂, 温度, 产率}
    paragraph_text text,         -- 实验步骤文本
    namerxn_label text           -- 反应类型分类标签
);
-- ③ 指纹表(相似度/预筛)
select id, m,
       morganbv_fp(m)  as mfp2,     -- Morgan 位向量,相似度主力
       rdkit_fp(m)     as sfp,      -- RDKit 路径指纹,相似度备选
       torsionsbv_fp(m) as ttbv
into product_fps from products;
create index mfp2_idx on product_fps using gist(mfp2);
create index sfp_idx  on product_fps using gist(sfp);
```
`mol`、`bfp` 都挂 GiST 索引,子结构和相似度检索就能走索引而不是全表扫。100 万级分子在这个结构下子结构查询是几百毫秒量级。
## 二、核心操作符速查(全部程序逻辑的地基)
| 人类动作 | SQL 操作符 | 用途 | 性能特征 |
|---|---|---|---|
| "这个分子是不是就是它" | `mol @= mol` 或 InChIKey 文本比对 | 完全匹配 | InChIKey 走 B-tree,最快 |
| "含不含这个骨架" | `qmol @> mol`(query 在左,库在右) | 子结构 | GiST 索引 + pattern fp 预筛,快 |
| "长得像不像" | `morganbv_fp(q) <%> mfp2` | 相似度排序 | GiST 排序索引,百万级毫秒级 |
| "相似度 > 0.7" | `morganbv_fp(q) % mfp2` | 阈值过滤 | 同上 |
有一个坑要提前知道:**子结构操作符左边是 query(SMILES/SMARTS),右边是库里的分子**,方向写反了会得到"库分子是查询的子结构"这种镜像结果。子结构在 SMILES 查询时不需要 SMARTS 语法,SMARTS 主要用来做官能团环境约束(比如"苯环上必须带一个裸卤素")。
## 三、人类流程图的 5 个决策节点 → SQL 的直接映射
这是这套程序的核心,把上一轮流程图里每个数据库调用点逐一落地:
| 流程图节点 | 人类问题 | 程序动作 | 关键 SQL |
|---|---|---|---|
| ① 精确检索 | "目标分子有人做过吗?" | InChIKey 直查 + `@=` 双保险 | `where inchikey = $1` |
| ② 相似结构 | "有没有类似物?" | Morgan 相似度 Tanimoto,**0.7–0.9 是人类"骨架类似物"的经验区间** | `mfp2 <%> $1 limit 200` |
| ③ 子结构检索 | "有没有含我这个骨架的?" | 目标砍掉末端官能团 → SMARTS/SMILES 子结构 | `m @> $1` |
| R2v 键级先例 | "这一刀切下去,这个键有先例吗?" | 产物端画 SMARTS(含反应中心环境),反应表 join 产物表 | `p.m @> $1` 再 join reactions |
| ⑤ 条件挖掘 | "这反应该用什么条件?" | namerxn_label + 官能团环境过滤 | jsonb 字段条件聚合 |
**相似度阈值 0.7–0.9 不是拍脑袋的数字**——这是 Tanimoto 相似度在 Morgan 指纹上对应"肉眼可辨骨架类似物"的经验范围,低于 0.6 会大量命中只共享小片段(比如苯环)的假阳性,高于 0.95 就只剩近同物。程序里应该允许按返回条数动态放宽:先 0.85,命中 < 5 条就降到 0.7。
## 四、完整自动化检索程序(Python 编排器)
程序骨架分两层:SQL 检索函数层(纯查询,无逻辑)+ 决策流水线层(复刻人类"查不到就降级"的思路)。用 `psycopg2` 连库,RDKit 在 Python 端做 SMILES 规范化和 SMARTS 生成:
```python
import psycopg2
from psycopg2.extras import RealDictCursor
from rdkit import Chem
from rdkit.Chem import rdFMCS
import networkx as nx
class ChemistSearchEngine:
    """复刻人类数据库检索决策链的自动检索器"""
    def __init__(self, dsn="postgresql://user:pass@localhost/reactiondb"):
        self.conn = psycopg2.connect(dsn)
        self.cur = self.conn.cursor(cursor_factory=RealDictCursor)
        # 相似度阈值按人类"类似物"经验区间设定
        self.sim_thresholds = [0.9, 0.8, 0.7]  # 逐级放宽
    # ---------- 检索原语层(SQL 直翻)----------
    def exact_match(self, smiles):
        """① 精确检索:InChIKey + @= 双保险"""
        inchikey = Chem.MolToInchiKey(Chem.MolFromSmiles(smiles))
        self.cur.execute("""
            select p.id, p.smiles, r.id as rxn_id,
                   r.conditions, r.paragraph_text
              from products p
              left join reactions r on r.product_id = p.id
             where p.inchikey = %s
        """, (inchikey,))
        return self.cur.fetchall()
    def similarity_search(self, smiles, top_n=200):
        """② 相似结构:逐级放宽阈值,复刻人类『没有就看得更粗』"""
        for th in self.sim_thresholds:
            self.cur.execute("""
                select p.id, p.smiles,
                       tanimoto_sml(morganbv_fp(mol_from_smiles(%s::cstring)),
                                    f.mfp2) as sim,
                       r.conditions
                  from product_fps f
                  join products p on p.id = f.id
                  left join reactions r on r.product_id = p.id
                 where morganbv_fp(mol_from_smiles(%s::cstring)) <%> f.mfp2
                 order by morganbv_fp(mol_from_smiles(%s::cstring)) <%> f.mfp2
                 limit %s
            """, (smiles, smiles, smiles, top_n))
            hits = self.cur.fetchall()
            if len(hits) >= 5:
                return hits, th  # 命中足够就停,返回当前阈值
        return hits, self.sim_thresholds[-1]
    def substructure_search(self, sub_smiles, top_n=500):
        """③ 子结构检索:目标分子砍掉末端官能团后当 query"""
        self.cur.execute("""
            select p.id, p.smiles, r.conditions, r.paragraph_text
              from products p
              left join reactions r on r.product_id = p.id
             where p.m @> mol_from_smiles(%s::cstring)
             limit %s
        """, (sub_smiles, top_n))
        return self.cur.fetchall()
    def reaction_transformation_search(self, product_smarts, fg_env=None):
        """R2v 键级先例检索:含反应中心环境的产物端 SMARTS,
           借 products 子结构索引再 join reactions 表"""
        sql = """
            select r.id, r.rxn_smiles, r.conditions, r.namerxn_label
              from reactions r
              join products p on p.id = r.product_id
             where p.m @> qmol_from_smarts(%s::cstring)
        """
        params = [product_smarts]
        if fg_env:  # 官能团环境过滤(比如必须带酯基)
            sql += " and p.m @> qmol_from_smarts(%s::cstring)"
            params.append(fg_env)
        self.cur.execute(sql, tuple(params))
        return self.cur.fetchall()
    # ---------- 决策流水线层(复刻人类降级逻辑)----------
    def retrosynthesis_pipeline(self, target_smiles):
        """给定目标分子,自动走 ①→②→R2v 递归"""
        result = {"target": target_smiles}
        # 步骤①:精确检索
        exact = self.exact_match(target_smiles)
        if exact:
            result["route"] = "文献直接命中"
            result["hits"] = exact
            return result
        # 步骤②:相似结构降级
        sim_hits, threshold = self.similarity_search(target_smiles)
        if sim_hits:
            result["route"] = f"类似物借路(sim>={threshold})"
            result["hits"] = sim_hits
            # 类似物的反应条件包就是『借路线』的素材
            return result
        # 步骤③:子结构降级(目标砍末端官能团)
        core = self.strip_terminal_fgs(target_smiles)
        sub_hits = self.substructure_search(core)
        if sub_hits:
            result["route"] = "骨架子结构命中"
            result["hits"] = sub_hits
            return result
        # 步骤 R2v:进入键级先例递归
        result["route"] = "需逆合成键级检索"
        result["hits"] = self.recurse_disconnections(target_smiles)
        return result
    def strip_terminal_fgs(self, smiles):
        """简单版:去掉末端可变官能团,保留骨架。
        实际应该用 BRICS/MCS 而不是简单去氢"""
        mol = Chem.MolFromSmiles(smiles)
        # ... 实现末端官能团剥离
        return Chem.MolToSmiles(mol)
    def recurse_disconnections(self, target_smiles, max_depth=3):
        """R2v:每次切一刀,先查该键的先例,有就停,没有就回切"""
        queue = [(target_smiles, 0)]
        results = []
        while queue:
            smiles, depth = queue.pop(0)
            if depth > max_depth:
                continue
            for cut in self.generate_strategic_cuts(smiles):
                # 切出来一片,用反应中心 SMARTS 查先例
                smarts = self.cut_to_reaction_smarts(cut)
                precedents = self.reaction_transformation_search(smarts)
                if precedents:
                    results.append({
                        "cut": cut, "smarts": smarts,
                        "precedents": precedents
                    })
                    # 先例充足就不再深挖该分支(『买得到就停』原则)
                    if len(precedents) >= 3:
                        continue
                # 先例不足,该前体入队继续回切
                queue.append((cut[0], depth + 1))
        return results
```
## 五、工程细节:几个决定成败的点
1. **子结构必须先过 pattern fp 预筛**。子结构在 GiST 索引上内部已经走 pattern 指纹预筛,benchmark 数据显示 rdcart 的 pattern fp 屏除率 97.95%,可以把 100 万分子筛到 2 万再走精确匹配。所以 `m` 列的 GiST 索引不是可选项,是必须项;
2. **反应表的"键级检索"是绕道产物表实现的**。RDKit Cartridge 没有原生 `rxn` 类型(RXNMapper 的映射在 Python 端做,存到 `rxn_smiles` 字段)。程序的做法是:把反应中心环境画成产物端 SMARTS(比如"[C:1](=O)[N:2]"表示酰胺键),用 `p.m @> qmol_from_smarts(...)` 借产物表的子结构索引,再 join 回反应表拿条件——**这就是复刻 R2v"这一刀切下去有先例吗"的实现机制**;
3. **相似度函数一定要 `STABLE` 声明**。 cartridge 文档的官方模板是把相似度搜索包成 SQL 函数(`get_mfp2_neighbors`),`language sql stable`,让 planner 走索引扫描。裸写查询用 `<%>` 操作符也可以,但函数化后更适合程序调用;
4. **`paragraph_text`/`conditions` 用 jsonb 而不是 text**。后面要做"条件挖掘"(⑤ 节点,比如"这类反应历史上用 Pd(dppf)Cl₂ 时的平均收率"),jsonb 才能直接 `jsonb_array_elements` 聚合统计,text 就要再写一层解析;
5. **检索结果要做 reranker**。数据库返回的相似度只是数值排序,人类看类似物时会优先看"官能团环境相同"的而不是 Tanimoto 最高的。程序最后加一步:对 top hits 用 RDKit 算官能团指纹(`rgroupFP` 或裸 SMARTS 匹配),按"官能团环境一致性"重排序——这是把"人类直觉"翻译成代码的最后一公里。
## 六、一个可以直接跑的 SQL 函数(官方推荐写法)
把相似度搜索包成函数,复刻"查不到就降级"的单步逻辑:
```sql
create or replace function find_analogs(
    query_smiles text,
    min_sim double precision default 0.7
)
returns table(id bigint, smiles text, sim double precision,
              conditions jsonb, paragraph_text text) as
$$
    select p.id, p.smiles,
           tanimoto_sml(morganbv_fp(mol_from_smiles(query_smiles::cstring)),
                        f.mfp2) as sim,
           r.conditions, r.paragraph_text
      from product_fps f
      join products p on p.id = f.id
      left join reactions r on r.product_id = p.id
     where morganbv_fp(mol_from_smiles(query_smiles::cstring)) % f.mfp2
       and tanimoto_sml(morganbv_fp(mol_from_smiles(query_smiles::cstring)),
                        f.mfp2) >= min_sim
     order by sim desc
$$ language sql stable;
```
调用就是 `select * from find_analogs('CC(=O)Nc1ccccc1', 0.8);`,Python 端只需传参,不用拼 SQL 字符串。
---
**整个系统的本质:三张表(分子/反应/指纹)+ 三个操作符(`@>`、`@=`、`<%>`)+ 一个降级编排器,就是把人类"精确 → 相似 → 子结构 → 键级先例"的肌肉记忆翻译成代码。** 上一轮流程图里的每个数据库调用点——分子级(①②Q5)、键级(R2v)、条件挖掘(⑤)、现货采购(Q4,可另建一张商品目录表同样模式处理)——在这套架构里都有精确的对应物。人类查 SciFinder 时脑子里跑的降级逻辑,现在变成 `if not hits: threshold -= 0.1` 这种可优化的代码。
