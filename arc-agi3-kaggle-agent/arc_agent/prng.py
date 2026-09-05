"""[arc-agi3-kaggle-agent/prng] BL.20783 -- PRNG semillado y deterministico. A diferencia de
projects/arc-agi-runner/src/prng.ts (BL.20775, mulberry32 escrito a mano), aca se usa
`random.Random(seed)` de la stdlib: mismo PRINCIPIO (mismo seed produce siempre la misma
secuencia, reproducible para replay) pero SIN portar el algoritmo mulberry32 bit a bit -- la
stdlib de Python ya es deterministica y esta bien probada; portar bit-twiddling a mano entre
lenguajes es fuente comun de bugs sutiles que tests superficiales no detectan."""
from __future__ import annotations

import random as _random_module
import time
from typing import Callable


def create_seeded_random(seed: str) -> Callable[[], float]:
    """Generador deterministico en [0, 1) -- mismo seed produce siempre la misma secuencia."""
    return _random_module.Random(seed).random


def generate_seed() -> str:
    """Seed nuevo no deterministico -- se persiste (ver runtime_report.py) para poder reproducir
    la corrida en un replay, mismo criterio que prng.ts::generateSeed en arc-agi-runner."""
    return f"{int(time.time() * 1000):x}-{_random_module.SystemRandom().getrandbits(32):x}"
