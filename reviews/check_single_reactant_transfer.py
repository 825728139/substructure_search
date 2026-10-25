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
def canonical(smiles):
 m=Chem.MolFromSmiles(smiles)
 assert m is not None
 return Chem.MolToSmiles(m,isomericSmiles=True)
def replay(a,b):
 products=[]
 for group in rxn.RunReactants((Chem.MolFromSmiles(a),Chem.MolFromSmiles(b))):
  product=group[0];Chem.SanitizeMol(product)
  products.append(Chem.MolToSmiles(product,isomericSmiles=True))
 return {'raw_count':len(products),'unique_products':sorted(set(products))}
def contains(result,target):return canonical(target) in result['unique_products']
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
report={'scope':'invented structural replay examples only; no experimental evidence or condition prediction','rdkit_version':rdBase.rdkitVersion,'rule':rule,'cases':rows}
Path(__file__).with_name('single_reactant_transfer_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(f'{len(rows)} illustrative replay cases checked; no experimental success or general precursor generator tested.')
