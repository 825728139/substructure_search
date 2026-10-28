"""Check four invented graph changes and an explicit multistage counterexample.
Tests only atom correspondence and changed boundaries, not experimental
feasibility, named reaction classification, or a production method scorer.
"""
from pathlib import Path
import json
from rdkit import Chem, rdBase

p=Chem.MolFromSmiles('COc1ccc(OCCN(C)C)cc1')
for a in p.GetAtoms(): a.SetAtomMapNum(a.GetIdx()+1)
aryl,oxygen,c1,c2,nitrogen=p.GetSubstructMatch(Chem.MolFromSmarts('c-[OX2]-[CH2]-[CH2]-[NX3]'))
methyl,other_o,_=p.GetSubstructMatch(Chem.MolFromSmarts('[CH3]-[OX2]-c'))
n_methyl=next(a.GetIdx() for a in p.GetAtomWithIdx(nitrogen).GetNeighbors() if a.GetTotalNumHs()==3)
def bond_set(m):
 return {tuple(sorted((b.GetBeginAtom().GetAtomMapNum(),b.GetEndAtom().GetAtomMapNum()))):str(b.GetBondType()) for b in m.GetBonds()}
def key(a,b): return tuple(sorted((a+1,b+1)))
def unmapped(m):
 m=Chem.Mol(m)
 for a in m.GetAtoms(): a.SetAtomMapNum(0)
 return Chem.MolToSmiles(m)
primary=key(oxygen,c1)
alternative=key(aryl,oxygen)
cases=[
 ('attach_sidechain',oxygen,c1,c1,'Cl','expected_interface_new'),
 ('elaborate_sidechain',nitrogen,n_methyl,n_methyl,'I','existing_interface_sidechain_elaboration'),
 ('modify_other_group',other_o,methyl,methyl,'I','existing_interface_other_site_modification'),
 ('alternative_attachment',aryl,oxygen,aryl,'Br','alternative_boundary_new'),
]
rows=[]
for i,(name,a,b,leaving_site,element,expected) in enumerate(cases):
 r=Chem.RWMol(p);r.RemoveBond(a,b)
 extra=Chem.Atom(element);extra.SetAtomMapNum(100+i)
 idx=r.AddAtom(extra);r.AddBond(leaving_site,idx,Chem.BondType.SINGLE)
 r=r.GetMol();Chem.SanitizeMol(r)
 before,after=bond_set(r),bond_set(p)
 new=sorted(after.keys()-before.keys())
 assert new==[key(a,b)]
 assert (primary in new)==(name=='attach_sidechain')
 assert (alternative in new)==(name=='alternative_attachment')
 assert p.HasSubstructMatch(Chem.MolFromSmiles('COc1ccc(OCCN(C)C)cc1'))
 if name!='attach_sidechain': assert primary in before
 rows.append({'id':name,'reactants':Chem.MolToSmiles(r),'product':Chem.MolToSmiles(p),'reactants_without_maps':unmapped(r),'formed':new,'broken':sorted(before.keys()-after.keys()),'primary_interface_new':primary in new,'alternative_interface_new':alternative in new,'expected_relative_label':expected})
assert len({x['product'] for x in rows})==1

# The four intermediate structures are supplied explicitly. They are not
# inferred by a classifier and make no claim about viable reaction conditions.
sequence_smiles = [
    '[OH:1][c:2]1[cH:3][cH:4][c:5]([Br:6])[cH:7][cH:8]1',
    '[O:1]([C:9](=[O:10])[CH3:11])[c:2]1[cH:3][cH:4][c:5]([Br:6])[cH:7][cH:8]1',
    '[O:1]([C:9](=[O:10])[CH3:11])[c:2]1[cH:3][cH:4][c:5]([N:12]([CH3:13])[CH3:14])[cH:7][cH:8]1',
    '[OH:1][c:2]1[cH:3][cH:4][c:5]([N:12]([CH3:13])[CH3:14])[cH:7][cH:8]1',
]
sequence = [Chem.MolFromSmiles(s) for s in sequence_smiles]
assert all(m is not None for m in sequence)
for molecule in sequence:
    labels = [a.GetAtomMapNum() for a in molecule.GetAtoms()]
    assert min(labels) > 0 and len(labels) == len(set(labels))
phenol = Chem.MolFromSmarts('[OX2H1+0]-c')
free_phenol = [m.HasSubstructMatch(phenol) for m in sequence]
assert free_phenol == [True, False, False, True]
sequence_bonds = [bond_set(m) for m in sequence]
assert all(b[(1, 2)] == 'SINGLE' for b in sequence_bonds)
assert [((1, 9) in b) for b in sequence_bonds] == [False, True, True, False]
assert [((5, 12) in b) for b in sequence_bonds] == [False, False, True, True]
amine = Chem.MolFromSmiles('[NH:12]([CH3:13])[CH3:14]')
net_inputs = bond_set(Chem.CombineMols(sequence[0], amine))
stage_inputs = bond_set(Chem.CombineMols(sequence[1], amine))
net_formed = sorted(sequence_bonds[-1].keys() - net_inputs.keys())
stage_formed = sorted(sequence_bonds[2].keys() - stage_inputs.keys())
assert net_formed == stage_formed == [(5, 12)]
assert sorted(net_inputs.keys() - sequence_bonds[-1].keys()) == [(5, 6)]
assert sorted(stage_inputs.keys() - sequence_bonds[2].keys()) == [(5, 6)]
stage_counterexample = {
    'id': 'endpoint_phenol_does_not_establish_coupling_stage_tolerance',
    'synthetic': True, 'structures': sequence_smiles,
    'supplied_state_order': ['initial_free_phenol', 'protected_before_coupling',
                             'protected_after_coupling', 'final_free_phenol'],
    'free_phenol_by_state': free_phenol,
    'aryl_oxygen_bond_present_in_all_states': True,
    'temporary_protection_bond_present': [False, True, True, False],
    'net_formed_bonds': net_formed, 'coupling_stage_formed_bonds': stage_formed,
    'limitation': 'The same net connection change does not locate conditions or show free-OH exposure. Without supplied intermediate states, that exposure is unknown. No reaction conditions, literature evidence or transfer engine are tested.',
}
out={'rdkit_version':rdBase.rdkitVersion,'scope':'invented graph-only examples; classifications are expected labels, not classifier output','product_without_maps':unmapped(p),'primary_core':'Ar-O (Ar = 4-methoxyphenyl)','primary_sidechain':'CH2-CH2-N(CH3)2','primary_interface':primary,'alternative_interface':alternative,'cases':rows,'stage_counterexample':stage_counterexample}
Path(__file__).with_name('attachment_method_checks.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print('Four same-product graph examples and one multistage protection counterexample checked; no experimental feasibility assessed.')
