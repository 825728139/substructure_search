"""复现设计审查中的结构边界情况；不验证反应可行性。
请使用已经安装 RDKit 的 Python 环境运行。
"""
from pathlib import Path
import json
from rdkit import Chem, rdBase
from rdkit.Chem import rdTautomerQuery
from rdkit.Chem.Scaffolds import MurckoScaffold

report={'rdkit_version':rdBase.rdkitVersion,'scope':'structure_and_matching_only','cases':[]}
def mol(s):
    """将示例 SMILES 解析为 RDKit 分子；解析失败触发断言，返回有效分子。"""
    m=Chem.MolFromSmiles(s)
    assert m is not None,s
    return m
def scaffold(s):
    """提取示例分子的 Murcko 骨架并返回规范 SMILES，用于比较结构表示的差异。"""
    return Chem.MolToSmiles(MurckoScaffold.GetScaffoldForMol(mol(s)))
def add(label,data):
    """向当前报告追加一个带中文案例名称的结构检查结果。"""
    report['cases'].append({'case':label,**data})

for label,a,b in [
 ('Cbz保护导致Murcko身份变化','Nc1ccccc1','O=C(OCc1ccccc1)Nc1ccccc1'),
 ('环酮与环醇导致Murcko身份变化','O=C1CCCCC1','OC1CCCCC1'),
 ('互变异构导致Murcko身份变化','O=c1cccc[nH]1','Oc1ccccn1')]:
    sa,sb=scaffold(a),scaffold(b)
    assert sa!=sb
    add(label,{'structures':[a,b],'scaffolds':[sa,sb],'equal':False})
a,b=mol('O=c1cccc[nH]1'),mol('Oc1ccccn1')
ordinary=b.HasSubstructMatch(a)
tautomer_aware=rdTautomerQuery.TautomerQuery(a).IsSubstructOf(b)
assert not ordinary and tautomer_aware
add('互变异构查询补回严格查询漏掉的匹配',{'ordinary_match':ordinary,'tautomer_aware_match':tautomer_aware})
q=mol('C[C@H](O)C(=O)O')
values=[]
for s,want in [('C[C@H](O)C(=O)O',True),('C[C@@H](O)C(=O)O',False),('CC(O)C(=O)O',False)]:
    ordinary=mol(s).HasSubstructMatch(q,useChirality=False)
    stereo=mol(s).HasSubstructMatch(q,useChirality=True)
    assert ordinary and stereo==want
    values.append({'candidate':s,'ignore_stereo':ordinary,'use_stereo':stereo})
add('相同相反与未指定立体需分组',{'query':Chem.MolToSmiles(q),'matches':values})
m=mol('O=C1NCCCCCCCCCC1')
c,o,n=m.GetSubstructMatch(Chem.MolFromSmarts('[CX3](=[OX1])-[NX3]'))
bond=m.GetBondBetweenAtoms(c,n)
assert bond.IsInRing()
frags=Chem.FragmentOnBonds(m,[bond.GetIdx()],addDummies=True)
count=len(Chem.GetMolFrags(frags))
assert count==1
add('大环开一根环内键后仍为一个连通分子',{'input':Chem.MolToSmiles(m),'cut_atom_indices':[c,n],'components':count,'opened_query':Chem.MolToSmiles(frags)})
m=mol('c1ccccc1-c1ccccc1')
rings=[set(r) for r in m.GetRingInfo().AtomRings()]
atom_union=set().union(*rings)
bond_union={b.GetIdx() for b in m.GetBonds() if any(b.GetBeginAtomIdx() in r and b.GetEndAtomIdx() in r for r in rings)}
assert len(atom_union)==m.GetNumHeavyAtoms() and len(bond_union)<m.GetNumBonds()
add('分开覆盖两个环可覆盖所有原子却不覆盖连接键',{'input':Chem.MolToSmiles(m),'covered_atoms':len(atom_union),'total_heavy_atoms':m.GetNumHeavyAtoms(),'covered_bonds':len(bond_union),'total_bonds':m.GetNumBonds(),'missing_bonds':[b.GetIdx() for b in m.GetBonds() if b.GetIdx() not in bond_union]})
# 记录身份一致与满足未完全指定的目标要求，是两种不同判断。
unspecified = mol('CC(O)c1ccccc1')
stereo_candidates = []
for smiles in ('C[C@H](O)c1ccccc1', 'C[C@@H](O)c1ccccc1'):
    candidate = mol(smiles)
    same_key = Chem.MolToSmiles(candidate) == Chem.MolToSmiles(unspecified)
    matches_query = candidate.HasSubstructMatch(unspecified, useChirality=True)
    assert not same_key and matches_query
    assert candidate.GetNumAtoms() == unspecified.GetNumAtoms()
    assert candidate.GetNumBonds() == unspecified.GetNumBonds()
    stereo_candidates.append({'smiles': smiles, 'same_isomeric_key': same_key,
                              'matches_unspecified_stereo_query': matches_query})
add('未指定手性的目标不能只靠带立体的身份字符串查找', {
    'target': Chem.MolToSmiles(unspecified), 'candidates': stereo_candidates,
    'scope': 'Controlled same-connectivity examples; not a general identity checker or observation claim.'})

# isomericSmiles=False 同时移除同位素标签和立体信息，不能用于仅忽略立体。
isotope_examples = []
for smiles in ('[13CH3][C@H](O)c1ccccc1', 'C[C@H](O)c1ccccc1'):
    molecule = mol(smiles)
    view = Chem.Mol(molecule)
    Chem.RemoveStereochemistry(view)
    isotope_examples.append({
        'original': Chem.MolToSmiles(molecule),
        'nonisomeric_serialization': Chem.MolToSmiles(molecule, isomericSmiles=False),
        'stereo_removed_isotope_preserved': Chem.MolToSmiles(view, isomericSmiles=True),
    })
assert isotope_examples[0]['nonisomeric_serialization'] == isotope_examples[1]['nonisomeric_serialization']
assert isotope_examples[0]['stereo_removed_isotope_preserved'] != isotope_examples[1]['stereo_removed_isotope_preserved']
assert '[13CH3]' in isotope_examples[0]['stereo_removed_isotope_preserved']
add('仅忽略立体的视图仍需保留同位素', {'examples': isotope_examples,
    'scope': 'Serialization behavior only; original structures remain unchanged.'})
Path(__file__).with_name('chemical_edge_cases.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(f"{len(report['cases'])} chemical representation/matching cases verified; RDKit {rdBase.rdkitVersion}.")
