"""Render the current pre-prediction retrieval and bounded reactant-transfer design."""
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
b [label="生成三层候选及原子对应，识别环系和化学要求
严格视图 + 有标签的化学扩展
互变异构 / 母体 / 可能保护形式 / 限定官能团变化"];
g [label="① 整体骨架与相关形式", fillcolor="#D6F0E5"];
c [label="② 核心骨架与支链互补", fillcolor="#D6F0E5"];
f [label="③ 分片骨架与成环参考", fillcolor="#D6F0E5"];
g1 [label="严格完整骨架身份复核
相关形式通过独立视图召回
原结构与差异保留，区分实际/类比/反向证据"];
c1 [label="完整核心与所有位点一致对齐
头尾及多点连接共同比较
位点存在 / 引入 / 保留及共同中间体"];
f1 [label="片间连接：逐分支与端口查询
单分子成环：双端同一实例匹配
多键成环及不同原子来源的构筑方式"];
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
构筑或获得方式、阶段证据、目标差异与未知项"];
model [label="此时才调用模型
考虑局部修饰、支链组合与战略切断
结合参考资料设计目标合成方案", fillcolor="#DBEAFE"];
input_scope [label="确认具体目标与组分范围
具体结构、完整组分和通式分别处理
主体不明时保留边界，不拼接伪共存"];
a -> input_scope -> b;
compiled [label="逐视图显式编译查询
元素、电荷、氢数、环系与实例约束
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
roles -> attachment -> quality -> transfer -> stats -> pack -> model;
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
b [label="自动核心候选与结构匹配
完整环系、连接链、分支与完整官能团
带明确上下文的小功能单元保留受控配额"];
c [label="统一全核心映射
对称位点一致对应；多点连接与骨架嵌入整体比较
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
label="分片与成环：端口、原子来源和完整参与组分";
a [label="目标结构与规则候选
普通连接边界 + 独立成环规则入口
不依赖模型先预测断键", fillcolor="#DBEAFE"];
multi [label="片间连接
单键或受限二键切片
保留全部分支与各自连接端口", fillcolor="#D6F0E5"];
ring [label="单分子成环
开环后仍可能只有一个连通结构
保留两个或多个端口", fillcolor="#D6F0E5"];
complex [label="多键成环
明确局部规则及变化签名
可能包含多根键和键型变化", fillcolor="#D6F0E5"];
m1 [label="逐片检索参考分子
每个分支都有制备/获得/使用/未知状态
不能因一侧容易命中就跳过另一侧"];
r1 [label="在同一真实分子中匹配多个端口
检查端间路径、相对位置与立体信息
两条独立单端记录不算双端共存"];
c1 [label="受控开环或局部环境查询
已有可靠成环记录可补充有出处的任务
无适用规则时明确未评估"];
port [label="每个端口的实际化学信息
目标位置 → 参考位置 → 实际端基与保护状态
结构类似 / 相关功能团 / 已有该位置连接实例
不能用分子其他位置的基团冒充端口支持"];
evidence [label="制备、分析与使用资料分别标记
核对样品阶段、实际结果、身份与各键证据
推定不当作确认；富集获得不当作新成键", fillcolor="#EAE0F7"];
origins [label="按实际变化与来源实例组织参考
化合物身份 / 分子实例 / 投料当量 / 来源份数
相同底物两份进入产物时，原子实例不能去重丢失
未知份数不靠配平复制；完整参与组合一起返回"];
coverage [label="按任务类型评价整个方案
所有分支、所有端口、最弱分支与双端共存
原子、键结构与各键变化证据分开计算
映射争议仅影响对应局部，不虚增构筑方式
原子全部覆盖不等于连接有形成证据"];
out [label="输出给模型的战略切断参考
真实分子、实际端基、底物/产物、反应与出处
切片或成环位置及仍待解决的连接/立体问题
查询图不自动成为已验证前体", fillcolor="#DBEAFE"];
a -> multi; a -> ring; a -> complex;
multi -> m1; ring -> r1; complex -> c1;
m1 -> port; r1 -> port; c1 -> port;
port -> evidence -> origins -> coverage -> out;
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
主反应条件与后处理、分析条件分开"];
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
核对完整目标、未变化结构、位置和立体要求
多产物 / 匹配截断 / 未支持分别保留"];
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


if __name__ == '__main__':
    diagrams = [('scaffold-search', MAIN), ('chemical-recall', CHEMISTRY),
                ('core-branch-combination', CORE), ('fragment-retrieval', FRAGMENT),
                ('reaction-reference-quality', QUALITY), ('attachment-methods', ATTACHMENT),
                ('single-reactant-transfer', TRANSFER)]
    for name, body in diagrams:
        source = ROOT / f'{name}.dot'
        source.write_text(body.replace('BASE', BASE))
        for ext in ('svg', 'png'):
            subprocess.run(['dot', f'-T{ext}', '-Gdpi=130', str(source),
                            '-o', str(ROOT / f'{name}.{ext}')], check=True)
    print(f'Rendered {len(diagrams)} current design diagrams.')
