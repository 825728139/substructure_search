.PHONY: install check test serve demo contracts
install:
	uv sync --frozen --python 3.12
check:
	uv run --frozen python scripts/check.py
test:
	uv run --frozen pytest -q
serve:
	uv run --frozen reaction-reference serve
demo:
	uv run --frozen reaction-reference search --target 'CCCNC(=O)c1ccccc1' --output var/demo.json || test $$? -eq 2
contracts:
	uv run --frozen reaction-reference export-schemas --output-dir contracts
