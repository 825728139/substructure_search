"""检查结构相关性；不据此认定实验可行。
其中带原子映射的多组分反应只是人工构造的图示例。
"""
from pathlib import Path
import json
from rdkit import Chem, DataStructs, rdBase
from rdkit.Chem import Descriptors, rdFingerprintGenerator

report={'rdkit_version':rdBase.rdkitVersion,'scope':'structure_and_atom_correspondence_only','cases':[]}
def mol(smiles):
    """将示例 SMILES 解析为 RDKit 分子；解析失败触发断言，返回有效分子。"""
    m=Chem.MolFromSmiles(smiles)
    assert m is not None,smiles
    return m

def boundary_components(m, core):
    """从核心外提取完整连通组分，返回各组分原子数及其连接核心的边界键。"""
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
    m=mol(s)
    match=m.GetSubstructMatch(q)
    assert match
    external=boundary_components(m,set(match))
    values.append({'name':label,'structure':s,'external_components':external})
assert [len(x['external_components'][0]['core_boundary_bonds']) for x in values]==[1,2,1]
report['cases'].append({'case':'相同苯环子图可能对应单点取代或额外稠合环','examples':values})

reactants='[CH3:1][N+:2]#[C-:3].[CH3:4][Br:5].[OH2:6]'
product='[CH3:1][NH:2][C:3](=[O:6])[CH3:4]'
rs=[mol(x) for x in reactants.split('.')]; p=mol(product)
source={a.GetAtomMapNum():i+1 for i,m in enumerate(rs) for a in m.GetAtoms()}
def bonds(m):
    """返回按原子映射号对索引的键型字典，供受控示例比较端点图变化。"""
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

# 整体指纹排序可能使体量相近的候选集中在某一个 R 位点。
# 这里使用人工构造的结构，不是真实反应先例。
target_smiles = 'CCOC(=O)c1cc(NC(=O)c2ccc(F)cc2)ccc1OCCN(C)C'
target = mol(target_smiles)
generator = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
target_fp = generator.GetFingerprint(target)
head_query = Chem.MolFromSmarts('CCOC(=O)c1cc(NC(=O)c2ccc(F)cc2)ccc1O')
tail_query = Chem.MolFromSmarts('CCOC(=O)c1cc(N)ccc1[O]-[CH2]-[CH2]-[NX3]([CH3])[CH3]')
candidates = []
for label, smiles in [
    ('head_1', 'CCOC(=O)c1cc(NC(=O)c2ccc(F)cc2)ccc1OCCN(C)CC'),
    ('head_2', 'CCOC(=O)c1cc(NC(=O)c2ccc(F)cc2)ccc1OCCN(CC)CC'),
    ('head_3', 'CCOC(=O)c1cc(NC(=O)c2ccc(F)cc2)ccc1OCCC'),
    ('tail_1', 'CCOC(=O)c1cc(NC(=O)C2CCCCC2)ccc1OCCN(C)C'),
]:
    molecule = mol(smiles)
    ratio = Descriptors.MolWt(molecule) / Descriptors.MolWt(target)
    assert abs(ratio - 1) < 0.08  # 仅描述本例，不是运行时阈值。
    candidates.append({
        'id': label, 'smiles': smiles, 'molecular_weight_ratio': ratio,
        'similarity': DataStructs.TanimotoSimilarity(target_fp, generator.GetFingerprint(molecule)),
        'head_at_declared_core_position': molecule.HasSubstructMatch(head_query),
        'tail_at_declared_core_position': molecule.HasSubstructMatch(tail_query),
    })
ordered = sorted(candidates, key=lambda row: (-row['similarity'], row['id']))
assert all(row['head_at_declared_core_position'] for row in ordered[:3])
assert not any(row['tail_at_declared_core_position'] for row in ordered[:3])
assert [row['id'] for row in candidates if row['tail_at_declared_core_position']] == ['tail_1']
report['cases'].append({
    'case': '近体量的整体相似前列可能遗漏另一目标支链', 'illustration_only': True,
    'target': target_smiles, 'candidates': ordered, 'illustrative_top_k': 3,
    'top_k_tail_coverage': False, 'declared_tail_query_finds_reference_structure': True,
    'note': 'Only structural coverage is checked; no reaction evidence, child-family compiler or scheduler tested.',
})

