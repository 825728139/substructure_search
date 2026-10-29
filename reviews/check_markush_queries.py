"""用小型 Markush 查询示例验证语义；本脚本不是正式检索引擎或专利通式解析器。
检查通用基团、多 R 位点联合匹配、完整取代基条件、
可选氢和额外取代；这些核验不证明合成可行性。
"""
from pathlib import Path
import json
from rdkit import Chem,rdBase

def mol(s):
 """将示例 SMILES 解析为 RDKit 分子；解析失败触发断言，返回有效分子。"""
 m=Chem.MolFromSmiles(s);assert m is not None,s
 return m

# RDKit 的通用基团匹配需要显式启用；ARY 表示碳芳基，不代表任意环。
gq=Chem.MolFromSmarts('OC* |$;;ARY$|')
Chem.SetGenericQueriesFromProperties(gq)
params=Chem.SubstructMatchParameters();params.useGenericMatchers=True
generic=[]
for s,want in [('c1ccccc1CO',True),('C1CCCCC1CO',False),('c1ccncc1CO',False)]:
 default=mol(s).HasSubstructMatch(gq)
 actual=mol(s).HasSubstructMatch(gq,params)
 assert default and actual==want
 generic.append({'structure':s,'default_match':default,'generic_ARY_match':actual})

# 示例家族：对位 R1-亚苯基-O-R2，其中 R1 为 F、Cl 或 Br。
# R2 限于中性、饱和、无环的 C1～C3 烷基；允许环上其他位置有取代。
qtext='[F,Cl,Br]-[c:1]1[c:2][c:3][c:4](-[OX2+0]-[#6])[c:5][c:6]1'
q=Chem.MolFromSmarts(qtext)
core_positions=[a.GetIdx() for a in q.GetAtoms() if 1<=a.GetAtomMapNum()<=6]
oxygen_position=next(a.GetIdx() for a in q.GetAtoms() if a.GetAtomicNum()==8)
carbon_position=oxygen_position+1

def evaluate(s):
 """核验示例核心与完整 R2 烷基组成、长度和连接边界，返回原始命中、家族命中及合法见证。"""
 m=mol(s) if isinstance(s,str) else Chem.Mol(s); witnesses=[]
 for match in m.GetSubstructMatches(q):
  core={match[i] for i in core_positions}
  oxygen,carbon=match[oxygen_position],match[carbon_position]
  # 从固定核心与氧原子之外遍历完整 R2 支链。
  # 本例只允许单点连接，若支链返回核心的第二个位点则不匹配。
  seen=set();stack=[carbon];valid=True
  while stack:
   i=stack.pop()
   if i in seen:continue
   seen.add(i);a=m.GetAtomWithIdx(i)
   if not (a.GetAtomicNum()==6 and not a.GetIsAromatic() and not a.IsInRing()
           and a.GetFormalCharge()==0 and a.GetNumRadicalElectrons()==0):
    valid=False
   for b in a.GetBonds():
    j=b.GetOtherAtomIdx(i)
    # 烷基组成和长度按重原子定义；普通氢和氘仍保留在原分子中，
    # 供同位素及完整目标要求的独立检查使用。
    if m.GetAtomWithIdx(j).GetAtomicNum()==1:continue
    if j==oxygen:
     if i!=carbon:valid=False
     continue
    if j in core:valid=False;continue
    if b.GetBondType()!=Chem.BondType.SINGLE:valid=False
    if j not in seen:stack.append(j)
  if valid and 1<=len(seen)<=3:
   witnesses.append({'R1':m.GetAtomWithIdx(match[0]).GetSymbol(),
                     'R2_carbon_count':len(seen),'R2_atoms':sorted(seen),
                     'core_atoms':[match[i] for i in core_positions],
                     'source_structure':Chem.MolToSmiles(m)})
 return {'raw_skeleton_match':m.HasSubstructMatch(q),'family_match':bool(witnesses),'witnesses':witnesses}

