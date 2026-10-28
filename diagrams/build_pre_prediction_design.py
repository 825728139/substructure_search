"""Render the current Markush-first retrieval and reference-evaluation design."""
from pathlib import Path
import subprocess
ROOT = Path(__file__).resolve().parent

BASE = '''
graph [rankdir=TB, bgcolor="#F8FAFC", pad="0.4", nodesep="0.40", ranksep="0.46", fontname="Noto Sans CJK SC", fontsize=22, labelloc=t];
node [shape=box, style="rounded,filled", fillcolor="white", color="#CAD5E2", fontcolor="#172D45", fontname="Noto Sans CJK SC", fontsize=14, margin="0.20,0.14"];
edge [color="#72849B", arrowsize=0.7, fontname="Noto Sans CJK SC", fontsize=11, fontcolor="#526477"];
'''

MAIN = '''digraph G {
BASE
label="先完成三层化学检索，再交给模型预测";
a [label="用户输入完整目标分子
自动生成结构与检索任务", fillcolor="#DBEAFE"];
b [label="三层默认生成 Markush 家族与目标位点对应
固定重要结构/官能团 + 可变 R；完整身份并行补查
互变异构 / 母体 / 可能保护形式 / 限定官能团变化"];
g [label="① 整体结构/骨架与相关形式", fillcolor="#D6F0E5"];
c [label="② 环系或链式核心与支链", fillcolor="#D6F0E5"];
f [label="③ 局部结构与片段参考", fillcolor="#D6F0E5"];
g1 [label="固定主要框架与必要功能单元
外围多 R 家族召回，严格身份另核验
真实支链组合与目标差异保留"];
c1 [label="固定核心、多 R 位点联合匹配
必要约束硬核验，其他支链保持可变
位点存在 / 引入 / 保留与真实共存"];
f1 [label="真实局部片段与连接环境召回
关联不同实际产物及其反应集合
必要时有预算补查实际输入侧的使用资料
不因目标无环跳过链式结构查询"];
g2 [label="整体类似物与实际底物
结构关系、转化方向与位点环境分组
真实正向关系不由反向记录代替"];
c2 [label="互补实例与反应证据矩阵
同一实例共存 / 分别出现 / 未知
实际共同前体、保护状态与已有顺序"];
f2 [label="具体参考分子与真实连接端
端基类别、位置、配对组分与出处
来源实例份数、各键证据及未覆盖问题"];
roles [label="先核对实验阶段、样品身份与实际结果
制备 / 拆分富集 / 普通回收 / 分析 / 预期失败
输入侧命中单列使用证据，不倒转为制备
结构、测量与条件对应阶段；零键变化不直接删除", fillcolor="#EAE0F7"];
quality [label="参考反应的化学相关性与有限补查
各键映射：形式检查 / 已检结论稳定性 / 化学支持
底物多份实例、手性来源、方向与条件关系
共同中间体及最多两条已有关系；缺失信息不补造"];
stats [label="骨架数量与化学覆盖分开统计
父候选 / 实际视图任务 / 目标位置
制备 / 富集获得 / 获得并集 / 分析 / 使用分账
化合物种类与实例份数分开，推定与确认分开", fillcolor="#EAE0F7"];
pack [label="模型预测前的参考资料包
三层实例、反应与底物、规则和原子对应
构筑或获得方式、阶段证据、目标差异与未知项
摘要超长时减少条目，结论与限制语一起保留"];
model [label="此时才调用模型
考虑局部修饰、支链组合与战略切断
结合参考资料设计目标合成方案", fillcolor="#DBEAFE"];
input_scope [label="确认具体目标与组分范围
具体结构、完整组分和通式分别处理
主体不明时保留边界，不拼接伪共存"];
a -> input_scope -> b;
compiled [label="优先采用 Markush 多位点联合查询
不预设目标开/闭环位置，不枚举虚拟环前体
逐视图显式编译查询
只固定必要元素/功能单元/位置，非关键支链放宽
明确保留/放开属性，按任务采用包含或身份判据"];
b -> compiled; compiled -> g; compiled -> c; compiled -> f;
g -> g1 -> g2;
c -> c1 -> c2;
f -> f1 -> f2;
g2 -> roles; c2 -> roles; f2 -> roles;
attachment [label="必经：目标母核—支链连接方法判定
实际反应类型、目标位点、边界键本步是否形成
核心底物、支链供体、反应端与迁移差异
完整接入 / 局部类比 / 支链转化 / 其他修饰 / 未知", fillcolor="#D6F0E5"];
transfer [label="有来源约束的单反应物替换类比
目标差异 → 母核/支链底物槽位 → 拟替代结构
原变化保持？完整目标能否回放？条件有什么依据？
规则推定单独输出，不冒充已报道反应", fillcolor="#D6F0E5"];
topology_assessment [label="已有反应分析后重排
核验源反应的开环 / 闭环 / 重组 / 环保留
变化是否对应目标相关区域？其他位置变化不冒充方法
三层命中都参与，排序不能找回未召回记录", fillcolor="#D6F0E5"];
ranking [label="独立过滤与双视角重排
方法参考价值：贡献、证据、迁移与目标覆盖
实验适配：材料、操作、危险信息、分离与规模
未知不能当低负担；明确限制不能被高收率抵消", fillcolor="#EAE0F7"];
roles -> attachment -> topology_assessment -> quality -> transfer -> stats -> ranking -> pack -> model;
}
'''

