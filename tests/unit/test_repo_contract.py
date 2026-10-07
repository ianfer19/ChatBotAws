"""Verifica la estructura del repositorio y las reglas de dependencia con AST.

Por qué existe: import-linter cubre la dirección de dependencias entre capas, pero
dos reglas necesitan inspeccionar el código con más precisión de la que permiten los
wildcards de contratos: (1) que ningún slice importe a otro y (2) que el `domain/` sea
puro (solo stdlib + pydantic + shared). Este test falla en CI si alguna se rompe.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
SLICES_DIR = SRC / "slices"

SLICES: tuple[str, ...] = (
    "conversation_gateway",
    "supervisor",
    "appointments",
    "orders",
    "knowledge_rag",
    "customer_context",
    "tenant_prompts",
    "sentiment_handoff",
    "abuse_protection",
    "media_handling",
    "retention_archiving",
)

LAYERS: tuple[str, ...] = ("domain", "application", "infrastructure", "handler")

# Raíces permitidas para imports absolutos dentro de domain/ (además de la stdlib).
DOMAIN_ALLOWED_ROOTS: frozenset[str] = frozenset({"shared", "pydantic", "pydantic_settings"})


def _iter_python_files(root: Path) -> list[Path]:
    """Devuelve todos los .py bajo `root`, excluyendo cachés de Python.

    Args:
        root: Carpeta desde la que se recorre.

    Returns:
        Lista ordenada de rutas de archivos Python.
    """
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _module_docstring(path: Path) -> str | None:
    """Lee el docstring de módulo de un archivo Python vía AST.

    Args:
        path: Archivo .py a analizar.

    Returns:
        El docstring del módulo o `None` si no tiene uno o no es analizable.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None
    return ast.get_docstring(tree)


def _resolved_import(stmt: ast.ImportFrom, file_path: Path) -> str:
    """Resuelve un `from ... import ...` a un path absoluto con puntos.

    Args:
        stmt: Nodo ImportFrom a resolver.
        file_path: Archivo fuente del import (para resolver imports relativos).

    Returns:
        Ruta del módulo destino con puntos (p. ej. `slices.orders.domain`).
    """
    rel = file_path.relative_to(SRC)
    parts = list(rel.parts[:-1])
    if stmt.level > 1:
        parts = parts[: len(parts) - (stmt.level - 1)]
    if stmt.module:
        parts.extend(stmt.module.split("."))
    return ".".join(parts)


