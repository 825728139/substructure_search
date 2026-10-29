"""比较具体分子身份与不连通、通用类别查询模式的语义。"""
from pathlib import Path
import json
from rdkit import Chem, rdBase
loose=Chem.MolFromSmarts('c1ccccc1.[NX3]')
connected=Chem.MolFromSmarts('c1ccccc1-[NX3]')
rows=[]
for s,expected in [('c1ccccc1.CN',False),('Nc1ccccc1',True)]:
    m=Chem.MolFromSmiles(s)
    assert m.HasSubstructMatch(loose)
    assert m.HasSubstructMatch(connected)==expected
    rows.append({'structure':s,'component_count':len(Chem.GetMolFrags(m)),'disconnected_query':True,'connected_query':expected})
generic=Chem.MolFromSmiles('*c1ccccc1')
assert generic is not None and any(a.GetAtomicNum()==0 for a in generic.GetAtoms())
out={'rdkit_version':rdBase.rdkitVersion,'component_cases':rows,'generic_smiles_parses':True,'contains_unresolved_dummy':True,'scope':'Representation checks only; no source product claim evaluated.'}
Path(__file__).with_name('component_scope_checks.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print('2 component matches and 1 generic-input check passed.')
