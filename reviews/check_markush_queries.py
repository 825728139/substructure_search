"""Small Markush-query examples, not a production engine or patent interpreter.
Checks generic groups, joint R-site matching, whole substituent predicates,
optional H and additional substitution. No synthetic feasibility is asserted.
"""
from pathlib import Path
import json
from rdkit import Chem,rdBase

def mol(s):
 m=Chem.MolFromSmiles(s);assert m is not None,s
 return m

# Official generic group support is opt-in. ARY is carboaryl, not any ring.
gq=Chem.MolFromSmarts('OC* |$;;ARY$|')
Chem.SetGenericQueriesFromProperties(gq)
params=Chem.SubstructMatchParameters();params.useGenericMatchers=True
generic=[]
for s,want in [('c1ccccc1CO',True),('C1CCCCC1CO',False),('c1ccncc1CO',False)]:
 default=mol(s).HasSubstructMatch(gq)
 actual=mol(s).HasSubstructMatch(gq,params)
 assert default and actual==want
 generic.append({'structure':s,'default_match':default,'generic_ARY_match':actual})

# Illustrative family: para R1-phenylene-O-R2, R1=F/Cl/Br,
# R2 = neutral saturated acyclic C1-C3. Other ring substitutions allowed.
qtext='[F,Cl,Br]-[c:1]1[c:2][c:3][c:4](-[OX2+0]-[#6])[c:5][c:6]1'
q=Chem.MolFromSmarts(qtext)
core_positions=[a.GetIdx() for a in q.GetAtoms() if 1<=a.GetAtomMapNum()<=6]
oxygen_position=next(a.GetIdx() for a in q.GetAtoms() if a.GetAtomicNum()==8)
carbon_position=oxygen_position+1

def evaluate(s):
 m=mol(s); witnesses=[]
 for match in m.GetSubstructMatches(q):
  core={match[i] for i in core_positions}
  oxygen,carbon=match[oxygen_position],match[carbon_position]
  # Traverse the entire R2 outside the fixed core and oxygen. Returning to a
  # second core attachment is excluded for this single-attachment example.
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
# Optional H is a declared alternative, not assumed from a wildcard atom.
oh=Chem.MolFromSmarts('[F,Cl,Br]-c1ccc([OX2H1+0])cc1')
assert mol('Oc1ccc(F)cc1').HasSubstructMatch(oh)
assert not evaluate('Oc1ccc(F)cc1')['family_match']
# Explicitly locking otherwise free ring positions is an additional constraint.
locked=Chem.MolFromSmarts('[F,Cl,Br]-c1[cH][cH]c(-[OX2+0]-[#6])[cH][cH]1')
assert not mol('COc1ccc(F)c(C)c1').HasSubstructMatch(locked)
assert evaluate('COc1ccc(F)c(C)c1')['family_match']
result={'scope':'illustrative query checks only; no generalized compiler, reaction evidence or exhaustive sidechain space tested',
        'rdkit_version':rdBase.rdkitVersion,'query':qtext,'generic_group_cases':generic,
        'joint_family_cases':rows,'explicit_optional_H_check':True,'explicit_extra_site_lock_check':True}
Path(__file__).with_name('markush_query_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(f'{len(generic)} generic-group + {len(rows)} joint-family + 2 explicit-option checks passed.')
