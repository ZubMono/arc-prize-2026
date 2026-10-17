"""[arc-agi3-kaggle-agent/scripts/slim_framework] BL.21554 -- adelgaza
`vendor/ARC-AGI-3-Agents/agents/__init__.py` para que el loop local no arrastre dependencias de
LLM.

El `__init__.py` de upstream importa EAGER cada template con backend de LLM (langgraph, langsmith,
smolagents, openai...). Ninguno hace falta para correr `MyAgent` contra los juegos reales, y
obligarian a instalar cientos de MB que ademas no pueden viajar al notebook (Kaggle corre sin
internet). Es el MISMO recorte que hace el notebook oficial de ejemplo ("Stochastic Goose") en
tiempo de ejecucion sobre Kaggle -- aca se hace una sola vez, local, al terminar `make setup`.

Es idempotente: reescribe el archivo con el mismo contenido cada vez. El framework vive en
`vendor/` (gitignoreado, baja del dataset), asi que este recorte nunca entra al repo."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from starter_config import VENDOR_DIR  # noqa: E402  (necesita el sys.path de arriba)

INIT_PATH = VENDOR_DIR / "agents" / "__init__.py"

CONTENIDO_ADELGAZADO = '''\
"""Adelgazado por scripts/slim_framework.py (BL.21554) -- solo se registran los agentes que el
loop local necesita: `random` (baseline oficial) y `myagent` (el nuestro). Los templates con
backend de LLM se omiten a proposito: el notebook de Kaggle corre SIN INTERNET."""
from typing import Type

from dotenv import load_dotenv

from .agent import Agent, Playback
from .swarm import Swarm
from .templates.random_agent import Random

load_dotenv()

AVAILABLE_AGENTS: dict[str, Type[Agent]] = {
    "random": Random,
}

__all__ = ["Agent", "Playback", "Swarm", "Random", "AVAILABLE_AGENTS"]
'''


def main() -> None:
    if not INIT_PATH.exists():
        raise SystemExit(
            f"[slim_framework] No esta el framework en {INIT_PATH}. Corre `make setup` primero "
            "(baja ARC-AGI-3-Agents desde el dataset de la competencia)."
        )
    if INIT_PATH.read_text(encoding="utf-8") == CONTENIDO_ADELGAZADO:
        print(f"[slim_framework] Ya estaba adelgazado: {INIT_PATH}")
        return
    INIT_PATH.write_text(CONTENIDO_ADELGAZADO, encoding="utf-8")
    print(f"[slim_framework] Adelgazado {INIT_PATH}")


if __name__ == "__main__":
    main()