CHEMISTRY = '''digraph G {
BASE
label="化学召回：严格结构与相关形式分别处理";
a [label="原始目标与原始参考分子
保留组分、样品组成、立体/同位素与原子对应", fillcolor="#DBEAFE"];
b [label="统一解析与芳香性表达
按经校验规则生成比较视图
每个视图记录适用范围、来源与被修改部分"];
exact_view [label="严格结构
元素、键、连接与身份条件
指定立体与标记要求逐项检查", fillcolor="#D6F0E5"];
state [label="互变异构 / 母体关系
比较实际匹配的化学形式
保留原有盐组分与电荷", fillcolor="#D6F0E5"];
protect [label="可能的保护形式
如 Cbz 导致额外芳环
按连接环境生成兼容比较视图", fillcolor="#D6F0E5"];
fg [label="限定官能团变化
如环酮与环醇
仅放宽规则指定的局部结构", fillcolor="#D6F0E5"];
match [label="逐视图显式编译电荷、氢数和组分约束
独立筛选，按任务复核核心包含或完整身份
不能先用严格筛选排除扩展候选
目标与参考在相同语义下比较"];
back [label="映射回真实记录
原始分子 + 位点 + 样品阶段 + 实验结果与差异
虚拟视图不冒充已报道分子或反应前体"];
stereo [label="立体与同位素要求分别检查
符合 / 冲突 / 部分缺失 / 未评估
目标未约束位置保留来源取值，记录身份另判
同时记录手性继承 / 建立 / 拆分富集 / 未知
未知手性不等于外消旋；显式标记不能丢弃"];
direction [label="结构相关之后再核对转化方向
实际正向记录 / 同向类比 / 仅反向 / 结构线索
虚拟视图不是已报道的可转化路线"];
count [label="结果合并但语义保留
一个父候选可有多个视图；分子与反应去重
严格命中、扩展命中和各任务状态分别报告", fillcolor="#EAE0F7"];
bound [label="自动处理边界
不无条件删除所有苄基、酯或金属组分
多点保护保留整体连接；组合视图受规则与预算限制
转换关系不等于已有可行转换路线", fillcolor="#FFF3D6"];
a -> b;
b -> exact_view; b -> state; b -> protect; b -> fg;
exact_view -> match; state -> match; protect -> match; fg -> match;
match -> back -> stereo -> direction -> count -> bound;
}
'''

