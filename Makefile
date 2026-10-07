# Atajos locales. En CI los mismos pasos viven en .github/workflows/.
# Equivalencias en Windows (PowerShell) en AGENTS.md -> "Comandos".

.PHONY: install lint fmt typecheck test verify-deps verify tf-fmt tf-validate

install:
	pip install -e ".[dev]"

lint:
	ruff check src tests
	ruff format --check src tests

fmt:
	ruff format src tests
	ruff check --fix src tests

typecheck:
	mypy

test:
	pytest

# Regla de dependencia entre capas (handler -> application -> domain, etc.)
verify-deps:
	lint-imports

verify: lint typecheck test verify-deps

tf-fmt:
	terraform fmt -check -recursive infra

tf-validate:
	@for d in infra/envs/*/; do \
		if ls "$$d"*.tf >/dev/null 2>&1; then \
			terraform -chdir="$$d" init -backend=false -input=false; \
			terraform -chdir="$$d" validate; \
		fi; \
	done
