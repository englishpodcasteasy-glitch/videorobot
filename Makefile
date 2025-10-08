.PHONY: setup run test colab-badge-check format lint

setup:
	python -m pip install --upgrade pip
	python -m pip install -r backend/requirements.txt
	python -m pip install pre-commit
	pre-commit install

run:
	python -m backend.main

test:
	python -m compileall backend

format:
	pre-commit run ruff-format --all-files
	pre-commit run black --all-files

lint:
	pre-commit run ruff --all-files

colab-badge-check:
	python - <<'PY'
from pathlib import Path
nb = Path('colab_runner.ipynb')
if not nb.exists():
    raise SystemExit('colab_runner.ipynb missing')
print('colab runner notebook found at', nb.resolve())
PY