CORE = '''digraph G {
BASE
label="支链互补：位点证据与真实共同中间体";
a [label="目标头部 — 共同核心 — 目标尾部
位点由目标连接关系定义，支持多个位点", fillcolor="#DBEAFE"];
b [label="自动生成多位点 Markush 家族
必要核心/官能团固定，非关键外围作为 R
一次检索多种实际支链与组合，避免全量枚举"];
c [label="统一全核心映射与完整 R 谓词核验
对称位点一致对应；多点连接按联合块比较
不能为每条支链分别挑选互相冲突的映射"];
x [label="实例甲覆盖目标头部
实际产物与底物、保护状态、立体信息
头部是本步形成还是此前已经存在？", fillcolor="#D6F0E5"];
y [label="实例乙覆盖目标尾部
实际产物与底物、保护状态、立体信息
形成尾部时是否已有头部并被保留？", fillcolor="#D6F0E5"];
m [label="实例 × 目标位点的双层矩阵
结构：严格相同 / 局部相近 / 不同 / 未知
证据：产物存在 / 本步引入 / 他处反应时保留
每格附实际结果、阶段及局部映射支持范围", fillcolor="#EAE0F7"];
precursor [label="寻找实际共同中间体
核对完整结构、样品组成、保护、立体与阶段
共同底物 → 真实反应甲/乙 → 各参考产物
不同位点 / 竞争同一位点 / 对称歧义分别标注", fillcolor="#EAE0F7"];
co [label="联合位点与共存检查
同一实例共存 / 不同实例分别覆盖 / 冲突 / 未知
逐位点并集与单套映射的联合覆盖分别统计
同来源的替代映射不能拼成一套共存证据
相同桥链或环状保护单元不能拆成独立支链
同时比较共轭、邻位拥挤、竞争及条件差异
手性符合目标，不等于本步建立了目标手性"];
set [label="选择少量互补参考组合
先检查映射与联合约束，再比较覆盖与多样性
分别保留共存支持和仅独立覆盖的参考
限制组合数量，未知证据不当作成功或失败"];
out [label="交给模型的参考
共同核心、位点覆盖、存在/引入/保留证据
实际共同底物、位点环境、反应条件与已报道顺序
组合是否可行及具体路线由模型进一步分析", fillcolor="#DBEAFE"];
a -> b -> c;
c -> x; c -> y;
x -> m; y -> m;
methods [label="逐位点判断引入方法
目标支链是否在本步接到对应母核位置？
边界新形成还是已有？实际用了哪些母核与支链底物？
连接方法资格先于整体相似度排序", fillcolor="#D6F0E5"];
m -> methods -> precursor -> co -> set -> out;
}
'''

FRAGMENT = '''digraph G {
BASE
label="局部与支链检索：在已有反应中发现构筑方法";
a [label="实际目标局部结构
功能单元、链段、完整环系及原始连接位置
不预先指定目标应该在哪里开环或闭环", fillcolor="#DBEAFE"];
b [label="子结构召回真实产物
目标局部与整体/核心查询互补
部分结构或化学视图关系保留标签"];
c [label="关联命中产物的不同反应
不只取一条最高收率或末端修饰记录
跨产物、跨层级保留分析机会"];
d [label="分析实际反应物到产物
实验结果、阶段、原子对应、成键/断键与环路径
先确认来源变化，再对应到目标", fillcolor="#EAE0F7"];
link [label="连接 / 支链构筑 / 基团转化
是否形成目标对应边界？
真实底物与端口是什么？", fillcolor="#D6F0E5"];
ring [label="源反应有开环 / 闭环 / 重组
哪一段目标结构得到参考？
实际方向与位置有何证据？", fillcolor="#D6F0E5"];
other [label="环已存在 / 其他位置变化 / 未知
不能凭产物有环就算成环
不能凭支链相似就认定方法", fillcolor="#FFF3D6"];
e [label="按目标相关性重排与保留策略多样性
相关位点和证据先于整体相似度
无关保护环开裂不占目标构筑名额
方法类比、未知与实际证据分别展示"];
f [label="不足时在预算内补查
更多关联反应 / 更小真实目标片段 / 已启用视图
有来源后可补查其真实两侧记录
不生成没有来源的目标环前体"];
g [label="给模型的参考包
实际反应、底物、目标位置、可参考贡献与差异
未召回 / 未分析 / 证据未知分别报告", fillcolor="#DBEAFE"];
a -> b -> c -> d;
d -> link; d -> ring; d -> other;
link -> e; ring -> e; other -> e;
e -> f -> g;
}
'''

