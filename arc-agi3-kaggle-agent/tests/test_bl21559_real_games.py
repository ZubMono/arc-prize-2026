"""[arc-agi3-kaggle-agent/tests/test_bl21559_real_games] BL.21559 -- efecto medido sobre las
PARTIDAS REALES y PARIDAD exacta con el motor TypeScript canonico.

QUE MIDE. Cuantas firmas de estado DISTINTAS ve el agente durante la partida, con la mascara VIVA
(la que existe en cada paso), no con la mascara final. Es la diferencia que hace o rompe todo lo que
se apoya en "volver a un estado ya visto": memoria por-estado, deteccion de ciclos y -- desde este
BL -- el desempate por novedad.

EL AGUJERO QUE TAPA. BL.21558 midio la mascara RETROSPECTIVAMENTE: aplico la mascara FINAL a toda la
trayectoria y encontro 78 -> 19 firmas en ar25, 95 -> 9 en ka59, 123 -> 9 en dc22. Durante la
partida eso no existia: la barra enciende una celda por paso, la componente que la mascara reconoce
crece con ella y el conjunto volatil cambiaba en ~48 pasos seguidos, asi que la firma cambiaba
igual. Medido con la mascara viva ANTES de este BL: 78/83, 95/100, 123/128 -- practicamente lo mismo
que sin mascara. La correccion (cerrar la barra entera apenas se la reconoce, cuando vive sobre un
borde) baja esos numeros a 33, 30 y 37.

PARIDAD. Los numeros son un contrato ejecutable con
`arc-agi-runner/src/worldModel/__tests__/bl21559.realGames.effect.test.ts`, que mide exactamente lo
mismo sobre exactamente la misma grabacion. Si un puerto cambia el criterio y el otro no, uno de los
dos se pone en rojo.

AISLAMIENTO. El fixture vive en el OTRO proyecto y se resuelve por ruta relativa con skip si no
esta: `arc-agi3-kaggle-agent` tiene que poder extraerse del monorepo y seguir corriendo sus tests.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from arc_agent.world_model import VolatilityTracker, compute_state_signature, is_no_op_transition

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "arc-agi-runner"
    / "src"
    / "worldModel"
    / "__fixtures__"
    / "volatilityRealGames.json"
)

#: Por juego: (pasos, firmas unicas con la mascara viva ANTES de BL.21559, firmas unicas con la
#: mascara viva de HOY). Regenerar el fixture obliga a re-medir a mano en los DOS puertos.
ESPERADO: dict[str, tuple[int, int, int]] = {
    "lf52-271a04aa": (92, 65, 18),
    "ar25-0c556536": (83, 78, 33),
    "ka59-38d34dbb": (100, 95, 30),
    "dc22-fdcac232": (128, 123, 37),
}


def _cargar_juegos() -> list[dict]:
    if not FIXTURE.exists():
        pytest.skip(
            f"fixture de partidas reales ausente ({FIXTURE}) -- se corre desde el monorepo; "
            "el agente extraido solo no lo tiene y eso es correcto por diseno."
        )
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["juegos"]


def _reconstruir(juego: dict) -> list[list[list[int]]]:
    grillas = [[list(fila) for fila in juego["base"]]]
    for paso in juego["pasos"]:
        siguiente = [list(fila) for fila in grillas[-1]]
        diff = paso["diff"]
        for i in range(0, len(diff), 3):
            siguiente[diff[i]][diff[i + 1]] = diff[i + 2]
        grillas.append(siguiente)
    return grillas


def _mascara_previa(mask, cambio_alguna_vez: list[list[bool]]):
    """Reconstruye la mascara PREVIA a este BL a partir de la vigente: la extension solo agrega
    celdas de la linea de la barra que TODAVIA no se vieron cambiar, asi que intersecar la mascara
    de hoy con "esta celda ya cambio alguna vez" devuelve el conjunto anterior. Es la unica forma de
    medir el antes y el despues sobre la MISMA trayectoria sin mantener dos implementaciones."""
    if mask is None:
        return None
    return [
        [celda and cambio_alguna_vez[y][x] for x, celda in enumerate(fila)]
        for y, fila in enumerate(mask)
    ]


def _medir(juego: dict) -> tuple[int, int, int, int]:
    """(pasos, firmas con mascara previa, firmas con mascara estable, no-ops detectados en vivo)."""
    grillas = _reconstruir(juego)
    tracker = VolatilityTracker()
    cambio_alguna_vez = [[False] * juego["ancho"] for _ in range(juego["alto"])]
    firmas_previas: set[tuple[int, int]] = set()
    firmas_estables: set[tuple[int, int]] = set()
    no_ops = 0

    for i, paso in enumerate(juego["pasos"]):
        mask = tracker.mask
        version = tracker.version
        disponibles = tuple(paso["accionesDisponibles"])
        # La version entra en la clave: dos firmas calculadas con mascaras distintas son hashes de
        # DOS definiciones de estado y contarlas juntas inventaria repeticiones.
        firmas_estables.add((version, compute_state_signature(grillas[i], disponibles, mask)))
        firmas_previas.add(
            (
                version,
                compute_state_signature(
                    grillas[i], disponibles, _mascara_previa(mask, cambio_alguna_vez)
                ),
            )
        )
        if is_no_op_transition(grillas[i], grillas[i + 1], mask):
            no_ops += 1
        diff = paso["diff"]
        for k in range(0, len(diff), 3):
            cambio_alguna_vez[diff[k]][diff[k + 1]] = True
        tracker.observe(paso["accion"], grillas[i], grillas[i + 1])

    return len(juego["pasos"]), len(firmas_previas), len(firmas_estables), no_ops


def test_la_mascara_viva_se_estabiliza_y_las_firmas_vuelven_a_repetirse() -> None:
    juegos = _cargar_juegos()
    medido: dict[str, tuple[int, int, int]] = {}
    for juego in juegos:
        pasos, previas, estables, no_ops = _medir(juego)
        medido[juego["gameId"]] = (pasos, previas, estables)
        print(
            f"[BL.21559][{juego['gameId']}] {pasos} pasos | firmas unicas con mascara VIVA: "
            f"antes {previas}, ahora {estables} | no-ops detectados en vivo {no_ops}"
        )
        # Antes: casi una firma nueva por paso pese a tener mascara -- la mejora de BL.21558 solo
        # existia mirando la partida terminada.
        assert previas > pasos * 0.65
        # Ahora la firma vuelve a describir el ESTADO durante la partida.
        assert estables < previas * 0.6

    assert medido == ESPERADO, "los numeros de paridad con el puerto TypeScript se movieron"
