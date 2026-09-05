"""[arc-agi3-kaggle-agent/tests/support/lazo_cerrado] Protocolo de medicion EN LAZO
CERRADO: la politica REAL elige, `EntornoMedido` contesta, y se cuenta a que se fue cada accion
del presupuesto. Mismo protocolo que uso BL.21593 para su gate (mismo seed, 200 pasos por juego,
25 juegos) para que los numeros sean comparables entre BLs.

LA METRICA DEL BL es `accionesEnBotonesMuertos`: pulsaciones gastadas en un boton que el MUNDO
sabe incapaz de cambiar nada, contadas SOLO despues de que la pantalla de titulo termino -- antes
de eso todas las flechas parecen muertas y pulsarlas es exactamente lo correcto (dc22/ka59/cd82/
lf52/bp35 arrancan en un menu). Las traducciones son `niveles`, `clicksProductivos`,
`pasosProductivos` y `distancia`.

`niveles` NO ES UN GATE DE MERGE (BL.21744). Es la columna que este banco mide peor: hasta BL.21744
era cero por construccion en 19 de los 25 mundos, porque el objetivo estaba fuera de su reticula.
Ya se arreglo y hay un guard con BFS que lo sostiene, pero el gate de merge sigue siendo
`scripts/gate_de_merge.py` contra el harness real. Aca la metrica que vale es
`accionesEnBotonesMuertos`.

Y eso ultimo esta MEDIDO, no argumentado. Corriendo el banco viejo (`git show 6f6afbb2f0^`) y el de
hoy con la MISMA politica, semilla "lazo" y 40 pasos: `accionesEnBotonesMuertos` 65 y 65 y
`juegosConMapeoResuelto` 16 y 16 -- identicos --, mientras `niveles` pasaba de 0 a 10,
`pasosProductivos` de 159 a 236 y `distancia` de 607 a 626. O sea: la geometria movia TRES de las
columnas y no tocaba la que decide. Por eso el rechazo de BL.21594 (que se decidio sobre
`accionesEnBotonesMuertos`, 1193 -> 1202) sigue en pie aunque el instrumento estuviera roto, y por
eso lo que hay que tachar de su acta es solo la linea de `niveles`. La invariancia quedo fijada
como propiedad en `tests/test_bl21744_acta_bl21594.py`, verificada a 40 Y a 200 pasos: a la
profundidad real `pasosProductivos` SI se mueve con la colocacion del objetivo (la recolocacion al
cobrar un nivel cuenta como paso productivo), y la unica columna invariante a las dos profundidades
es `accionesEnBotonesMuertos` -- justo la que decidio el rechazo.

QUIEN LO EJECUTA. El guard de alcanzabilidad (`tests/test_bl21744_alcanzabilidad_de_niveles.py`) lo
corre GATE-ARC-ALCANZABILIDAD en el pre-commit del monorepo cuando el commit toca este banco
(`scripts/safeguards/arc-guard-alcanzabilidad.cjs`). Antes no lo corria ningun pipeline: el unico
invocador era `make test`, a mano, que es el mismo mecanismo que fallo durante meses."""
from __future__ import annotations

from typing import Callable

from arc_agent.prng import create_seeded_random
from arc_agent.types import GameState

from .mundos_medidos import MUNDOS, EntornoMedido, Mundo

PASOS_POR_PARTIDA = 200


def jugar(
    mundo: Mundo,
    crear_politica: Callable[[Callable[[], float]], object],
    pasos: int = PASOS_POR_PARTIDA,
    seed: str = "lazo",
) -> dict[str, object]:
    """Una partida completa. `crear_politica` recibe el rng semillado y devuelve algo con
    `decide(frame)` -- la firma de `ExplorationPolicy`, para poder correr dos versiones del agente
    (baseline y candidata) sobre el MISMO mundo con el MISMO seed."""
    entorno = EntornoMedido(mundo, seed)
    politica = crear_politica(create_seeded_random(f"{seed}:{mundo.nombre}"))
    frame = entorno.reset()
    muertos = 0
    por_accion: dict[str, int] = {}
    paso_resuelto: int | None = None
    for paso in range(pasos):
        decision = politica.decide(frame)  # type: ignore[attr-defined]
        accion = decision.action.value
        por_accion[accion] = por_accion.get(accion, 0) + 1
        if not entorno.en_menu and entorno.es_boton_muerto(accion):
            muertos += 1
        frame = entorno.step(decision)
        if paso_resuelto is None and _mapeo_resuelto(politica):
            paso_resuelto = paso + 1
        if frame.state in (GameState.WIN, GameState.GAME_OVER):
            break
    return {
        "juego": mundo.nombre,
        "accionesEnBotonesMuertos": muertos,
        "pasoDeMapeoResuelto": paso_resuelto,
        "niveles": entorno.niveles,
        "pasosProductivos": entorno.productivos,
        "clicksProductivos": entorno.clicks_productivos,
        "distancia": entorno.distancia,
        "porAccion": por_accion,
    }


def _mapeo_resuelto(politica: object) -> bool:
    creencia = getattr(politica, "creencia_de_direcciones", None)
    if creencia is None:
        return False
    sembradas = creencia.acciones_sembradas()
    return bool(sembradas) and all(creencia.resuelta(a) for a in sembradas)


def medir_todos(
    crear_politica: Callable[[Callable[[], float]], object],
    pasos: int = PASOS_POR_PARTIDA,
    seed: str = "lazo",
) -> dict[str, dict[str, object]]:
    """Los 25 juegos, uno por uno. Devuelve el detalle por juego indexado por nombre."""
    return {m.nombre: jugar(m, crear_politica, pasos, seed) for m in MUNDOS}


def totales(medicion: dict[str, dict[str, object]]) -> dict[str, int]:
    """Suma las metricas enteras de todos los juegos -- la fila que compara dos agentes."""
    claves = (
        "accionesEnBotonesMuertos",
        "niveles",
        "pasosProductivos",
        "clicksProductivos",
        "distancia",
    )
    salida = {c: sum(int(v[c]) for v in medicion.values()) for c in claves}  # type: ignore[arg-type]
    resueltos = [v["pasoDeMapeoResuelto"] for v in medicion.values()]
    salida["juegosConMapeoResuelto"] = sum(1 for r in resueltos if r is not None)
    salida["pasosHastaMapeoResuelto"] = sum(int(r) for r in resueltos if r is not None)  # type: ignore[arg-type]
    return salida