QUALITY = '''digraph G {
BASE
label="反应证据解释：实际获得、阶段关系与局部确定性";
a [label="检索命中的实际记录
完整结构、参与组分、原文与目标位置", fillcolor="#DBEAFE"];
stage [label="先定位实验与样品阶段
投入 / 反应 / 后处理 / 分离 / 取样分析
按原文允许分支或缺失；不补造中间体与分离节点
衍生物、原产物、回收部分的测量分别关联"];
result [label="核对实际结果与获得操作
化学制备 / 拆分富集 / 普通回收 / 分析观察
预期未得到 / 失败 / 信息不足
富集可提供获得参考，普通回收不算本步制得", fillcolor="#EAE0F7"];
mapcheck [label="每根关键键的映射证据
形式有效性：编号、元素、标记、实例
未映射编号0不作身份；缺副产物不造内部断键
统一芳香性，核验共振写法；保留实际变化
局部稳定性：已检候选一致还是冲突？
化学支持：来源、示踪、规则推定或未知
单一映射或检查截断保留范围", fillcolor="#D6F0E5"];
instances [label="同结构的多份参与
化合物身份可共用检索
每份分子实例保留独立原子对应
投料当量不等于进入产物的份数
缺少份数不能只为配平而复制", fillcolor="#D6F0E5"];
stereo [label="目标手性怎么获得
从底物继承 / 本步建立 / 去对称化
拆分富集 / 构型改变或会聚 / 未知
ee/dr 绑定对象与阶段
零重原子键变化也可有价值", fillcolor="#D6F0E5"];
combine [label="局部结论与实际贡献分开返回
有争议的键不计确定构筑；其他有据资料保留
等价编号不产生新策略；多份底物不重复计独立来源
获得目标不等于建立骨架或解决手性底物来源"];
context [label="结合方向、环境、条件与已有关系
实际正向 / 同向类比 / 仅反向 / 结构线索
共同中间体核对样品组成与阶段相容性
主反应条件与后处理、分析条件分开
通法引用保留出处，本例收率与结果不继承"];
count [label="计数与代表实例
制备、拆分富集、获得并集、使用和分析分别计
关键键：来源支持 / 稳定推定 / 单一推定 / 争议 / 未评估
保留不同构筑与获得途径，以及未解决前体要求", fillcolor="#EAE0F7"];
out [label="然后交给模型预测
明确每条资料贡献了什么、证据支持到哪里
所有检索与已知事实整理均在模型调用前完成", fillcolor="#DBEAFE"];
a -> stage -> result;
result -> mapcheck; result -> instances; result -> stereo;
mapcheck -> combine; instances -> combine; stereo -> combine;
combine -> context -> count -> out;
}
'''

ATTACHMENT = '''digraph G {
BASE
label="子结构命中之后：这条反应提供了所需连接方法吗？";
a [label="目标自动分区
母核 + 期望支链/基团 + 目标连接位点与边界键
合法替代边界分别编号，无需模型先预测", fillcolor="#DBEAFE"];
b [label="召回产物与全部相关反应
母核、支链和边界在同一实际产物中匹配
产物相同，也可能对应完全不同的反应步骤"];
c [label="识别实际反应类型与变化
两侧底物、成键/断键/键型变化、来源条件
排除有据的共振写法差异；不消除实际转化
反应名称仅为辅助，不能代替目标位点核验"];
d [label="回溯母核与支链来源
母核是否此前已有？支链完整带入还是本步构筑？
哪个真实底物、哪个端基提供目标连接？
实际结果、映射争议与未知分别保留"];
e [label="判定当前目标边界", fillcolor="#EAE0F7"];
formed [label="边界本步形成
母核与支链完整/局部覆盖
对应连接方法 / 方法类比", fillcolor="#D6F0E5"];
elab [label="边界此前已存在
本步延长支链或转换基团
支链构筑/修饰参考"];
other [label="变化在其他位置
或母核后构筑 / 替代边界
分配到相应任务，不能冒充当前连接"];
unknown [label="反应信息或映射不足
连接贡献未知
保留结构线索，不计有据方法", fillcolor="#FFF3D6"];
r [label="目标连接方法区排序
先检查相关变化和位点，再比较真实底物与环境
精确产物的无关修饰不占连接方法名额
不同类型可以提供同一连接；同类型也可能无关"];
o [label="给模型的答案
哪类反应、用哪些母核与支链底物、在何处形成哪根键
支链覆盖了多少、实际端基和条件是什么、还有哪些差异
所有判定在模型预测前完成", fillcolor="#DBEAFE"];
a -> b -> c -> d -> e;
e -> formed; e -> elab; e -> other; e -> unknown;
formed -> r; elab -> r; other -> r; unknown -> r;
adapt [label="类似物的小差异可否通过换一个底物解决？
母核供体和支链供体均可检查
单来源差异 → 保留反应角色 → 回放目标 → 条件支持
作为具体类比建议，不计为目标已有制备", fillcolor="#EAE0F7"];
r -> adapt -> o;
}
'''