family_cases=[
 ('F_methoxy','COc1ccc(F)cc1',True),
 ('Cl_ethoxy','CCOc1ccc(Cl)cc1',True),
 ('Br_propoxy','CCCOc1ccc(Br)cc1',True),
 ('branched_C3','CC(C)Oc1ccc(F)cc1',True),
 ('H_requires_explicit_option','Oc1ccc(F)cc1',False),
 ('wrong_relative_position','COc1cccc(F)c1',False),
 ('heteroatom_inside_R2','COCCOc1ccc(F)cc1',False),
 ('motifs_split_across_molecules','COc1ccccc1.Fc1ccccc1',False),
 ('additional_unlocked_substituent','COc1ccc(F)c(C)c1',True),
 ('aryl_not_alkyl','c1ccc(Oc2ccc(F)cc2)cc1',False),
 ('outside_C3_limit','CCCCOc1ccc(F)cc1',False),
]
rows=[]
for name,s,want in family_cases:
 result=evaluate(s);assert result['family_match']==want,(name,result)
 rows.append({'case':name,'structure':s,**result})
# 可选氢必须明确声明为另一种取值，不能从通配原子自动推定。
oh=Chem.MolFromSmarts('[F,Cl,Br]-c1ccc([OX2H1+0])cc1')
assert mol('Oc1ccc(F)cc1').HasSubstructMatch(oh)
assert not evaluate('Oc1ccc(F)cc1')['family_match']
# 将原本自由的环上位点明确锁定，是额外增加的查询限制。
locked=Chem.MolFromSmarts('[F,Cl,Br]-c1[cH][cH]c(-[OX2+0]-[#6])[cH][cH]1')
assert not mol('COc1ccc(F)c(C)c1').HasSubstructMatch(locked)
assert evaluate('COc1ccc(F)c(C)c1')['family_match']

# 普通氢采用显式或隐式表示，不应改变该家族的匹配分类。
# 同时检查反例，保证跳过氢计数时没有放宽杂原子、环和大小限制。
hydrogen_representation_cases=[]
for name,smiles,want in family_cases:
 implicit=mol(smiles)
 explicit=Chem.AddHs(implicit)
 implicit_result=evaluate(implicit)
 explicit_result=evaluate(explicit)
 assert implicit_result['family_match']==explicit_result['family_match']==want,name
 assert {w['R2_carbon_count'] for w in implicit_result['witnesses']}=={
     w['R2_carbon_count'] for w in explicit_result['witnesses']},name
 hydrogen_representation_cases.append({
     'case':name,'implicit_H_match':implicit_result['family_match'],
     'explicit_H_match':explicit_result['family_match']})

# 该家族不限制同位素；氘不是非碳重原子。
# 满足烷基类别，不等于已满足另行指定的同位素分布要求。
deuterated=mol('[2H]COc1ccc(F)cc1')
deuterated_result=evaluate(deuterated)
assert deuterated_result['family_match']
assert {w['R2_carbon_count'] for w in deuterated_result['witnesses']}=={1}
assert any(a.GetAtomicNum()==1 and a.GetIsotope()==2 for a in deuterated.GetAtoms())
assert all('[2H]' in w['source_structure'] for w in deuterated_result['witnesses'])

hydroxyl_representation_cases=[]
for smiles,want in [('Oc1ccc(F)cc1',1),('COc1ccc(F)cc1',0)]:
 default_counts=[];neighbor_inclusive_counts=[];oh_matches=[]
 for molecule in (mol(smiles),Chem.AddHs(mol(smiles))):
  oxygen=next(a for a in molecule.GetAtoms() if a.GetAtomicNum()==8)
  default_counts.append(oxygen.GetTotalNumHs())
  neighbor_inclusive_counts.append(oxygen.GetTotalNumHs(includeNeighbors=True))
  oh_matches.append(molecule.HasSubstructMatch(oh))
 assert neighbor_inclusive_counts==[want,want]
 assert oh_matches==[bool(want),bool(want)]
 hydroxyl_representation_cases.append({
     'smiles':smiles,'default_H_counts':default_counts,
     'neighbor_inclusive_H_counts':neighbor_inclusive_counts,'OH_query_matches':oh_matches})
assert hydroxyl_representation_cases[0]['default_H_counts']==[1,0]

# 当带位置标签的 R 条件在核心查询之后检查时，对称核心映射不再可互换。
# 下面用反例展示：在后过滤之前使用工具默认的原子集合去重，
# 可能产生真实的漏匹配。
symmetric_core = Chem.MolFromSmarts('[c:1]1[c:2][c:3][c:4][c:5][c:6]1')

def labeled_sites_match(molecule, match):
    """在一次固定苯环映射下核验指定位置外接 F 和 Cl，返回是否满足带位置标签的条件。"""
    core_atoms = set(match)
    def exterior_symbols(position):
        """返回当前核心映射中指定位置所连接的核心外原子元素集合。"""
        return {a.GetSymbol() for a in molecule.GetAtomWithIdx(match[position]).GetNeighbors()
                if a.GetIdx() not in core_atoms}
    return 'F' in exterior_symbols(0) and 'Cl' in exterior_symbols(3)

