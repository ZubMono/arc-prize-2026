"""[arc-agi3-kaggle-agent/tests/test_mechanics_parity] BL.21741 (correccion) -- el contrato
EJECUTABLE de la PERCEPCION entre el motor TypeScript canonico
(projects/arc-agi-runner/src/worldModel/objectMechanics.ts + mechanicsSignature.ts) y este puerto.

EL DEFECTO QUE LO MOTIVA, MEDIDO. BL.21741 arreglo la percepcion de ESTE lado -- tope 4096, tipo
propio para los dos silencios (`sobreElTope` / `formaIncompatible`), firma COMPUESTA -- y el motor
TypeScript quedo sin el arreglo: `MAX_CELDAS_CAMBIADAS = 2048` y "desconocida" para todo. Sobre el
MISMO corpus persistido de subidas de nivel (14 ventanas, sha256 86ec7f5ffe39) el puerto Python
daba 7 firmas distintas sobre 8 transiciones y el motor TypeScript daba UNA (`desconocida` 14 de
14) -- y las dos suites estaban verdes: 1033 tests Python y 566 TypeScript. El puerto que quedo
viejo NO es el secundario: es el que juega contra la API oficial cada hora
(`scripts/cron/arc-live-game-run.cjs`) y el que PERSISTE `arcReplayFrames`, o sea la fuente del
corpus sobre el que este BL y los siguientes miden. `test_dsl_parity.py` no lo cubria: su alcance es
`primitiveOps` / `apply_program`, no la percepcion objeto-centrica.

COMO FUNCIONA. `arc-agi-runner/scripts/generateMechanicsParityFixture.ts` importa el motor canonico
y emite `mechanicsParity.json` con (a) las CONSTANTES del contrato -- donde vivio la divergencia --
y (b) casos (pre, post) -> {tipo, celdasCambiadas, firma, conteo de clusters, silencio}. Los dos
lados lo consumen: el test TypeScript falla si el fixture quedo stale respecto del motor, y este
falla si el puerto divergio. El fixture es el unico arbitro; ninguno de los dos lados se cree a si
mismo. El gate `scripts/safeguards/check-dsl-parity.cjs` corre las dos mitades en el pre-commit.

AISLAMIENTO. El fixture vive en el OTRO proyecto, asi que se resuelve por ruta relativa y se hace
skip si no esta: `arc-agi3-kaggle-agent` tiene que poder extraerse del monorepo y seguir corriendo
sus tests. Mismo criterio que `test_dsl_parity.py`. Este archivo es de DESARROLLO: nunca viaja al
notebook de Kaggle (no esta en MODULE_ORDER).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arc_agent.world_model.object_mechanics import (  # noqa: E402
    MAX_AREA_CAJA_DE_CAMBIOS,
    MAX_CELDAS_CAMBIADAS,
    MAX_TAMANO_OBJETO,
    MIN_EVIDENCIA_DE_OBJETO,
    TIPOS_DE_MECANICA,
    TIPOS_DE_NO_MIRE,
    TIPO_SIN_MEDICION,
    TIPO_SIN_NOMBRAR,
    detectar_mecanica,
)
# BL.21853 -- los topes de la via de OBJETO ENTERO viven en object_geometry y son contrato: si un
# puerto los cambia y el otro no, los dos motores clasifican distinto el mismo frame con las dos
# suites en verde (que es exactamente lo que paso con MAX_CELDAS_CAMBIADAS).
from arc_agent.world_model.object_geometry import (  # noqa: E402
    MAX_CELDAS_DE_OBJETO_ENTERO,
    MAX_PARES_DE_OBJETO,
)
from arc_agent.world_model.mechanics_signature import (  # noqa: E402
    CORTES_DE_CUBO,
    PREFIJO_DE_FIRMA_COMPUESTA,
    conteo_de_tipos_de_cluster,
    es_firma_de_silencio,
    firma_de_mecanica,
)

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "arc-agi-runner"
    / "src"
    / "worldModel"
    / "__fixtures__"
    / "mechanicsParity.json"
)


def _cargar() -> dict:
    if not FIXTURE.exists():
        pytest.skip(
            f"fixture de paridad ausente ({FIXTURE}) -- se corre desde el monorepo; "
            "el agente extraido solo no lo tiene y eso es correcto por diseno."
        )
    datos = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert datos["generatedFrom"] == "typescript", (
        "el fixture tiene que venir del lado canonico: si alguien lo regenera desde Python, "
        "el test se vuelve un espejo de si mismo y deja de probar la paridad."
    )
    return datos


FIXTURE_CARGADO = _cargar() if FIXTURE.exists() else {"cases": [], "constantes": {}}
CASOS = FIXTURE_CARGADO.get("cases", [])


def test_las_constantes_del_contrato_coinciden_con_el_motor_canonico() -> None:
    """LA MITAD DEL FIXTURE QUE HABRIA ATAJADO LA DIVERGENCIA REAL.

    El tope valia 4096 aca y 2048 alla, y ningun caso de comportamiento sobre grillas de 8x8 lo
    habria mostrado: hacen falta 2049 celdas cambiadas para que el corte se note. Las constantes
    SON contrato."""
    _cargar()
    esperado = FIXTURE_CARGADO["constantes"]
    assert esperado == {
        "MAX_CELDAS_CAMBIADAS": MAX_CELDAS_CAMBIADAS,
        "MAX_AREA_CAJA_DE_CAMBIOS": MAX_AREA_CAJA_DE_CAMBIOS,
        "MAX_TAMANO_OBJETO": MAX_TAMANO_OBJETO,
        "MIN_EVIDENCIA_DE_OBJETO": MIN_EVIDENCIA_DE_OBJETO,
        "MAX_CELDAS_DE_OBJETO_ENTERO": MAX_CELDAS_DE_OBJETO_ENTERO,
        "MAX_PARES_DE_OBJETO": MAX_PARES_DE_OBJETO,
        "CORTES_DE_CUBO": list(CORTES_DE_CUBO),
        "TIPOS_DE_MECANICA": list(TIPOS_DE_MECANICA),
        "TIPOS_DE_NO_MIRE": list(TIPOS_DE_NO_MIRE),
        "TIPO_SIN_MEDICION": TIPO_SIN_MEDICION,
        "TIPO_SIN_NOMBRAR": TIPO_SIN_NOMBRAR,
        "PREFIJO_DE_FIRMA_COMPUESTA": PREFIJO_DE_FIRMA_COMPUESTA,
    }


def test_el_fixture_cubre_todos_los_tipos_y_las_dos_formas_de_compuesta() -> None:
    """Un caso por tipo, y las dos compuestas que se pueden confundir entre si."""
    _cargar()
    tipos = {c["expected"]["tipo"] for c in CASOS}
    assert set(TIPOS_DE_MECANICA) <= tipos, f"faltan tipos en el fixture: {set(TIPOS_DE_MECANICA) - tipos}"
    compuestas = [
        c["expected"]["firma"]
        for c in CASOS
        if c["expected"]["firma"].startswith(PREFIJO_DE_FIRMA_COMPUESTA)
    ]
    assert any(es_firma_de_silencio(f) for f in compuestas)
    assert any(not es_firma_de_silencio(f) for f in compuestas)


@pytest.mark.parametrize("caso", CASOS, ids=[c["name"] for c in CASOS])
def test_el_puerto_reproduce_el_fixture(caso: dict) -> None:
    """Mismo (pre, post) -> misma percepcion, campo por campo."""
    opciones = caso.get("opciones") or {}
    mecanica = detectar_mecanica(
        caso["pre"],
        caso["post"],
        caso.get("mask"),
        max_celdas_cambiadas=opciones.get("maxCeldasCambiadas"),
    )
    esperado = caso["expected"]
    firma = firma_de_mecanica(mecanica)
    assert mecanica.tipo == esperado["tipo"], caso["why"]
    assert mecanica.celdas_cambiadas == esperado["celdasCambiadas"], caso["why"]
    assert firma == esperado["firma"], caso["why"]
    assert es_firma_de_silencio(firma) is esperado["esFirmaDeSilencio"], caso["why"]
    assert conteo_de_tipos_de_cluster(mecanica) == esperado["conteoDeTiposDeCluster"], caso["why"]

    t = mecanica.traslacion_principal
    traslacion = (
        None
        if t is None
        else {"dy": t.dy, "dx": t.dx, "alto": t.alto, "ancho": t.ancho}
    )
    assert traslacion == esperado["traslacionPrincipal"], caso["why"]

    c = mecanica.cambio_de_color_principal
    color = None if c is None else {"desde": c.desde, "hasta": c.hasta, "celdas": c.celdas}
    assert color == esperado["cambioDeColorPrincipal"], caso["why"]