TRANSFER = '''digraph G {
BASE
label="单反应物替换：让已有反应更接近目标分子";
a [label="实际参考反应 + 目标分子
原底物甲 + 原底物乙 → 参考产物
支链近似或整体骨架一致，都进入检查", fillcolor="#DBEAFE"];
b [label="定位全部目标差异
新增/删除基团、连接、位置、立体与同位素
差异通过原子对应与连接锚点追溯来源"];
c [label="差异是否能归到一个反应物槽位？
保留其他组分、完整反应端与实例关系"];
side [label="支链差异来自乙
甲 + 替代乙
例：乙胺换丙胺", fillcolor="#D6F0E5"];
core [label="母核差异来自甲
替代甲 + 乙
例：苯甲酰端换对氟苯甲酰端", fillcolor="#D6F0E5"];
unknown [label="两个来源都需改变 / 映射不清
保持一般方法类比
不声称只换一个底物", fillcolor="#FFF3D6"];
d [label="构造或检索具体替代底物
保留原功能团、离去部分、保护和必要反应角色
已记录结构与仅推定结构分别标注
重复底物份数与交叉选择性不能忽略"];
e [label="按来源变化进行有限结构回放
先复现原产物，再只换一个槽位
按组合核验各产物，不用第一项决定主产物
比对视图去映射编号，原图和原子追踪保留
完整目标、位置和立体要求仍需核验
去重前限制组合数，目标命中与枚举完整性分开"];
f [label="单槽位变化仍需比较化学环境
新增竞争位点、位阻、电子、配位与保护差异
已有目标实验 / 类似底物范围支持 / 未验证 / 冲突
图回放成功不证明原条件可以直接复用"];
g [label="给模型的具体建议
哪个原反应？换谁？换成什么？其他组分是什么？
哪些目标差异解决了，完整目标是否可对应？
替代底物与条件还有哪些证据缺口？", fillcolor="#DBEAFE"];
count [label="事实和推定分开统计
原反应保留来源；替换建议标为未观察的推定
不增加目标制备、已知成键或已有路线计数"];
a -> b -> c;
c -> side; c -> core; c -> unknown;
side -> d; core -> d;
d -> e -> f -> g;
unknown -> g;
g -> count;
}
'''

TOPOLOGY = '''digraph G {
BASE
label="开环闭环的参考位置，从已检索反应中识别";
a [label="目标：无环 / 有环 / 链环混合
三层表示整体、关键核心和局部结构", fillcolor="#DBEAFE"];
b [label="先进行结构与支链召回
无环目标使用链式功能单元和连接路径
不剪目标环猜前体，不向目标链加键猜环"];
c [label="命中产物 → 关联实际反应集合
整体和核心命中也参与分析
一个产物保留不同来源反应"];
d [label="核验实际两侧结构与变化
先查发生了什么，再判断与目标哪里相关
阶段、方向、原子来源及映射争议明确保留", fillcolor="#EAE0F7"];
o [label="实际开环
源底物环键消失，生成对应链段
断键可能不在目标产物中
返回源键及保留原子对应", fillcolor="#D6F0E5"];
cl [label="实际闭环
源产物环连接在反应前不存在
前体可是一条链或多个组分
投影到目标中有据的相关位置", fillcolor="#D6F0E5"];
x [label="其他情况
环保留 / 环重组 / 局部转化 / 未知
净环数或产物形状不能单独分类
不反转来源记录当另一方向的证据"];
r [label="目标相关性重排
当前目标片段的构筑证据优先
同类名称或无关位置的环变化不够
环变化不是天然高于局部修饰的万能标签"];
f [label="召回边界
排序不能找回根本没召回的先例
预算内扩大真实结构或关联反应范围
未找到与未完成分别报告", fillcolor="#FFF3D6"];
end_result [label="之后才交给模型
这是某已知反应的可参考位置与差异
不是预先断言目标必须在这里开/闭环", fillcolor="#DBEAFE"];
a -> b -> c -> d;
d -> o; d -> cl; d -> x;
o -> r; cl -> r; x -> r;
r -> f -> end_result;
}
'''

