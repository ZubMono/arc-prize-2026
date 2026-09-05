"""[arc-agi3-kaggle-agent/scripts/build_kernel_notebook] BL.21554 -- arma
`notebooks/submission.ipynb`, el notebook que se PUBLICA como kernel de Kaggle.

`agent/my_agent.py` es a su vez GENERADO por `submission/build_agent.py` (BL.21555): inlinea el
nucleo `arc_agent/` mas el wrapper `MyAgent` en un solo archivo. La cadena completa es
`make agente` -> `make notebook` (el Makefile encadena ambos). ESTE script sigue el patron real
de la competencia, el del notebook oficial de ejemplo ("Stochastic Goose"):

  Celda 1: instala la wheel `arc-agi` DESDE el dataset offline adjunto (sin internet).
  Celda 2: escribe `my_agent.py` en /tmp -- su cuerpo es `agent/my_agent.py` tal cual.
  Celda 3: si corre en la re-ejecucion de competencia, espera al gateway, copia el framework a
           /kaggle/working, registra MyAgent y corre `python main.py --agent myagent`.
  Celda 4: si no (modo "Save & Run All"), escribe un submission.parquet dummy para que el commit
           sea aceptado. El parquet real lo emite el gateway en la re-ejecucion.

El agente se escribe en /tmp y no en /kaggle/working a proposito: si quedara como output del
notebook, la UI de "Submit to Competition" lo ofreceria como candidato junto a submission.parquet
y una seleccion por defecto desafortunada rechaza la entrega.

ACELERADOR: ver `ACELERADOR` abajo. Es la FUENTE UNICA -- de ahi salen tanto los metadatos del
.ipynb como `enable_gpu` de `notebooks/kernel-metadata.json`, que se sincroniza en cada build."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from textwrap import dedent

sys.path.insert(0, str(Path(__file__).resolve().parent))

from starter_config import (  # noqa: E402  (necesita el sys.path de arriba)
    AGENT_SRC_PATH,
    KERNEL_METADATA_PATH,
    KERNEL_NOTEBOOK_PATH,
    PROJECT_ROOT,
    leer_metadata_kernel,
    slug_competencia,
)

# ─────────────────────────────────────────────────────────────────────────────
# ACELERADOR DE KAGGLE -- cambiar SOLO esta linea.
#   "cpu"      sin GPU.
#   "t4"       Nvidia T4 x2 (default del starter oficial).
#   "p100"     Nvidia P100.
#   "rtx6000"  Nvidia RTX 6000, exclusivo de ARC-AGI-3, quema cuota mucho mas rapido.
#
# Va en "cpu" a proposito y no en el "t4" que trae el starter: este agente no usa ML en inferencia
# (es busqueda + heuristicas sobre stdlib), asi que una GPU no le acelera absolutamente nada y la
# cuota de GPU es un recurso escaso de la cuenta que hay que gastar donde rinda.
# ─────────────────────────────────────────────────────────────────────────────
ACELERADOR = "cpu"

#: Mapeo interno al vocabulario de Kaggle. No tocar salvo que Kaggle agregue opciones.
ACELERADORES: dict[str, dict] = {
    "cpu": {"nombre": "none", "gpu": False},
    "t4": {"nombre": "nvidiaTeslaT4", "gpu": True},
    "p100": {"nombre": "nvidiaTeslaP100", "gpu": True},
    "rtx6000": {"nombre": "nvidiaRtx6000", "gpu": True},
}


def celda_codigo(fuente: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {"trusted": True},
        "outputs": [],
        "execution_count": None,
        "source": fuente,
    }


def celda_markdown(fuente: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": fuente}


def construir() -> dict:
    """Arma el notebook completo (dict listo para serializar a .ipynb)."""
    if ACELERADOR not in ACELERADORES:
        raise SystemExit(
            f"[build_kernel_notebook] ACELERADOR={ACELERADOR!r} desconocido. "
            f"Opciones: {sorted(ACELERADORES)}."
        )
    if not AGENT_SRC_PATH.exists():
        raise SystemExit(f"[build_kernel_notebook] No existe {AGENT_SRC_PATH}.")

    slug = slug_competencia()
    entrada = f"/kaggle/input/competitions/{slug}"
    cuerpo_agente = AGENT_SRC_PATH.read_text(encoding="utf-8")
    if "class MyAgent(Agent):" not in cuerpo_agente:
        raise SystemExit(
            f"[build_kernel_notebook] {AGENT_SRC_PATH} no define `class MyAgent(Agent):` -- el "
            "framework oficial registra la clase por nombre exacto. Regenerar con `make agente`."
        )

    celda_instalacion = celda_codigo(
        "!pip install --no-index --find-links \\\n"
        f"    {entrada}/arc_agi_3_wheels \\\n"
        "    arc-agi python-dotenv"
    )

    celda_agente = celda_codigo("%%writefile /tmp/my_agent.py\n" + cuerpo_agente)

    celda_corrida = celda_codigo(
        dedent(
            f"""\
            import os

            if os.getenv('KAGGLE_IS_COMPETITION_RERUN'):
                # Esperar a que el sidecar del gateway acepte conexiones.
                !curl --fail --retry 999 --retry-all-errors --retry-delay 5 \\
                      --retry-max-time 600 http://gateway:8001/api/games

                # Copiar el framework oficial a un lugar escribible.
                !cp -r {entrada}/ARC-AGI-3-Agents \\
                       /kaggle/working/ARC-AGI-3-Agents

                # Dejar nuestro agente como template del framework.
                !cp /tmp/my_agent.py \\
                    /kaggle/working/ARC-AGI-3-Agents/agents/templates/my_agent.py

                # Registrar MyAgent. Se reescribe __init__.py porque el de upstream importa
                # EAGER templates con dependencias que no viajan (langgraph, smolagents, ...).
                with open('/kaggle/working/ARC-AGI-3-Agents/agents/__init__.py', 'w') as f:
                    f.write(\"\"\"from typing import Type
            from dotenv import load_dotenv
            from .agent import Agent, Playback
            from .swarm import Swarm
            from .templates.random_agent import Random
            from .templates.my_agent import MyAgent

            load_dotenv()

            AVAILABLE_AGENTS: dict[str, Type[Agent]] = {{
                'random': Random,
                'myagent': MyAgent,
            }}
            \"\"\")

                # Apuntar el framework al gateway.
                with open('/kaggle/working/ARC-AGI-3-Agents/.env', 'w') as f:
                    f.write(\"\"\"SCHEME=http
            HOST=gateway
            PORT=8001
            ARC_API_KEY=test-key-123
            ARC_BASE_URL=http://gateway:8001/
            OPERATION_MODE=online
            ENVIRONMENTS_DIR=
            RECORDINGS_DIR=/kaggle/working/server_recording
            \"\"\")

                # Correr. El gateway graba cada accion y emite submission.parquet.
                !cd /kaggle/working/ARC-AGI-3-Agents && \\
                    MPLBACKEND=agg \\
                    python main.py --agent myagent
            """
        )
    )

    celda_dummy = celda_codigo(
        dedent(
            """\
            import os
            if not os.getenv('KAGGLE_IS_COMPETITION_RERUN'):
                # Modo commit (Save & Run All): se emite un submission dummy para que el commit
                # sea aceptado. El parquet real lo produce el gateway en la re-ejecucion.
                import pandas as pd
                submission = pd.DataFrame(
                    data=[['1_0', '1', True, 1]],
                    columns=['row_id', 'game_id', 'end_of_game', 'score'])
                submission.to_parquet('/kaggle/working/submission.parquet', index=False)
                submission.head()
            """
        )
    )

    acelerador = ACELERADORES[ACELERADOR]
    return {
        "metadata": {
            "kernelspec": {
                "language": "python",
                "display_name": "Python 3",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "mimetype": "text/x-python",
                "file_extension": ".py",
                "pygments_lexer": "ipython3",
            },
            "kaggle": {
                "accelerator": acelerador["nombre"],
                "isInternetEnabled": False,
                "isGpuEnabled": acelerador["gpu"],
                "language": "python",
                "sourceType": "notebook",
            },
        },
        "nbformat_minor": 4,
        "nbformat": 4,
        "cells": [
            celda_markdown(
                "# ARC Prize 2026 - ARC-AGI-3\n\n"
                "Notebook GENERADO por `scripts/build_kernel_notebook.py` a partir de "
                "`agent/my_agent.py`. No editar celdas a mano: editar el archivo fuente y correr "
                "`make notebook`."
            ),
            celda_instalacion,
            celda_agente,
            celda_corrida,
            celda_dummy,
        ],
    }


def sincronizar_metadata() -> None:
    """Deja `enable_gpu` de la metadata del kernel alineado con `ACELERADOR` (fuente unica)."""
    if not KERNEL_METADATA_PATH.exists():
        return
    metadata = leer_metadata_kernel()
    esperado = ACELERADORES[ACELERADOR]["gpu"]
    if metadata.get("enable_gpu") != esperado:
        metadata["enable_gpu"] = esperado
        KERNEL_METADATA_PATH.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"[build_kernel_notebook] Sincronizado enable_gpu={esperado} en la metadata.")


def main() -> None:
    KERNEL_NOTEBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    KERNEL_NOTEBOOK_PATH.write_text(
        json.dumps(construir(), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"[build_kernel_notebook] Escrito {KERNEL_NOTEBOOK_PATH.relative_to(PROJECT_ROOT)} "
        f"(acelerador: {ACELERADOR})."
    )
    sincronizar_metadata()


if __name__ == "__main__":
    main()
