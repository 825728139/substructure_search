"""Third-round representation checks, not chemical feasibility tests.
All mapped equations below are illustrative, not extracted experiments.
"""
from pathlib import Path
from collections import Counter
import json
from rdkit import Chem, rdBase

def mol(smiles):
    result=Chem.MolFromSmiles(smiles)
    assert result is not None,smiles
    return result

def plain(m):
    m=Chem.Mol(m)
    for a in m.GetAtoms(): a.SetAtomMapNum(0)
    return Chem.MolToSmiles(m)

def bonds(m):
    return {tuple(sorted((b.GetBeginAtom().GetAtomMapNum(),b.GetEndAtom().GetAtomMapNum()))):str(b.GetBondType()) for b in m.GetBonds()}

def edits(reactants,products):
    a,b=bonds(reactants),bonds(products)
    return {'formed':sorted(b.keys()-a.keys()),'broken':sorted(a.keys()-b.keys()),'order_changes':sorted(k for k in a.keys()&b.keys() if a[k]!=b[k])}

report={'rdkit_version':rdBase.rdkitVersion,'scope':'illustrative_graph_and_multiplicity_checks','cases':[]}
r=mol('[CH3:1][C:2](=[O:3])[OH:4].[CH3:5][OH:6]')
products=[mol('[CH3:1][C:2](=[O:3])[O:6][CH3:5].[OH2:4]'),mol('[CH3:1][C:2](=[O:3])[O:4][CH3:5].[OH2:6]')]
changes=[edits(r,p) for p in products]
assert plain(products[0])==plain(products[1])
assert changes[0]['formed']!=changes[1]['formed']
assert all(len(c['formed'])==len(c['broken'])==1 and not c['order_changes'] for c in changes)
assert all(p.GetNumHeavyAtoms()==r.GetNumHeavyAtoms() for p in products)
report['cases'].append({'case':'相同结构反应和相同编辑数可对应不同新成键位置','illustration_only':True,'reactants':Chem.MolToSmiles(r),'products':[Chem.MolToSmiles(p) for p in products],'unmapped_product':plain(products[0]),'alternative_changes':changes,'note':'Alternative assignments illustrate ambiguity, not two demonstrated mechanisms or pathways.'})

reactant_text='[CH3:1][CH:2]=[O:3].[CH3:4][CH:5]=[O:6]'
r=mol(reactant_text)
p=mol('[CH:2](=[O:3])[CH2:1][CH:5]([OH:6])[CH3:4]')
identities=Counter(plain(mol(x)) for x in reactant_text.split('.'))
assert identities=={'CC=O':2}
assert mol('CC=O').GetNumHeavyAtoms()==3 and p.GetNumHeavyAtoms()==6
assert r.GetNumHeavyAtoms()==p.GetNumHeavyAtoms()
assert edits(r,p)['formed']==[(1,5)]
report['cases'].append({'case':'同一底物两份实例不能随结构去重丢掉','illustration_only':True,'unique_structure_count':len(identities),'molecular_instance_count':sum(identities.values()),'instances_by_structure':dict(identities),'mapped_reactants':reactant_text,'mapped_product':Chem.MolToSmiles(p),'changes':edits(r,p),'note':'Copy count in this illustration is explicit; missing stoichiometry must not be invented from atom balance alone.'})

a=mol('[CH3:1][C@H:2]([OH:3])[CH2:4][CH3:5]')
b=mol('[CH3:1][C@@H:2]([OH:3])[CH2:4][CH3:5]')
assert all(not v for v in edits(a,b).values())
assert plain(a)!=plain(b)
assert not a.HasSubstructMatch(b,useChirality=True)
report['cases'].append({'case':'零重原子键编辑不表示目标立体结构相同','illustration_only':True,'structures':[plain(a),plain(b)],'heavy_atom_bond_changes':edits(a,b),'strict_stereo_match':False,'note':'This comparison does not establish an inversion, resolution or any actual reaction.'})
Path(__file__).with_name('mapping_and_stereo_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(f'{len(report["cases"])} illustrative mapping/multiplicity/stereo checks passed; RDKit {rdBase.rdkitVersion}.')
