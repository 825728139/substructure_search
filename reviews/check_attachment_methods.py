"""Check four invented graph changes giving the same product.
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
out={'rdkit_version':rdBase.rdkitVersion,'scope':'invented graph-only examples; classifications are expected labels, not classifier output','product_without_maps':unmapped(p),'primary_core':'Ar-O (Ar = 4-methoxyphenyl)','primary_sidechain':'CH2-CH2-N(CH3)2','primary_interface':primary,'alternative_interface':alternative,'cases':rows}
Path(__file__).with_name('attachment_method_checks.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print('Four same-product graph examples checked; one forms the primary interface, one forms the alternative boundary.')
