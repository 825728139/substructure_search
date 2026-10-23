"""Reproduce structural edge cases in the design review, not reaction feasibility.
Run with a Python environment containing RDKit.
"""
from pathlib import Path
import json
from rdkit import Chem, rdBase
from rdkit.Chem import rdTautomerQuery
from rdkit.Chem.Scaffolds import MurckoScaffold

report={'rdkit_version':rdBase.rdkitVersion,'scope':'structure_and_matching_only','cases':[]}
def mol(s):
    m=Chem.MolFromSmiles(s)
    assert m is not None,s
    return m
def scaffold(s):
    return Chem.MolToSmiles(MurckoScaffold.GetScaffoldForMol(mol(s)))
def add(label,data):
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
Path(__file__).with_name('chemical_edge_cases.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(f"{len(report['cases'])} chemical representation/matching cases verified; RDKit {rdBase.rdkitVersion}.")