RANKING = '''digraph G {
BASE
label="子结构检索后的过滤与排序：参考价值和实验适配分别回答";
a [label="三层命中反应 + 有来源的替换类比
排序单位：目标任务 × 实际实验或明确推定建议
同产物的不同反应和条件分别保留", fillcolor="#DBEAFE"];
b [label="方法与证据资格核对
是否在对应位置提供所需连接/转化？
实际制得、观察、预期、失败、未知分别标记
事实与推定、执行完整与截断分开"];
good [label="有据方法 / 明确类比
进入对应任务的比较组", fillcolor="#D6F0E5"];
other [label="其他步骤或位置的参考
保留其作用，不冒充当前方法"];
unknown [label="信息不足或冲突
保留待核查资料
不默认成功、简单或安全", fillcolor="#FFF3D6"];
feat [label="提取九方向特征及来源
方法相关性 · 迁移负担 · 反应性/选择性 · 证据
材料供应 · 操作设备 · 危险/监管 · 产出分离 · 放大资源
每项绑定材料、阶段、规模、单位、日期和未知状态"];
ref [label="默认：合成参考价值
目标贡献 → 证据 → 迁移与环境 → 覆盖
同类且信息可比时比较操作和资源负担
特殊设备方法仍可有很高启发价值", fillcolor="#D6F0E5"];
lab [label="可选：按明确配置的实验适配
设备/温压/规模/材料限制四态匹配
通过 / 不符合 / 未知 / 不适用
未配置能力时不声称已适配", fillcolor="#D6F0E5"];
compare [label="组内比较与权衡
固定可比字段、测量口径与缺失分组
组内固定偏好；组间配额保留未知和不同策略
不用未经校准的成功率或安全总分"];
select [label="结果组织
真实实验去重 + 目标缺口覆盖 + 方法/来源多样性
展示条目、引用实验和推定建议分别计数
稳定分页；重要缺失可在共同预算内补查
重排使用全部已评估候选，不只上次展示列表
截断只代表已分析候选中的排序"];
result [label="输出理由与代价，再交给模型
已报告取得完整目标的记录优先可见
解决哪一步？需替换什么？材料和设备要求？
温压/后处理、危险信息及条件迁移缺口在哪里？
参考排序不是实验执行许可", fillcolor="#DBEAFE"];
a -> b;
b -> good; b -> other; b -> unknown;
good -> feat; other -> feat; unknown -> feat;
feat -> ref; feat -> lab;
ref -> compare; lab -> compare;
compare -> select -> result;
}
'''

DIMENSIONS = '''digraph G {
BASE
label="九个排序方向：先看对目标有何帮助，再看执行代价";
a [label="① 目标方法相关性
实际反应类型与目标位点
连接、转化、开闭环或获得贡献
结构像不等于方法相关", fillcolor="#DBEAFE"];
b [label="② 类比迁移负担
换几个反应物、改变哪些结构
反应端、位置、立体与保护差异
单槽位替换也有条件缺口", fillcolor="#DBEAFE"];
c [label="③ 反应性与选择性
电子、位阻、共轭、配位环境
竞争位点、基团相容性证据
没有通用的官能团活性总分", fillcolor="#DBEAFE"];
d [label="④ 证据与可重复性
实际产物、分离/分析、真实来源
独立实验、失败与冲突、映射范围
重复公开记录不等于复现", fillcolor="#D6F0E5"];
e [label="⑤ 原料与供应负担
底物、催化剂、活化与保护准备
规格、纯度、日期、价格单位
分子量小不等于廉价可得", fillcolor="#D6F0E5"];
f [label="⑥ 操作与设备
各阶段高低温、压力与时长
惰性/无水、气体、光电及值守
后处理和分析阶段不能混用", fillcolor="#D6F0E5"];
g [label="⑦ 危险性与监管
具体材料 SDS/GHS 与来源版本
过程放热/气体/压力及规模信息
未查到信息不等于无危险", fillcolor="#FFF3D6"];
h [label="⑧ 产出与分离
分离收率、分析收率分别比较
纯度、选择性、回收及纯化步骤
不能只按百分比高低选择", fillcolor="#FFF3D6"];
i [label="⑨ 放大与资源
已有规模、传热/传质相关证据
材料、溶剂/水、洗脱与废物
资料不足不计算虚假的 PMI", fillcolor="#FFF3D6"];
note [shape=plaintext,label="分子量：区分目标、参考产物与实际投料材料；结合结构覆盖、用量与盐形解释
温度：结合所有阶段、设备、材料和时间；室温并不自动代表低过程风险
输出：合成参考价值 + 实验适配状态 + 可追溯理由 + 未知信息", fontsize=14];
{rank=same; a; b; c;}
{rank=same; d; e; f;}
{rank=same; g; h; i;}
a -> b -> c [style=invis];
d -> e -> f [style=invis];
g -> h -> i [style=invis];
a -> d -> g [style=invis];
b -> e -> h [style=invis];
c -> f -> i [style=invis];
h -> note [style=invis];
}
'''

