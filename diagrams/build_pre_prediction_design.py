"""Render the five diagrams of the current pre-prediction retrieval design."""
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
b [label="原子对应、环系、连接链、官能团与立体/同位素要求
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
input_scope [label="确认具体目标与组分范围\n显式编译每种查询的属性和实例约束\n通式或主体不明时保留边界，不拼接伪共存"];
a -> input_scope -> b;
b -> g; b -> c; b -> f;
g -> g1 -> g2;
c -> c1 -> c2;
f -> f1 -> f2;
g2 -> roles; c2 -> roles; f2 -> roles;
roles -> quality -> stats -> pack -> model;
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
独立执行相容的筛选、匹配与完整身份复核
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
m -> precursor -> co -> set -> out;
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


if __name__ == '__main__':
    diagrams = [('scaffold-search', MAIN), ('chemical-recall', CHEMISTRY),
                ('core-branch-combination', CORE), ('fragment-retrieval', FRAGMENT),
                ('reaction-reference-quality', QUALITY)]
    for name, body in diagrams:
        source = ROOT / f'{name}.dot'
        source.write_text(body.replace('BASE', BASE))
        for extension in ('svg', 'png'):
            subprocess.run(['dot', f'-T{extension}', '-Gdpi=130', str(source),
                            '-o', str(ROOT / f'{name}.{extension}')], check=True)
    print('Rendered five current design diagrams.')
