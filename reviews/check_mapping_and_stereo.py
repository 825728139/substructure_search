"""Mapping representation checks, not chemical feasibility tests.
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
    # This small helper is intentionally limited to unique, positive maps.
    # Raw set differences below are not a production reaction classifier.
    labels=[a.GetAtomMapNum() for a in m.GetAtoms()]
    if any(label<=0 for label in labels) or len(set(labels))!=len(labels):
        raise ValueError('This example helper requires unique positive atom maps.')
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
# Omitted coproduct atoms are not evidence that every internal bond broke.
ester = mol('[CH3:1][C:2](=[O:3])[O:6][CH2:7][CH2:8][CH3:9].[NH2:4][CH3:5]')
amide = mol('[CH3:1][C:2](=[O:3])[NH:4][CH3:5]')
alcohol = mol('[OH:6][CH2:7][CH2:8][CH3:9]')
major_only = edits(ester, amide)
with_coproduct = edits(ester, Chem.CombineMols(amide, alcohol))
assert major_only['broken'] == [(2, 6), (6, 7), (7, 8), (8, 9)]
assert with_coproduct['broken'] == [(2, 6)]
assert major_only['formed'] == with_coproduct['formed'] == [(2, 4)]
report['cases'].append({
    'case': '只列主产物时不能把消失片段内部键都算作断键',
    'illustration_only': True,
    'mapped_inputs': Chem.MolToSmiles(ester), 'reported_main_product': Chem.MolToSmiles(amide),
    'illustrated_coproduct': Chem.MolToSmiles(alcohol),
    'raw_difference_main_only': major_only, 'raw_difference_with_coproduct': with_coproduct,
    'note': 'The coproduct is supplied only to demonstrate representation dependence, not inferred from source evidence.',
})

# Multiple unlabelled atoms all return zero, but retain distinct local IDs.
partial = mol('[CH3:1][C:2](=[O:3])OCCC.[NH2:4][CH3:5]')
unmapped_edges = [b.GetIdx() for b in partial.GetBonds()
                  if not b.GetBeginAtom().GetAtomMapNum() and not b.GetEndAtom().GetAtomMapNum()]
naive_zero_keys = {tuple(sorted((b.GetBeginAtom().GetAtomMapNum(), b.GetEndAtom().GetAtomMapNum())))
                   for b in partial.GetBonds() if b.GetIdx() in unmapped_edges}
assert len(unmapped_edges) == 3 and naive_zero_keys == {(0, 0)}
try:
    bonds(partial)
except ValueError:
    pass
else:
    raise AssertionError('Unmapped labels must not enter the positive-map example helper.')
report['cases'].append({
    'case': 'map零不是公共原子身份', 'illustration_only': True,
    'structure': Chem.MolToSmiles(partial), 'unmapped_internal_bond_indices': unmapped_edges,
    'actual_local_bond_count': len(unmapped_edges), 'naive_map_key_count': len(naive_zero_keys),
    'note': 'Use local atom references; absent mapping is not a cross-side correspondence.',
})

# These small examples use fixed, unique maps to compare contributors without
# exchanging atoms. This is not a general resonance normalizer or classifier.
def nuclear_signature(molecule):
    return (
        tuple(sorted((a.GetAtomMapNum(), a.GetAtomicNum(), a.GetIsotope(),
                      a.GetTotalNumHs(includeNeighbors=True), a.GetNumRadicalElectrons())
                     for a in molecule.GetAtoms())),
        tuple(sorted(bonds(molecule))),
        sum(a.GetFormalCharge() for a in molecule.GetAtoms()),
    )

def controlled_resonance_forms(molecule, normalize_aromaticity=True):
    original = Chem.MolToSmiles(molecule)
    forms = list(Chem.ResonanceMolSupplier(molecule, flags=0, maxStructs=17))
    # Fixture bound only. A limited enumeration is not proof that no other
    # resonance representations exist under other supported rule sets.
    assert 0 < len(forms) < 17
    if normalize_aromaticity:
        # The supplier can emit Kekule bond types even where the input used
        # aromatic bonds. Compare both sides under the same aromaticity policy.
        for form in forms:
            Chem.SanitizeMol(form)
    assert all(nuclear_signature(form) == nuclear_signature(molecule) for form in forms)
    assert Chem.MolToSmiles(molecule) == original
    return forms

def charge_changes(left, right):
    a = {atom.GetAtomMapNum(): atom.GetFormalCharge() for atom in left.GetAtoms()}
    b = {atom.GetAtomMapNum(): atom.GetFormalCharge() for atom in right.GetAtoms()}
    assert a.keys() == b.keys()
    return [{'map': label, 'before': a[label], 'after': b[label]}
            for label in sorted(a) if a[label] != b[label]]

resonance_cases = []
for name, left, right in [
    ('nitro', '[CH3:1][N+:2](=[O:3])[O-:4]', '[CH3:1][N+:2]([O-:3])=[O:4]'),
    ('isotope_labeled_carboxylate', '[CH3:1][C:2](=[18O:3])[O-:4]',
     '[CH3:1][C:2]([18O-:3])=[O:4]'),
]:
    before, after = mol(left), mol(right)
    raw = edits(before, after)
    assert not raw['formed'] and not raw['broken'] and len(raw['order_changes']) == 2
    assert nuclear_signature(before) == nuclear_signature(after)
    left_forms = {Chem.MolToSmiles(f) for f in controlled_resonance_forms(before)}
    right_forms = {Chem.MolToSmiles(f) for f in controlled_resonance_forms(after)}
    common = sorted(left_forms & right_forms)
    assert common
    resonance_cases.append({
        'case': name, 'mapped_forms': [left, right], 'raw_changes': raw,
        'raw_charge_changes': charge_changes(before, after),
        'common_mapped_contributors': common, 'atom_and_isotope_identity_preserved': True,
    })
report['cases'].append({
    'case': '硝基和带同位素羧酸根的共振写法不代表化学转化',
    'illustration_only': True, 'examples': resonance_cases,
    'note': 'A common contributor witnesses these representation relationships; no atom-map or isotope permutation is used.',
})

reaction_before = mol('[O-:1][c:2]1[cH:3][cH:4][c:5]([N+:6](=[O:7])[O-:8])[cH:9][cH:10]1.[CH3:11][I:12]')
reaction_after = mol('[O:1]([c:2]1[cH:3][cH:4][c:5]([N+:6]([O-:7])=[O:8])[cH:9][cH:10]1)[CH3:11].[I-:12]')
raw = edits(reaction_before, reaction_after)
assert raw == {'formed': [(1, 11)], 'broken': [(11, 12)], 'order_changes': [(6, 7), (6, 8)]}
expected = {'formed': [(1, 11)], 'broken': [(11, 12)], 'order_changes': []}
consistent_pairs = []
for form in controlled_resonance_forms(reaction_before, False):
    normalized = Chem.Mol(form)
    Chem.SanitizeMol(normalized)
    assert nuclear_signature(normalized) == nuclear_signature(reaction_before)
    if edits(normalized, reaction_after) == expected:
        consistent_pairs.append((form, normalized))
assert consistent_pairs
emitted, consistent = consistent_pairs[0]
emitted_changes = edits(emitted, reaction_after)
assert len(emitted_changes['order_changes']) == 6
assert [change['map'] for change in charge_changes(reaction_before, reaction_after)] == [1, 7, 8, 12]
assert [change['map'] for change in charge_changes(consistent, reaction_after)] == [1, 12]
report['cases'].append({
    'case': '硝基共振写法不应扩大实际O甲基化的变化区域',
    'illustration_only': True,
    'mapped_reactants': Chem.MolToSmiles(reaction_before),
    'mapped_products': Chem.MolToSmiles(reaction_after),
    'raw_changes': raw, 'consistent_reactant_contributor': Chem.MolToSmiles(consistent),
    'tool_contributor_before_aromatic_normalization': emitted_changes,
    'changes_in_consistent_representation': expected,
    'raw_charge_changes': charge_changes(reaction_before, reaction_after),
    'retained_charge_changes': charge_changes(consistent, reaction_after),
    'note': 'A supplied graph illustration, not an experiment or a minimum-edit classification algorithm. The O-C formation and C-I loss remain.',
})

distinct_cases = []
for name, left, right in [
    ('keto_enol', '[CH3:1][CH:2]=[O:3]', '[CH2:1]=[CH:2][OH:3]'),
    ('protonation', '[CH3:1][C:2](=[O:3])[O-:4]', '[CH3:1][C:2](=[O:3])[OH:4]'),
    ('hydrogenation', '[CH2:1]=[CH:2][CH3:3]', '[CH3:1][CH2:2][CH3:3]'),
]:
    before, after = mol(left), mol(right)
    # Fixed-atom H/charge changes rule out representation-only equivalence;
    # the lack of an intersection by itself would not prove this generally.
    assert nuclear_signature(before) != nuclear_signature(after)
    left_forms = {Chem.MolToSmiles(f) for f in controlled_resonance_forms(before)}
    right_forms = {Chem.MolToSmiles(f) for f in controlled_resonance_forms(after)}
    assert not left_forms & right_forms
    distinct_cases.append({'case': name, 'mapped_forms': [left, right],
                           'same_fixed_atom_H_charge_connectivity': False,
                           'raw_changes': edits(before, after)})
report['cases'].append({
    'case': '互变异构质子化和加氢不因同重原子连接而消除',
    'illustration_only': True, 'examples': distinct_cases,
    'note': 'These distinct structures remain distinct; the graph pairs alone do not establish observed reactions.',
})
Path(__file__).with_name('mapping_and_stereo_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(f'{len(report["cases"])} illustrative mapping/multiplicity/stereo checks passed; RDKit {rdBase.rdkitVersion}.')