def _imports_of(file_path: Path) -> list[tuple[str, bool]]:
    """Extrae todos los destinos de import de un archivo como (ruta, es_relativo).

    Args:
        file_path: Archivo .py a analizar.

    Returns:
        Lista de rutas absolutas resueltas y si originalmente era relativo.
    """
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    found: list[tuple[str, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, False) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.append((_resolved_import(node, file_path), node.level > 0))
    return found


def test_todos_los_paquetes_src_tienen_docstring_de_responsabilidad() -> None:
    """Todo directorio bajo `src/` debe ser un paquete con `__init__.py` documentado.

    Por qué: el docstring es la "responsabilidad" del paquete; el test de estructura
    impide carpetas huérfanas (criterio de aceptación de la Fase 1).
    """
    dirs = [
        p
        for p in SRC.rglob("*")
        if p.is_dir() and "__pycache__" not in p.parts and not p.name.endswith(".egg-info")
    ]
    assert dirs, "src/ no contiene paquetes: la estructura no se creó"
    missing: list[str] = []
    undocumented: list[str] = []
    for directory in dirs:
        init = directory / "__init__.py"
        if not init.is_file():
            missing.append(str(directory.relative_to(REPO_ROOT)))
            continue
        if not (_module_docstring(init) or "").strip():
            undocumented.append(str(directory.relative_to(REPO_ROOT)))
    assert not missing, f"paquetes sin __init__.py: {missing}"
    assert not undocumented, f"__init__.py sin docstring de responsabilidad: {undocumented}"


def test_cada_slice_tiene_estructura_y_agents_md() -> None:
    """Cada slice tiene AGENTS.md y sus 4 capas con paquetes documentados.

    Por qué: el AGENTS.md del slice es su contrato funcional; sin él, una IA o un
    humano no puede trabajar en la carpeta siguiendo solo la documentación.
    """
    problems: list[str] = []
    for slice_name in SLICES:
        slice_dir = SLICES_DIR / slice_name
        if not slice_dir.is_dir():
            problems.append(f"falta la carpeta del slice {slice_name}")
            continue
        agents = slice_dir / "AGENTS.md"
        if not agents.is_file() or agents.stat().st_size < 400:
            problems.append(f"{slice_name}: falta AGENTS.md (o es demasiado breve)")
        for layer in LAYERS:
            init = slice_dir / layer / "__init__.py"
            if not init.is_file() or not (_module_docstring(init) or "").strip():
                problems.append(f"{slice_name}/{layer}: falta __init__.py documentado")
    assert not problems, "estructura incompleta:\n" + "\n".join(problems)


def test_los_slices_no_se_importan_entre_si() -> None:
    """Ningún módulo de un slice puede importar módulos de otro slice.

    Por qué: la comunicación entre slices ocurre solo vía `shared/contracts`;
    los imports cruzados acoplan funcionalidades que deben evolucionar por separado.
    """
    violations: list[str] = []
    for slice_name in SLICES:
        for file_path in _iter_python_files(SLICES_DIR / slice_name):
            for target, _is_relative in _imports_of(file_path):
                if not target.startswith("slices."):
                    continue
                parts = target.split(".")
                if len(parts) < 2:
                    continue
                if parts[1] != slice_name:
                    violations.append(f"{file_path.relative_to(REPO_ROOT)} importa {target}")
    assert not violations, "imports entre slices prohibidos:\n" + "\n".join(violations)


def test_domain_es_puro() -> None:
    """El `domain/` de cada slice solo importa stdlib, pydantic y shared.

    Por qué: el dominio es lo único estable del sistema; si importa AWS, HTTP,
    framework o capas superiores, la regla de dependencia se degrada en silencio.
    """
    violations: list[str] = []
    for slice_name in SLICES:
        domain_dir = SLICES_DIR / slice_name / "domain"
        if not domain_dir.is_dir():
            violations.append(f"{slice_name}: falta domain/")
            continue
        for file_path in _iter_python_files(domain_dir):
            for target, is_relative in _imports_of(file_path):
                root_module = target.split(".")[0]
                if is_relative:
                    # Los imports relativos deben permanecer dentro de <slice>.domain
                    if not target.startswith(f"slices.{slice_name}.domain"):
                        violations.append(
                            f"{file_path.relative_to(REPO_ROOT)} sale de domain con {target}"
                        )
                    continue
                if root_module in sys.stdlib_module_names:
                    continue
                if root_module in DOMAIN_ALLOWED_ROOTS:
                    continue
                violations.append(
                    f"{file_path.relative_to(REPO_ROOT)} importa {target} "
                    f"(raíz no permitida en domain: {root_module})"
                )
    assert not violations, "domain no es puro:\n" + "\n".join(violations)


def test_todos_los_slices_estan_en_los_contratos_de_import_linter() -> None:
    """Cada slice debe aparecer en los `containers` de los contratos `layers`.

    Por qué: import-linter no admite wildcards en capas, así que los contratos
    listan los contenedores a mano; olvidar uno dejaría ese slice sin verificar.
    """
    import tomllib

    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = config["tool"]["importlinter"]["contracts"]
    layers_contracts = [c for c in contracts if c.get("type") == "layers"]
    assert layers_contracts, "no hay contratos layers en pyproject.toml"
    missing: list[str] = []
    for slice_name in SLICES:
        for contract in layers_contracts:
            containers = contract.get("containers", [])
            if f"slices.{slice_name}" not in containers:
                missing.append(f"{slice_name} -> {contract['name']}")
    assert not missing, "slices sin registrar en import-linter:\n" + "\n".join(missing)


def test_enlaces_locales_de_agents_md_existen() -> None:
    """Todos los enlaces relativos de los AGENTS.md apuntan a archivos existentes.

    Por qué: AGENTS.md es la fuente única de verdad; un enlace roto rompe la
    navegación de humanos y de IAs.
    """
    broken: list[str] = []
    for agents_md in sorted(REPO_ROOT.rglob("AGENTS.md")):
        if ".git" in agents_md.parts:
            continue
        text = agents_md.read_text(encoding="utf-8")
        for match in re.finditer(r"\]\(([^)]+)\)", text):
            target = match.group(1)
            if target.startswith(("http://", "https://", "#")):
                continue
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue
            resolved = (agents_md.parent / path_part).resolve()
            if not resolved.exists():
                broken.append(f"{agents_md.relative_to(REPO_ROOT)} -> {target}")
    assert not broken, "enlaces rotos:\n" + "\n".join(broken)
