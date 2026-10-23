"""Second-round structural checks. No experimental feasibility is asserted.
The atom-mapped multicomponent example is an invented graph illustration.
"""
from pathlib import Path
import json
from rdkit import Chem, rdBase

report={'rdkit_version':rdBase.rdkitVersion,'scope':'structure_and_atom_correspondence_only','cases':[]}
def mol(smiles):
    m=Chem.MolFromSmiles(smiles)
    assert m is not None,smiles
    return m

def boundary_components(m, core):
    remaining=set(range(m.GetNumAtoms()))-core
    components=[]
    while remaining:
        first=remaining.pop(); stack=[first]; comp={first}
        while stack:
            for n in m.GetAtomWithIdx(stack.pop()).GetNeighbors():
                i=n.GetIdx()
                if i in remaining:
                    remaining.remove(i); comp.add(i); stack.append(i)
        links=[]
        for b in m.GetBonds():
            u,v=b.GetBeginAtomIdx(),b.GetEndAtomIdx()
            if (u in comp and v in core) or (v in comp and u in core):
                links.append([u,v])
        components.append({'outside_atom_count':len(comp),'core_boundary_bonds':links})
    return components

values=[]
q=Chem.MolFromSmarts('Clc1ccccc1')
for label,s in [('para','Clc1ccc([N+](=O)[O-])cc1'),('meta','Clc1cccc([N+](=O)[O-])c1')]:
    m=mol(s)
    cl=next(a for a in m.GetAtoms() if a.GetAtomicNum()==17)
    center=cl.GetNeighbors()[0].GetIdx()
    nitro=next(a for a in m.GetAtoms() if a.GetAtomicNum()==7)
    site=next(a for a in nitro.GetNeighbors() if a.GetAtomicNum()==6).GetIdx()
    edges=list(Chem.FindAtomEnvironmentOfRadiusN(m,1,center))
    atoms={center}
    for i in edges:
        b=m.GetBondWithIdx(i); atoms.update((b.GetBeginAtomIdx(),b.GetEndAtomIdx()))
    env=Chem.MolFragmentToSmiles(m,atomsToUse=sorted(atoms),bondsToUse=edges,rootedAtAtom=center)
    values.append({'position':label,'structure':s,'radius_1':env,'ring_distance_to_nitro_site':len(Chem.GetShortestPath(m,center,site))-1,'chlorobenzene_core_match':m.HasSubstructMatch(q)})
assert values[0]['radius_1']==values[1]['radius_1']
assert values[0]['ring_distance_to_nitro_site']==3 and values[1]['ring_distance_to_nitro_site']==2
assert all(x['chlorobenzene_core_match'] for x in values)
report['cases'].append({'case':'相同端口近邻并不描述完整芳环取代环境','examples':values,'note':'No reaction rates or selectivity were calculated.'})

values=[]
q=Chem.MolFromSmarts('c1ccccc1')
for label,s in [('toluene','Cc1ccccc1'),('naphthalene','c1ccc2ccccc2c1'),('biphenyl','c1ccccc1-c1ccccc1')]:
    m=mol(s); match=m.GetSubstructMatch(q); assert match
    external=boundary_components(m,set(match))
    values.append({'name':label,'structure':s,'external_components':external})
assert [len(x['external_components'][0]['core_boundary_bonds']) for x in values]==[1,2,1]
report['cases'].append({'case':'相同苯环子图可能对应单点取代或额外稠合环','examples':values})

reactants='[CH3:1][N+:2]#[C-:3].[CH3:4][Br:5].[OH2:6]'
product='[CH3:1][NH:2][C:3](=[O:6])[CH3:4]'
rs=[mol(x) for x in reactants.split('.')]; p=mol(product)
source={a.GetAtomMapNum():i+1 for i,m in enumerate(rs) for a in m.GetAtoms()}
def bonds(m):
    return {tuple(sorted((b.GetBeginAtom().GetAtomMapNum(),b.GetEndAtom().GetAtomMapNum()))):str(b.GetBondType()) for b in m.GetBonds()}
before={k:v for m in rs for k,v in bonds(m).items()}; after=bonds(p)
formed=sorted(after.keys()-before.keys())
order_changed=sorted(k for k in before.keys()&after.keys() if before[k]!=after[k])
assert formed==[(3,4),(3,6)] and order_changed==[(2,3)]
assert p.HasSubstructMatch(Chem.MolFromSmarts('[NX3]-[CX3](=[OX1])'))
assert (2,3) not in formed
assert len({source[a.GetAtomMapNum()] for a in p.GetAtoms()})==3
report['cases'].append({'case':'酰胺产物不必对应新形成C-N连接','illustration_only':True,'mapped_reactants':reactants,'mapped_product':product,'product_atom_sources':source,'formed_bonds':formed,'bond_order_changes':order_changed,'note':'Invented mapped graph illustrating alternative construction; not a literature record or tested reaction.'})

labelled=mol('[13CH3]CO'); unlabelled=mol('CCO')
strict=unlabelled.HasSubstructMatch(labelled)
broad=labelled.HasSubstructMatch(unlabelled)
assert not strict and broad
report['cases'].append({'case':'明确同位素查询与未指定查询语义不同','labelled_query_matches_unlabelled':strict,'unlabelled_query_matches_labelled':broad})

out=Path(__file__).with_name('reaction_relevance_checks.json')
out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(f'{len(report["cases"])} additional structural/provenance cases passed; RDKit {rdBase.rdkitVersion}.')
