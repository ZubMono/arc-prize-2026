"""[arc-agi3-kaggle-agent/scripts/starter_config] BL.21554 -- FUENTE UNICA de rutas, slug de
competencia y usuario de Kaggle para todo el andamiaje de entrega adoptado del starter oficial
(`arcprize/ARC-AGI-3-Kaggle-Starter`).

Por que existe: el Makefile, `fetch_competition_data.py`, `slim_framework.py`, `play_local.py` y
`build_kernel_notebook.py` necesitan LOS MISMOS cinco datos (donde vive el framework vendorizado,
donde viven los juegos, donde viven las wheels, cual es el slug de la competencia y cual es el
usuario de Kaggle). Duplicarlos en cinco archivos era garantia de drift, asi que viven aca -- y el
slug y el usuario ni siquiera se escriben aca: se LEEN de `notebooks/kernel-metadata.json`, que es
el archivo que la propia CLI de Kaggle consume al publicar el kernel.

Kaggle SIEMPRE se habla por `node <monorepo>/scripts/kaggle-cli.cjs` (BL.21581): el token sale del
`.env` cifrado y nunca toca el disco ni el argv. `correr_kaggle()` es el unico lugar del proyecto
que arma ese subproceso."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

#: Raiz del sub-proyecto (`projects/arc-agi3-kaggle-agent/`).
PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: Raiz del monorepo. Solo se usa para localizar `scripts/kaggle-cli.cjs`; si el sub-proyecto se
#: extrae del monorepo, `correr_kaggle()` degrada al binario del venv con un mensaje explicito.
MONOREPO_ROOT = PROJECT_ROOT.parents[1]
KAGGLE_CLI_CJS = MONOREPO_ROOT / "scripts" / "kaggle-cli.cjs"

VENV_DIR = PROJECT_ROOT / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"
VENV_KAGGLE = VENV_DIR / "bin" / "kaggle"

#: Framework oficial `ARC-AGI-3-Agents`. NO se clona: viaja DENTRO del dataset de la competencia
#: (verificado con `kaggle competitions files arc-prize-2026-arc-agi-3`), asi que se baja con el
#: mismo token y se materializa aca. Gitignoreado.
VENDOR_DIR = PROJECT_ROOT / "vendor" / "ARC-AGI-3-Agents"

#: Juegos REALES de ARC-AGI-3 (codigo fuente de cada entorno). El paquete `arc-agi` los busca en
#: el directorio que indique `ENVIRONMENTS_DIR` (default: `environment_files` relativo al cwd).
ENVIRONMENTS_DIR = PROJECT_ROOT / "environment_files"

#: Wheels offline que Kaggle adjunta al dataset (`arc_agi`, `arcengine` y sus dependencias).
WHEELS_DIR = PROJECT_ROOT / "wheels"

#: Descarga cruda de la competencia (zip + extraccion). Transitorio, gitignoreado.
CACHE_DIR = PROJECT_ROOT / ".cache" / "kaggle"

NOTEBOOKS_DIR = PROJECT_ROOT / "notebooks"
KERNEL_METADATA_PATH = NOTEBOOKS_DIR / "kernel-metadata.json"
KERNEL_NOTEBOOK_PATH = NOTEBOOKS_DIR / "submission.ipynb"

#: El UNICO archivo de agente que viaja al notebook de Kaggle (contrato del starter oficial).
AGENT_SRC_PATH = PROJECT_ROOT / "agent" / "my_agent.py"

#: Placeholder que trae el starter y que el Makefile se niega a pushear sin reemplazar.
PLACEHOLDER_USUARIO = "REPLACE_WITH_YOUR_USERNAME"


def leer_metadata_kernel() -> dict:
    """Contenido de `notebooks/kernel-metadata.json`. Falla con mensaje accionable si no esta."""
    if not KERNEL_METADATA_PATH.exists():
        raise SystemExit(
            f"[starter_config] Falta {KERNEL_METADATA_PATH}. Es la fuente unica del slug de la "
            "competencia y del usuario de Kaggle."
        )
    return json.loads(KERNEL_METADATA_PATH.read_text(encoding="utf-8"))


def slug_competencia() -> str:
    """Slug de la competencia, leido de `competition_sources[0]` de la metadata del kernel."""
    fuentes = leer_metadata_kernel().get("competition_sources") or []
    if not fuentes:
        raise SystemExit(
            f"[starter_config] {KERNEL_METADATA_PATH} no declara `competition_sources`: sin eso no "
            "se sabe que dataset bajar ni a que competencia se entrega."
        )
    return str(fuentes[0])


def usuario_kaggle() -> str:
    """Usuario de Kaggle, leido del prefijo de `id` de la metadata del kernel."""
    identificador = str(leer_metadata_kernel().get("id", ""))
    usuario = identificador.split("/", 1)[0]
    if not usuario or usuario == PLACEHOLDER_USUARIO:
        raise SystemExit(
            f"[starter_config] {KERNEL_METADATA_PATH} todavia tiene el placeholder "
            f"`{PLACEHOLDER_USUARIO}` en `id`. Reemplazalo por tu usuario de Kaggle."
        )
    return usuario


def _binario_kaggle() -> str | None:
    """Ruta al CLI de Kaggle: el del venv del proyecto, o el que haya en el PATH."""
    if VENV_KAGGLE.exists():
        return str(VENV_KAGGLE)
    return shutil.which("kaggle")


def correr_kaggle(args: list[str], *, capturar: bool = False) -> subprocess.CompletedProcess:
    """Corre el CLI de Kaggle por la via sancionada del repo (`scripts/kaggle-cli.cjs`, BL.21581).

    El token viaja SOLO por entorno, inyectado por el wrapper desde el `.env` cifrado: nunca por
    argv (visible en `ps`) y nunca por disco. Si el sub-proyecto se extrajo del monorepo y el
    wrapper no existe, se degrada al binario directo avisandolo en espanol -- en ese caso el token
    tiene que estar en el entorno de quien invoca."""
    binario = _binario_kaggle()
    entorno = dict(os.environ)
    if binario:
        entorno["KAGGLE_CLI_BIN"] = binario

    if KAGGLE_CLI_CJS.exists():
        comando = ["node", str(KAGGLE_CLI_CJS), *args]
    else:
        if not binario:
            raise SystemExit(
                "[starter_config] No hay ni `scripts/kaggle-cli.cjs` (monorepo) ni binario "
                "`kaggle` en el venv/PATH. Corre `make setup` primero."
            )
        print(
            "[starter_config] AVISO: no se encontro scripts/kaggle-cli.cjs; se usa el binario "
            "directo. El token tiene que estar en KAGGLE_API_TOKEN del entorno."
        )
        comando = [binario, *args]

    return subprocess.run(
        comando,
        cwd=str(MONOREPO_ROOT if KAGGLE_CLI_CJS.exists() else PROJECT_ROOT),
        env=entorno,
        check=True,
        text=True,
        capture_output=capturar,
    )


def exportar_environments_dir() -> None:
    """Fija `ENVIRONMENTS_DIR` absoluto para el paquete `arc-agi`.

    Sin esto el paquete busca `environment_files` RELATIVO al cwd, y cualquier invocacion desde
    otro directorio se queda sin juegos (o peor: intenta bajarlos de la API oficial, que es
    exactamente la dependencia de red que este proyecto no puede tener)."""
    os.environ.setdefault("ENVIRONMENTS_DIR", str(ENVIRONMENTS_DIR))


def faltantes_para_jugar() -> list[str]:
    """Que activos del dataset faltan para poder correr el loop local. Vacio = todo listo.

    Es la MISMA lista que consultan `play_local.py` (para fallar con instrucciones) y los tests
    (para skipearse limpio cuando el dataset no esta bajado, ej. en CI)."""
    faltan: list[str] = []
    if not (VENDOR_DIR / "agents" / "agent.py").exists():
        faltan.append(str(VENDOR_DIR))
    if not ENVIRONMENTS_DIR.is_dir() or not any(ENVIRONMENTS_DIR.glob("*/*/metadata.json")):
        faltan.append(str(ENVIRONMENTS_DIR))
    return faltan
