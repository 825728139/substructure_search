"""Illustrative reaction-graph replay, not a feasibility or condition predictor.
The rule, source reaction, replacements and expected outcomes are invented
examples. This is not an implementation of reactant-delta attribution.
"""
from pathlib import Path
import json
from rdkit import Chem, rdBase
from rdkit.Chem import rdChemReactions

rule='[C:1](=[O:2])([Cl])-[c:5].[N;H2;+0;!$(N-C=O):3]-[C:4]>>[C:1](=[O:2])(-[NH:3]-[C:4])-[c:5]'
rxn=rdChemReactions.ReactionFromSmarts(rule)
acid='O=C(Cl)c1ccccc1'
amine='CCN'
source='CCNC(=O)c1ccccc1'
def as_mol(value):
 m=Chem.MolFromSmiles(value) if isinstance(value,str) else Chem.Mol(value)
 assert m is not None
 return m
def canonical(value):
 m=as_mol(value)
 for atom in m.GetAtoms(): atom.SetAtomMapNum(0)
 return Chem.MolToSmiles(m,isomericSmiles=True)
def replay(a,b,reaction=rxn,product_set_limit=16):
 assert product_set_limit>0
 groups=reaction.RunReactants((as_mol(a),as_mol(b)),maxProducts=product_set_limit+1)
 product_sets=[];raw_sets=[]
 # These controlled examples expect valid products. A production executor
 # must record failed validation per group, rather than silently skip it.
 for group in groups[:product_set_limit]:
  for product in group: Chem.SanitizeMol(product)
  raw_sets.append([Chem.MolToSmiles(product,isomericSmiles=True) for product in group])
  product_sets.append([canonical(product) for product in group])
 return {'raw_count':len(groups),'evaluated_set_count':len(product_sets),
         'enumeration_complete':len(groups)<=product_set_limit,
         'validation_complete':True,'validation_scope':'evaluated_product_sets',
         'raw_product_sets':raw_sets,'product_sets':product_sets,
         'unique_products':sorted({p for group in product_sets for p in group})}
def contains(result,target):
 # Membership of one concrete target only; never combine different groups.
 return any(canonical(target) in group for group in result['product_sets'])
