"""[arc-agi3-kaggle-agent/tests/test_bl21744_gate_comparable] BL.21744 (correccion 2026-08-19) --
EL GATE DE MERGE NO PUEDE APROBAR COMPARANDO DOS MEDICIONES DE CONFIGURACION DISTINTA.

EL DEFECTO, reproducido antes de arreglarlo. Con una linea base fabricada de tres claves y sin
bloque `config`:

    $ .venv/bin/python scripts/gate_de_merge.py --juego ls20,vc33 --pasos 20 --semillas gate-1 \\
          --json nuevo.json --contra base_sin_config.json
    CONTRA base_sin_config.json: 0 -> 1 (delta +1)
    GATE: APROBADO -- los niveles totales subieron.        # exit code 0

El agente no habia cambiado una linea. `nivelesTotales` es una SUMA sobre juegos x semillas y crece
con `--juego`, `--pasos` y `--semillas`, asi que cualquier base mas barata que la corrida produce un
delta positivo. El control que habia comparaba tres campos y solo `if antes_valor is not None`: una
base sin `config` -- la que escribe una version vieja del gate, o un archivo a mano -- lo esquivaba
entero. Es el ESPEJO del defecto que BL.21744 vino a eliminar: aquel era un falso NEGATIVO que
rechazaba toda mejora real; este es un falso POSITIVO que mergea lo que no mejoro, y en un gate de
merge ese es el error mas caro de los dos.

La leccion ya estaba escrita en el modulo hermano de la valvula de Kaggle
(`scripts/lib/arcKaggleDecisionSubmit.cjs`): "la suma depende de cuantos seeds se corrieron, asi que
cambiar BANCO_SEEDS haria aparecer una mejora de la nada contra una referencia vieja". Aca se aplica
exigiendo que la configuracion sea IDENTICA, que es mas fuerte que promediar.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

from gate_de_merge import (  # noqa: E402  (necesita el sys.path de arriba)
    CAMPOS_COMPARABLES,
    motivos_de_incomparabilidad,
)

CONFIG_DE_HOY = {
    "juegos": ["ls20", "vc33"],
    "juegosMedidos": ["ls20", "vc33"],
    "pasos": 200,
    "semillas": ["gate-1", "gate-2", "gate-3"],
    "modo": "offline",
    "banderas": "(default: las entregadas)",
}


def test_una_base_sin_bloque_config_no_es_comparable() -> None:
    """EL CASO REPRODUCIDO. Antes devolvia APROBADO; ahora el gate se niega y explica por que."""
    motivos = motivos_de_incomparabilidad(None, CONFIG_DE_HOY)
    assert motivos and "config" in motivos[0]
    assert motivos_de_incomparabilidad({}, CONFIG_DE_HOY) == motivos


@pytest.mark.parametrize("campo", CAMPOS_COMPARABLES)
def test_una_base_a_la_que_le_falta_cualquier_campo_no_es_comparable(campo) -> None:
    """Un campo faltante no es "no hay dato": es un dato que no se puede verificar, y el gate
    fail-closed. Sin esto alcanzaba con borrar una clave del JSON para que el gate aprobara."""
    base = {k: v for k, v in CONFIG_DE_HOY.items() if k != campo}
    motivos = motivos_de_incomparabilidad(base, CONFIG_DE_HOY)
    assert any(campo in m for m in motivos), motivos


@pytest.mark.parametrize(
    "campo,valor_de_la_base",
    [
        ("juegos", ["ls20"]),
        ("juegosMedidos", ["ls20"]),
        ("pasos", 60),
        ("semillas", ["gate-1"]),
        ("modo", "normal"),
    ],
)
def test_cada_campo_mas_barato_en_la_base_bloquea_el_gate(campo, valor_de_la_base) -> None:
    """LA TRAMPA CONCRETA: `make gate-base GATE_PASOS=60 GATE_SEMILLAS=gate-1` seguido de
    `make gate` (200 pasos x 3 semillas) daba APROBADO garantizado, y el propio docstring del gate
    recomendaba ese lazo rapido. Cada uno de estos campos lo habilitaba por separado."""
    base = {**CONFIG_DE_HOY, campo: valor_de_la_base}
    motivos = motivos_de_incomparabilidad(base, CONFIG_DE_HOY)
    assert any(campo in m for m in motivos), motivos


def test_juegos_medidos_atrapa_al_juego_que_se_salteo_en_silencio() -> None:
    """`correr()` saltea el juego cuyo entorno no se pudo crear e imprime una linea que nadie lee.
    Las dos corridas PIDEN los mismos 25, asi que `juegos` coincide; lo que no coincide es lo que se
    midio de verdad, y esa diferencia se sumaba entera al delta."""
    base = {**CONFIG_DE_HOY, "juegosMedidos": ["ls20"]}
    assert motivos_de_incomparabilidad(base, CONFIG_DE_HOY)


def test_dos_corridas_iguales_si_son_comparables() -> None:
    assert motivos_de_incomparabilidad(dict(CONFIG_DE_HOY), CONFIG_DE_HOY) == []


def test_las_palancas_distintas_NO_bloquean_porque_esa_comparacion_es_la_ablacion() -> None:
    """`banderas` queda fuera de la lista a proposito: comparar dos paquetes de palancas es
    exactamente para lo que existe `--banderas` (BL.21702). El gate lo imprime en la linea del
    delta para que la comparacion quede declarada, no la prohibe."""
    base = {**CONFIG_DE_HOY, "banderas": "ninguna"}
    assert motivos_de_incomparabilidad(base, CONFIG_DE_HOY) == []
    assert "banderas" not in CAMPOS_COMPARABLES


def test_la_comparabilidad_se_puede_verificar_ANTES_de_medir() -> None:
    """El gate completo son ~36 min de CPU. Los tres campos que se conocen sin medir -- juegos,
    pasos y semillas, mas el modo -- se verifican al arrancar, asi que una base incomparable (o
    inexistente) corta en el segundo cero en vez de media hora despues. `juegosMedidos` no entra en
    esa pasada porque recien existe cuando la corrida termino; lo cobra la verificacion final."""
    previos = ("juegos", "pasos", "semillas", "modo")
    base = {k: CONFIG_DE_HOY[k] for k in previos}
    assert motivos_de_incomparabilidad(base, CONFIG_DE_HOY, campos=previos) == []
    assert motivos_de_incomparabilidad({**base, "pasos": 60}, CONFIG_DE_HOY, campos=previos)
    # Y con el juego de campos COMPLETO esa misma base no alcanza: le falta `juegosMedidos`.
    assert any("juegosMedidos" in m for m in motivos_de_incomparabilidad(base, CONFIG_DE_HOY))