# 不同映射可能分别覆盖不同的目标 R 位点；即使都来自同一个来源分子，
# 它们的位点并集也不能当作同一次映射下的联合见证。
coverage_target = mol('COc1cc(OC)cc(OC)c1')
coverage_core = Chem.MolFromSmarts('c1ccccc1')
methoxy_query = Chem.MolFromSmarts('[c]-[O;X2;+0]-[C;H3;X4;+0]')
target_core = coverage_target.GetSubstructMatch(coverage_core)
target_branches = {match[0]: match[1:] for match in coverage_target.GetSubstructMatches(methoxy_query)}
target_sites = {position + 1 for position, atom in enumerate(target_core) if atom in target_branches}
assert target_sites == {1, 3, 5}
coverage_examples = []
for name, smiles, expected_joint_sites in [
    ('one_methoxy', 'COc1ccccc1', 1),
    ('two_meta_methoxy', 'COc1cccc(OC)c1', 2),
    ('three_alternating_methoxy', 'COc1cc(OC)cc(OC)c1', 3),
]:
    molecule = mol(smiles)
    branches = {match[0]: match[1:] for match in molecule.GetSubstructMatches(methoxy_query)}
    embeddings = molecule.GetSubstructMatches(coverage_core, uniquify=False, maxMatches=129)
    assert len(embeddings) == 12  # 枚举这个受控六元核心的所有映射。
    witnesses = []
    for embedding in embeddings:
        atom_mapping = dict(zip(target_core, embedding))
        covered_sites = set()
        for position, target_atom in enumerate(target_core, 1):
            source_atom = atom_mapping[target_atom]
            if target_atom in target_branches and source_atom in branches:
                covered_sites.add(position)
                atom_mapping.update(zip(target_branches[target_atom], branches[source_atom]))
        assert len(atom_mapping) == len(set(atom_mapping.values()))
        assert len(atom_mapping) == 6 + 2 * len(covered_sites)
        witnesses.append({'sites': covered_sites, 'atom_mapping': atom_mapping})
    site_union = set().union(*(w['sites'] for w in witnesses))
    atom_union = set().union(*(set(w['atom_mapping']) for w in witnesses))
    best = max(witnesses, key=lambda w: (len(w['sites']), tuple(sorted(w['sites']))))
    assert site_union == target_sites
    assert len(atom_union) == coverage_target.GetNumHeavyAtoms() == 12
    assert len(best['sites']) == expected_joint_sites
    assert len(best['atom_mapping']) == 6 + 2 * expected_joint_sites
    # 原子重编号会改变局部索引，不应改变能够获得的覆盖计数。
    renumbered = Chem.RenumberAtoms(molecule, list(reversed(range(molecule.GetNumAtoms()))))
    renumbered_sites = {match[0] for match in renumbered.GetSubstructMatches(methoxy_query)}
    renumbered_masks = [
        {position + 1 for position, atom in enumerate(match)
         if position + 1 in target_sites and atom in renumbered_sites}
        for match in renumbered.GetSubstructMatches(coverage_core, uniquify=False, maxMatches=129)
    ]
    assert max(map(len, renumbered_masks)) == expected_joint_sites
    coverage_examples.append({
        'id': name, 'source_smiles': smiles, 'source_heavy_atoms': molecule.GetNumHeavyAtoms(),
        'core_embedding_count': len(embeddings),
        'alternative_site_sets': sorted({tuple(sorted(w['sites'])) for w in witnesses}),
        'sitewise_union_count': len(site_union), 'site_denominator': len(target_sites),
        'joint_site_count_best_found': len(best['sites']),
        'atom_union_count': len(atom_union), 'atom_denominator': 12,
        'joint_atom_count_best_found': len(best['atom_mapping']),
        'best_found_target_to_source_atoms': sorted(best['atom_mapping'].items()),
        'all_core_embeddings_checked_in_this_fixture': True,
        'renumbering_preserves_joint_count': True,
    })
report['cases'].append({
    'case': '同一来源的替代映射并集不能当作单实例联合覆盖',
    'illustration_only': True, 'target': Chem.MolToSmiles(coverage_target),
    'target_R_sites_in_fixed_core_order': sorted(target_sites), 'examples': coverage_examples,
    'note': 'All three sources give a sitewise union of 3/3, but a single embedding covers 1/3, 2/3 or 3/3. No experimental evidence or production ranking engine is tested.',
})

out=Path(__file__).with_name('reaction_relevance_checks.json')
out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(f'{len(report["cases"])} additional structural/provenance cases passed; RDKit {rdBase.rdkitVersion}.')
