"""Check current design artifacts; this does not test a retrieval engine."""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
files = sorted(ROOT.glob("*.md"))
for directory in ("design", "reviews"):
    files.extend(sorted((ROOT / directory).rglob("*.md")))

for path in files:
    content = path.read_text()
    assert content.count("```") % 2 == 0, f"Unbalanced fences: {path}"
    for ref in re.findall(r"\]\(([^)]+)\)", content):
        if ref.startswith(("https://", "http://", "#")):
            continue
        target = ref.split("#", 1)[0]
        assert (path.parent / target).is_file(), f"Broken link: {path}: {ref}"

spec = (ROOT / "design" / "specification.md").read_text()
sections = re.findall(r"^### (\d+\.\d+) ", spec, re.MULTILINE)
assert len(sections) == len(set(sections)), "Duplicate detailed section number"
for ref in re.findall(r"第 (\d+\.\d+) 节", spec):
    assert ref in sections, f"Missing section {ref}"

json_files = []
for directory in ("design", "reviews"):
    json_files.extend((ROOT / directory).glob("*.json"))
for path in json_files:
    json.loads(path.read_text())

svgs = list((ROOT / "diagrams").glob("*.svg"))
for svg in svgs:
    ET.parse(svg)

print(
    f"Integrity checked: {len(files)} Markdown files, {len(json_files)} JSON files "
    f"and {len(svgs)} diagram SVGs. No engine claims validated."
)