rows=[]
baseline=replay(acid,amine)
assert contains(baseline,source)
rows.append({'id':'source_replay','reactants':[acid,amine],'result':baseline,'target':source,'exact_graph_match':True})
side_target='CCCNC(=O)c1ccccc1'
side=replay(acid,'CCCN');assert contains(side,side_target)
rows.append({'id':'replace_sidechain_donor','reactants':[acid,'CCCN'],'changed_reactant_slots':[1],'result':side,'target':side_target,'exact_graph_match':True})
core_target='CCNC(=O)c1ccc(F)cc1'
core=replay('O=C(Cl)c1ccc(F)cc1',amine);assert contains(core,core_target)
rows.append({'id':'replace_core_donor','reactants':['O=C(Cl)c1ccc(F)cc1',amine],'changed_reactant_slots':[0],'result':core,'target':core_target,'exact_graph_match':True})
double_target='CCCNC(=O)c1ccc(F)cc1'
both=replay('O=C(Cl)c1ccc(F)cc1','CCCN')
assert not contains(side,double_target) and not contains(core,double_target) and contains(both,double_target)
rows.append({'id':'two_source_changes_not_single','target':double_target,'side_only_matches':False,'core_only_matches':False,'both_result':both,'changed_reactant_slots':[0,1]})
competitive=replay(acid,'NCCN')
assert contains(competitive,'NCCNC(=O)c1ccccc1')
assert competitive['raw_count']==2 and len(competitive['unique_products'])==1
rows.append({'id':'extra_reactive_site_despite_exact_graph','reactants':[acid,'NCCN'],'result':competitive,'note':'Equivalent first-acylation matches do not prove monoacylation selectivity, conditions or absence of further reaction.'})
wrong_handle=replay(acid,'CC(=O)N');assert wrong_handle['raw_count']==0
rows.append({'id':'amine_role_changed_to_amide','result':wrong_handle,'note':'Excluded by this illustrative rule; no claim of general chemical impossibility.'})
wrong_position=replay('O=C(Cl)c1ccccc1F',amine)
assert not contains(wrong_position,core_target)
rows.append({'id':'same_formula_wrong_ring_position','result':wrong_position,'target':core_target,'exact_graph_match':False})
hydrolysis_rule='[C:1](=[O:2])[O:3][CH2:4][c:5].[OH2:6]>>[C:1](=[O:2])[OH:6].[OH:3][CH2:4][c:5]'
hydrolysis=rdChemReactions.ReactionFromSmarts(hydrolysis_rule)
alcohol_target='OCc1ccccc1'
multi=replay('CC(=O)OCc1ccccc1','O',reaction=hydrolysis)
assert len(multi['product_sets'])==1 and len(multi['product_sets'][0])==2
native_one=hydrolysis.RunReactants((as_mol('CC(=O)OCc1ccccc1'),as_mol('O')),maxProducts=1)
assert len(native_one)==1 and len(native_one[0])==2
assert multi['product_sets'][0][0]!=canonical(alcohol_target) and contains(multi,alcohol_target)
reordered_rule='[C:1](=[O:2])[O:3][CH2:4][c:5].[OH2:6]>>[OH:3][CH2:4][c:5].[C:1](=[O:2])[OH:6]'
reordered=replay('CC(=O)OCc1ccccc1','O',reaction=rdChemReactions.ReactionFromSmarts(reordered_rule))
assert contains(reordered,alcohol_target)
assert sorted(multi['product_sets'][0])==sorted(reordered['product_sets'][0])
rows.append({'id':'target_is_second_product','rule':hydrolysis_rule,'target':alcohol_target,
             'result':multi,'reordered_result':reordered,
             'native_max_products_1_returned_sets':len(native_one),
             'molecules_in_that_set':len(native_one[0]),
             'note':'Product ordering is not a main-product label; the water is a reagent, not a synthesis target.'})

mapped_acid,mapped_amine=as_mol(acid),as_mol(amine)
for offset,molecule in enumerate((mapped_acid,mapped_amine),start=1):
 for atom in molecule.GetAtoms(): atom.SetAtomMapNum(offset*100+atom.GetIdx())
mapped=replay(mapped_acid,mapped_amine)
assert any(a.GetAtomMapNum() for a in Chem.MolFromSmiles(mapped['raw_product_sets'][0][0]).GetAtoms())
assert mapped['raw_product_sets'][0][0]!=canonical(source) and contains(mapped,source)
assert all(a.GetAtomMapNum()>0 for m in (mapped_acid,mapped_amine) for a in m.GetAtoms())
rows.append({'id':'mapped_input_identity_comparison','mapped_inputs':[Chem.MolToSmiles(mapped_acid),Chem.MolToSmiles(mapped_amine)],
             'target':source,'result':mapped,'note':'Mapped inputs and raw product strings are retained; full atom provenance projection is not implemented by this probe.'})

limited=replay(acid,'NCCN',product_set_limit=1)
assert limited['raw_count']==2 and limited['evaluated_set_count']==1
assert len(limited['unique_products'])==1 and not limited['enumeration_complete']
assert contains(limited,'NCCNC(=O)c1ccccc1')
rows.append({'id':'duplicate_results_do_not_remove_truncation','evaluated_limit':1,'result':limited,
             'note':'A target witness exists in checked output; duplicate output identities do not prove enumeration complete.'})

report={'scope':'invented structural replay examples only; no experimental evidence or condition prediction','rdkit_version':rdBase.rdkitVersion,'rule':rule,'cases':rows}
Path(__file__).with_name('single_reactant_transfer_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(f'{len(rows)} illustrative replay cases checked; no experimental success or general precursor generator tested.')
