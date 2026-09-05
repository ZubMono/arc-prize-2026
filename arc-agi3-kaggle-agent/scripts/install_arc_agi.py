"""[arc-agi3-kaggle-agent/scripts/install_arc_agi] BL.21554 -- instala `arc-agi` y `arcengine` en
el venv del proyecto a partir de las wheels que Kaggle adjunta al dataset.

POR QUE NO ES UN `pip install arc-agi` A SECAS. Las wheels del dataset son las MISMAS que corre el
gateway de Kaggle: instalarlas fija la version exacta del motor de juego contra la que se evalua,
en vez de la que PyPI tenga hoy. Ese es el punto entero de que Kaggle las adjunte.

POR QUE HAY DOS CAMINOS. El dataset trae las dependencias binarias (numpy, matplotlib, pillow,
pydantic-core...) compiladas SOLO para `x86_64`, que es la arquitectura de los ejecutores de
Kaggle. En un host ARM (Graviton, Apple Silicon) esas wheels no aplican y `--no-index` falla con
"no matching distribution". En ese caso se instalan igual las wheels que SI son portables
(`arc_agi` y `arcengine` son `py3-none-any`, o sea el codigo que importa) y las binarias se
resuelven desde PyPI para la arquitectura del host. El motor de juego queda pinneado igual; lo que
cambia es el build de numpy, que no altera el comportamiento del juego."""
from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from starter_config import WHEELS_DIR  # noqa: E402  (necesita el sys.path de arriba)

#: Wheels puras (`py3-none-any`) que definen el motor de juego. Se instalan SIEMPRE desde el
#: dataset, en cualquier arquitectura.
PAQUETES_PUROS = ("arc_agi", "arcengine")

#: Arquitectura para la que Kaggle compila las wheels binarias del dataset.
ARQUITECTURA_DE_KAGGLE = "x86_64"


def wheels_puras() -> list[Path]:
    """Rutas de las wheels de `arc_agi`/`arcengine` presentes en `wheels/`."""
    encontradas: list[Path] = []
    for paquete in PAQUETES_PUROS:
        candidatas = sorted(WHEELS_DIR.glob(f"{paquete}-*.whl"))
        if not candidatas:
            raise SystemExit(
                f"[install_arc_agi] No hay wheel de `{paquete}` en {WHEELS_DIR}. "
                "Corre `python3 scripts/fetch_competition_data.py` primero."
            )
        encontradas.append(candidatas[-1])
    return encontradas


def comando_de_instalacion() -> list[str]:
    """Argumentos de `pip install`, segun la arquitectura del host."""
    base = [sys.executable, "-m", "pip", "install", "--find-links", str(WHEELS_DIR)]
    if platform.machine() == ARQUITECTURA_DE_KAGGLE:
        # Mismo escenario que Kaggle: todo sale del dataset, sin tocar la red.
        return [*base, "--no-index", "arc-agi", "python-dotenv"]
    print(
        f"[install_arc_agi] Host {platform.machine()}: las wheels binarias del dataset son "
        f"{ARQUITECTURA_DE_KAGGLE} y no aplican aca. Se instalan arc-agi/arcengine desde el "
        "dataset y las dependencias binarias desde PyPI."
    )
    return [*base, *[str(ruta) for ruta in wheels_puras()], "python-dotenv"]


def main() -> None:
    comando = comando_de_instalacion()
    print(f"[install_arc_agi] {' '.join(comando[2:])}")
    subprocess.run(comando, check=True)
    print("[install_arc_agi] Listo: motor de juego instalado en el venv del proyecto.")


if __name__ == "__main__":
    main()