symmetry_cases = []
for smiles in ('Fc1ccc(Cl)cc1', 'Clc1ccc(F)cc1'):
    molecule = mol(smiles)
    defaults = molecule.GetSubstructMatches(symmetric_core)
    complete = molecule.GetSubstructMatches(symmetric_core, uniquify=False, maxMatches=100)
    assert len(defaults) == 1 and len(complete) == 12
    valid = [match for match in complete if labeled_sites_match(molecule, match)]
    assert len(valid) == 2
    symmetry_cases.append({
        'smiles': smiles, 'canonical_smiles': Chem.MolToSmiles(molecule),
        'default_matches': len(defaults),
        'default_postcheck_hit': any(labeled_sites_match(molecule, m) for m in defaults),
        'all_core_mappings': len(complete), 'valid_labeled_assignments': len(valid),
    })
assert symmetry_cases[0]['canonical_smiles'] == symmetry_cases[1]['canonical_smiles']
assert symmetry_cases[0]['default_postcheck_hit']
assert not symmetry_cases[1]['default_postcheck_hit']

molecule = mol('Clc1ccc(F)cc1')
limited = molecule.GetSubstructMatches(symmetric_core, uniquify=False, maxMatches=2)
assert len(limited) == 2 and not labeled_sites_match(molecule, limited[0])
exhausted = molecule.GetSubstructMatches(symmetric_core, uniquify=False, maxMatches=13)
assert len(exhausted) == 12
renumbered = Chem.RenumberAtoms(molecule, list(reversed(range(molecule.GetNumAtoms()))))
assert any(labeled_sites_match(renumbered, m) for m in renumbered.GetSubstructMatches(
    symmetric_core, uniquify=False, maxMatches=100))
enumeration_check = {
    'checked_limit': 1, 'requested_with_sentinel': 2, 'returned': len(limited),
    'witness_in_checked_prefix': False, 'enumeration_complete': False,
    'full_mapping_count': len(exhausted), 'full_witness_found': True,
    'renumbering_preserves_full_match': True,
    'scope': 'RDKit counterexample only; no production scheduler or compiler tested',
}
# 普通子结构包含匹配不会排除已映射核心原子之间的额外边。
# 这些额外内部边不能当作核心外的 R 取代基。
chain_query = Chem.MolFromSmarts('[#6]-[#6]-[#6]')
core_topology_cases = []
for smiles, expected_extra in [('CCC', 0), ('C1CC1', 1), ('CC(C)C', 0)]:
    molecule = mol(smiles)
    match = molecule.GetSubstructMatch(chain_query)
    assert match
    inverse = {atom: position for position, atom in enumerate(match)}
    extra_edges = []
    for bond in molecule.GetBonds():
        begin, end = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        if begin in inverse and end in inverse:
            if chain_query.GetBondBetweenAtoms(inverse[begin], inverse[end]) is None:
                extra_edges.append(sorted((inverse[begin], inverse[end])))
    assert len(extra_edges) == expected_extra
    core_topology_cases.append({
        'smiles': smiles, 'ordinary_containment': True,
        'extra_edges_in_query_positions': extra_edges,
        'scope': 'graph counterexample; policy depends on the declared family',
    })
result={'scope':'illustrative query checks only; no generalized compiler, reaction evidence or exhaustive sidechain space tested',
        'rdkit_version':rdBase.rdkitVersion,'query':qtext,'generic_group_cases':generic,
        'hydrogen_representation_cases':hydrogen_representation_cases,
        'hydroxyl_representation_cases':hydroxyl_representation_cases,
        'deuterated_alkyl_example':{'structure':Chem.MolToSmiles(deuterated),
            'family_match':True,'R2_carbon_count':1,'isotope_requirement_assessed':False},
        'symmetry_postcheck_cases':symmetry_cases,'bounded_enumeration_check':enumeration_check,
        'internal_core_edge_cases':core_topology_cases,
        'joint_family_cases':rows,'explicit_optional_H_check':True,'explicit_extra_site_lock_check':True}
Path(__file__).with_name('markush_query_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(f'{len(generic)} generic-group + {len(rows)} joint-family + 2 explicit-option checks; symmetry, enumeration, core-edge and hydrogen-representation checks passed.')
