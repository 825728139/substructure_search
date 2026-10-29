"""用人工构造的反应端点图检查目标检索的语义。
这些例子没有文献来源，不用于指认机理或验证反应可行性、动力学。
"""
from pathlib import Path
import json
from rdkit import Chem,rdBase
from rdkit.Chem.Scaffolds import MurckoScaffold

def mol(s):
 """将示例 SMILES 解析为 RDKit 分子；解析失败触发断言，返回有效分子。"""
 m=Chem.MolFromSmiles(s);assert m is not None,s
 return m

def bonds(m):
 """返回按原子映射号对索引的键型字典，供受控示例比较端点图变化。"""
 return {tuple(sorted((b.GetBeginAtom().GetAtomMapNum(),b.GetEndAtom().GetAtomMapNum()))):str(b.GetBondType()) for b in m.GetBonds()}

def summary(m):
 """返回重原子、键、组分和独立环数量，供无环与环变化示例比较。"""
 return {'atoms':m.GetNumHeavyAtoms(),'bonds':m.GetNumBonds(),'components':len(Chem.GetMolFrags(m)),'cycle_rank':m.GetNumBonds()-m.GetNumAtoms()+len(Chem.GetMolFrags(m))}

def changes(r,p):
 """对受控的两侧映射图取键集合差，返回成键、断键和键级变化；不指认反应机理。"""
 a,b=bonds(r),bonds(p)
 return {'formed':sorted(b.keys()-a.keys()),'broken':sorted(a.keys()-b.keys()),'order_changed':sorted(k for k in a.keys()&b.keys() if a[k]!=b[k])}

def plain(m):
 """复制分子并移除映射号，返回保留立体与同位素信息的规范结构字符串。"""
 m=Chem.Mol(m)
 for a in m.GetAtoms():a.SetAtomMapNum(0)
 return Chem.MolToSmiles(m)

rows=[]
linear=mol('CNCCO')
assert MurckoScaffold.GetScaffoldForMol(linear).GetNumAtoms()==0
core=Chem.MolFromSmarts('[N]-[CH2]-[CH2]-[OX2H1+0]')
assert linear.HasSubstructMatch(core)
rows.append({'id':'acyclic_nonempty_functional_core','target':'CNCCO','murcko_atom_count':0,'functional_core_atom_count':core.GetNumAtoms(),'match':True})

p=mol('[OH:1][CH2:2][CH2:3][NH:5][CH3:4]')
r_open=mol('[O:1]1[CH2:2][CH2:3]1.[CH3:4][NH2:5]')
r_sub=mol('[OH:1][CH2:2][CH2:3][Cl:6].[CH3:4][NH2:5]')
for name,r,expected_rank in [('ring_opening_to_acyclic',r_open,1),('acyclic_substitution_same_product',r_sub,0)]:
 c=changes(r,p)
 assert summary(r)['cycle_rank']==expected_rank and summary(p)['cycle_rank']==0
 assert c['formed']==[(3,5)]
 rows.append({'id':name,'reactants':Chem.MolToSmiles(r),'product':Chem.MolToSmiles(p),'reactant_graph':summary(r),'product_graph':summary(p),'changes':c})
assert changes(r_open,p)['broken']==[(1,3)]
assert changes(r_sub,p)['broken']==[(3,6)]

r=mol('[NH2:1][CH2:2][CH2:3][CH2:4][C:5](=[O:6])[OH:7]')
p_cycle=mol('[NH:1]1[CH2:2][CH2:3][CH2:4][C:5]1=[O:6]')
c=changes(r,p_cycle)
assert summary(r)['cycle_rank']==0 and summary(p_cycle)['cycle_rank']==1
assert c['formed']==[(1,5)]
rows.append({'id':'acyclic_to_cyclic_endpoint','reactants':Chem.MolToSmiles(r),'product':Chem.MolToSmiles(p_cycle),'changes':c,'before':summary(r),'after':summary(p_cycle)})

r=mol('[NH:1]1[CH2:2][CH:3]=[CH:4][C:5]1=[O:6]')
c=changes(r,p_cycle)
assert not c['formed'] and not c['broken'] and c['order_changed']==[(3,4)]
assert summary(r)['cycle_rank']==summary(p_cycle)['cycle_rank']==1
rows.append({'id':'same_cyclic_product_ring_already_present','reactants':Chem.MolToSmiles(r),'product':Chem.MolToSmiles(p_cycle),'changes':c})

atom_by_map={a.GetAtomMapNum():a.GetIdx() for a in p_cycle.GetAtoms()}
b=p_cycle.GetBondBetweenAtoms(atom_by_map[1],atom_by_map[5])
opened=Chem.FragmentOnBonds(p_cycle,[b.GetIdx()],addDummies=True)
assert len(Chem.GetMolFrags(opened))==1
assert sum(a.GetAtomicNum()==0 for a in opened.GetAtoms())==2
rows.append({'id':'query_ring_cut_is_one_fragment_two_ports','query':Chem.MolToSmiles(opened),'components':1,'dummy_ports':2,'not_forward_reaction_direction':True})

r=mol('[CH2:1]1[CH2:2][CH2:3][CH:4]1[CH2:5][CH3:6]')
p_expand=mol('[CH2:1]1[CH2:2][CH2:3][CH2:4][CH:5]1[CH3:6]')
c=changes(r,p_expand)
assert summary(r)['cycle_rank']==summary(p_expand)['cycle_rank']==1
assert c['broken']==[(1,4)] and c['formed']==[(1,5)]
assert sorted(len(x) for x in r.GetRingInfo().AtomRings())==[4]
assert sorted(len(x) for x in p_expand.GetRingInfo().AtomRings())==[5]
rows.append({'id':'ring_rank_unchanged_but_topology_changed','reactants':Chem.MolToSmiles(r),'product':Chem.MolToSmiles(p_expand),'changes':c,'before':summary(r),'after':summary(p_expand),'note':'Net mapped topology illustration, not evidence of an elementary ring-expansion mechanism.'})

out={'scope':'seven invented representation and graph-edit cases; no literature or experimental claims','rdkit_version':rdBase.rdkitVersion,'cases':rows}
Path(__file__).with_name('acyclic_and_ring_change_checks.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print(f'{len(rows)} acyclic/topology graph cases checked; no reaction feasibility or production classifier tested.')