MARKUSH = '''digraph G {
BASE
label="默认 Markush：限制关键化学特征，联合检索可变支链";
a [label="输入完整目标
自动确定三层核心/锚点、连接位点与必要功能单元
无需用户逐个指定重要或非重要支链", fillcolor="#DBEAFE"];
fixed [label="固定必要要素
定义任务的核心连接、功能团类别和位置
必要氢数、电荷、键语义与联合关系", fillcolor="#D6F0E5"];
variable [label="非关键外围设为 R
不逐原子固定目标取代基
允许不同实际支链和未锁定位置的额外取代", fillcolor="#D6F0E5"];
family [label="生成有限的 Markush 家族
固定框架 + R1、R2… + 必要约束
示意：对位 R1–C6H4–O–R2
具体片段 / 基团类别 / 可选 H / 无额外类别限制"];
relations [label="核验查询的完整含义
多个位点在同一具体分子、同一核心映射成立
完整支链类别不只检查第一原子
重原子支链不计氢；H 数和同位素另核验
检查核心内额外键；包含与保拓扑分开
桥接或回环 R 整体约束；可变连接段必须语义明确"];
transport [label="编译、任务传递与缓存恢复
完整查询约束保留类别、位点和后检查
普通 SMARTS 会丢失部分通用组限制
恢复属性并启用匹配参数；缺条件则停止完整判定
传递前后用正反例检查语义一致"];
scope [label="优先选择有参考价值的体量范围
整体/核心：分子量与重原子数接近目标
分片：按局部覆盖和实际反应位置比较
属性与指纹绑定同一具体表示
不足先区分原因，再补查或放宽", fillcolor="#D6F0E5"];
index [label="当前范围内的子结构索引
筛选家族必需特征，再匹配固定结构
限时分批取数，不先全量计数或排序"];
similar [label="整体/核心和宽查询：相似优先
在声明范围累计不同结构，再做严格匹配
全库前缀后过滤不等于窗口内 Top-K
与索引通道取并集；保留当前选择范围", fillcolor="#FFF3D6"];
search [label="完整 R 与联合条件核验
同一具体分子、同一映射下检查全部要求
对称核心在完整 R 核验后去重
工具不支持或预算耗尽时标未评估/截断
存在命中与分配枚举完整性分别报告
宽查询先返回参考；完整枚举为后续离线能力"];
result [label="提取实际 R 分配与共存组合
每个位点出现过什么？哪些 R 在同一分子中共存？
只有分别见过的 R，不能拼成全部已知组合", fillcolor="#EAE0F7"];
reaction [label="再分析真实反应与目标迁移
哪个 R 本步引入、延长或保留？
能否换一个实际反应物得到目标？
被放宽的基团是否带来位阻、竞争或条件差异？"];
out [label="返回给排序与模型
具体分子、各 R 和真实联合实例、实际反应与出处
目标覆盖、放宽依据、未解决差异与检索范围
查询通式不等于具体目标已经合成", fillcolor="#DBEAFE"];
a -> fixed; a -> variable;
fixed -> family; variable -> family;
family -> relations -> transport -> scope;
scope -> index -> search;
scope -> similar;
similar -> search;
search -> result -> reaction -> out;
result:w -> family:w [style=dashed,constraint=false,label="位点缺口
预算内定向补查"];
reaction:e -> scope:e [style=dashed,constraint=false,label="当前范围方法不足
预算内放宽"];
}
'''


if __name__ == '__main__':
    diagrams = [('scaffold-search', MAIN), ('chemical-recall', CHEMISTRY),
                ('core-branch-combination', CORE), ('fragment-retrieval', FRAGMENT),
                ('reaction-reference-quality', QUALITY), ('attachment-methods', ATTACHMENT),
                ('single-reactant-transfer', TRANSFER), ('topology-search', TOPOLOGY),
                ('result-ranking', RANKING), ('ranking-dimensions', DIMENSIONS),
                ('markush-query', MARKUSH)]
    for name, body in diagrams:
        source = ROOT / f'{name}.dot'
        source.write_text(body.replace('BASE', BASE))
        for ext in ('svg', 'png'):
            subprocess.run(['dot', f'-T{ext}', '-Gdpi=130', str(source),
                            '-o', str(ROOT / f'{name}.{ext}')], check=True)
    print(f'Rendered {len(diagrams)} current design diagrams.')
