"""Demonstrate query semantics, not an implemented retrieval compiler."""
from pathlib import Path
import json
from rdkit import Chem, rdBase
plain = Chem.MolFromSmiles('CCO')
explicit_oh = Chem.MolFromSmarts('[C]-[C]-[OX2H1+0]')
rows=[]
for smiles, expected in [('CCO', True), ('CC[O-]', False), ('CCOC', False)]:
    mol=Chem.MolFromSmiles(smiles)
    actual=mol.HasSubstructMatch(explicit_oh)
    assert actual == expected
    assert mol.HasSubstructMatch(plain)
    rows.append({'candidate':smiles,'plain_molecule_query':True,'explicit_oh_query':actual})
result={'rdkit_version':rdBase.rdkitVersion,'scope':'oxygen_predicate_example_only','query':'[C]-[C]-[OX2H1+0]','checks':rows}
Path(__file__).with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print('3 query-semantics cases verified.')
