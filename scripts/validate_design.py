"""Check design artifact integrity; this does not test a retrieval engine."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET
root=Path(__file__).resolve().parents[1]
files=[root/'plan.md',root/'chemical_review.md',root/'GIT_HISTORY.md']
for directory in ('reviews','audits','design'):
    files.extend((root/directory).glob('**/*.md'))
for p in files:
    text=p.read_text()
    assert text.count('```')%2==0, f'Unbalanced fences: {p}'
    for ref in re.findall(r'\]\(([^)]+)\)',text):
        if ref.startswith(('https://','http://','#')): continue
        target=ref.split('#',1)[0]
        assert (p.parent/target).is_file(),f'Broken link: {p}: {ref}'
spec=root/'design/specification.md'
text=(spec if spec.exists() else root/'plan.md').read_text()
sections=re.findall(r'^### (\d+\.\d+) ',text,re.M)
assert len(sections)==len(set(sections)), 'Duplicate detailed section number'
for ref in re.findall(r'第 (\d+\.\d+) 节',text):
    assert ref in sections, f'Missing section {ref}'
for svg in (root/'diagrams').glob('*.svg'): ET.parse(svg)
print(f'Integrity checked: {len(files)} Markdown files and 5 diagram SVGs. No engine claims validated.')
