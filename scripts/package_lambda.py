"""Construye `artifacts/chatbot.zip`, el desplegable compartido por las Lambdas.

Lambda no ejecuta desde Git: cada función necesita un zip con (1) nuestro código —
`shared/`, `adapters/`, `slices/` y `handlers/` copiados **tal cual** desde `src/`, de
modo que los `handler` de Terraform (`slices.conversation_gateway.handler...`,
`handlers.consumer.main`) resuelvan sobre la raíz del zip — y (2) las librerías de
terceros que el runtime **no** trae (`langgraph`, `requests`, `pydantic`,
`pydantic-settings` y sus transitivas). El `boto3` no se empaqueta: el runtime de
Lambda ya lo incluye (`TODO(verify)`: versión mínima); `psycopg` (Aurora) se excluye a
propósito porque ni el webhook ni el consumer hablan con la base del conocimiento.

Zip único para todas las funciones (decisión de la Fase 7 de despliegue): el código es
el mismo y solo cambia el `handler` de cada una; un zip por función no ahorra lo
suficiente como para mantener dos builds.

Uso (PowerShell, desde la raíz del repo):

    python scripts\\package_lambda.py            # artifacts/chatbot.zip
    python scripts\\package_lambda.py --out ruta.zip

Requiere `pip` accesible desde el mismo intérprete (`sys.executable -m pip`). El
instalado con `--target` va a un directorio temporal que se borra al terminar; el zip
queda típicamente ~50-80 MB sin comprimir (límite de Lambda: 250 MB descomprimido).
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path

# Paquetes de `src/` que van al zip. `handlers` es la composition root (ADR 0014).
_PAQUETES_SRC = ("shared", "adapters", "slices", "handlers")

# Dependencias de runtime a instalar dentro del zip (sin boto3: lo trae Lambda; sin
# psycopg: Aurora no se usa en estas funciones).
_DEPENDENCIAS = (
    "langgraph>=1.2.14",
    "requests>=2.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
)

# Archivos/directorios que nunca se copian al build.
_EXCLUIR = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git"}


def _raiz_repo() -> Path:
    """Devuelve la raíz del repositorio (padre de `scripts/`).

    Returns:
        `Path` absoluto de la raíz del repo.
    """
    return Path(__file__).resolve().parents[1]


def _copiar_codigo(src_dir: Path, destino: Path) -> None:
    """Copia los paquetes de `src/` al directorio de build, sin cachés ni `.pyc`.

    Args:
        src_dir: Directorio `src/` del repo.
        destino: Directorio temporal que recibirá los paquetes.

    Raises:
        FileNotFoundError: Si falta alguno de los paquetes esperados en `src/`.
    """
    for paquete in _PAQUETES_SRC:
        origen = src_dir / paquete
        if not origen.is_dir():
            raise FileNotFoundError(f"falta el paquete {paquete!r} en {src_dir}")
        shutil.copytree(
            origen,
            destino / paquete,
            ignore=shutil.ignore_patterns(*_EXCLUIR, "*.pyc", "*.pyo"),
        )


def _instalar_dependencias(destino: Path) -> None:
    """Instala las dependencias de runtime dentro del directorio de build.

    Args:
        destino: Directorio temporal del build (los paquetes van a su raíz).

    Raises:
        RuntimeError: Si `pip` termina con error (red, versión incompatible...).
    """
    comando = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--quiet",
        "--target",
        str(destino),
        "--upgrade",
        *_DEPENDENCIAS,
    ]
    resultado = subprocess.run(comando, capture_output=True, text=True, check=False)
    if resultado.returncode != 0:
        raise RuntimeError(
            "pip install falló al empaquetar las dependencias:\n"
            f"{resultado.stderr.strip() or resultado.stdout.strip()}"
        )


def _zippear(directorio: Path, zip_path: Path) -> None:
    """Crea el zip con la raíz del build (paquetes y dependencias en la misma capa).

    Args:
        directorio: Directorio temporal con el contenido final.
        zip_path: Ruta del `.zip` de salida (se sobrescribe).
    """
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archivo:
        for ruta in sorted(directorio.rglob("*")):
            if ruta.is_file():
                archivo.write(ruta, ruta.relative_to(directorio))


def construir(zip_path: Path) -> Path:
    """Construye el desplegable completo: código + dependencias + zip.

    Args:
        zip_path: Ruta final del `.zip`.

    Returns:
        La misma ruta, para encadenar o registrar el resultado.

    Raises:
        FileNotFoundError: Si falta un paquete de `src/`.
        RuntimeError: Si `pip` falla instalando dependencias.
    """
    raiz = _raiz_repo()
    with tempfile.TemporaryDirectory(prefix="chatbot-zip-") as tmp:
        build = Path(tmp)
        _copiar_codigo(raiz / "src", build)
        _instalar_dependencias(build)
        _zippear(build, zip_path)
    return zip_path


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada CLI del empaquetado.

    Args:
        argv: Argumentos de línea de comandos; `None` usa `sys.argv`.

    Returns:
        `0` si el zip se creó; `1` si algo falló (mensaje en stderr).
    """
    parser = argparse.ArgumentParser(description="Construye artifacts/chatbot.zip")
    parser.add_argument(
        "--out",
        default=str(_raiz_repo() / "artifacts" / "chatbot.zip"),
        help="Ruta del zip de salida (por defecto artifacts/chatbot.zip)",
    )
    args = parser.parse_args(argv)
    try:
        ruta = construir(Path(args.out))
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    tamaño_mb = ruta.stat().st_size / (1024 * 1024)
    print(f"OK: {ruta} ({tamaño_mb:.1f} MB comprimido)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
