"""Tests de BL.22855 — separar "¿mejoró?" de "¿no rompió nada?".

EL TEST DEL ANTES es el que decide si esto sirve: probar que con el criterio HISTORICO (delta>0) los
dos casos que importan salen AL REVES —una corrección legítima rechazada, un +1 de puro ruido
aceptado— y que con el juicio declarado salen bien.

La medición es la REAL del 2026-08-26: 5 corridas del mismo código dieron 11/9/9/8/7 niveles.
"""

from __future__ import annotations

import pytest

from arc_agent.veredicto_de_merge import (
    MODO_MEJORA,
    MODO_SIN_REGRESION,
    banda_de_ruido,
    evaluar,
)

# La medicion REAL, tal como la dejo resolucion_del_gate.py.
MEDICION = {
    "veredicto": {"concluyente": True, "rango": 4, "sigma": 1.327, "min": 7, "max": 11, "total": 5}
}


def criterio_historico(delta: int) -> bool:
    """El criterio que el gate usaba, para poder comparar contra el."""
    return delta > 0


# ─── EL TEST DEL ANTES ────────────────────────────────────────────────────────────────────────────

def test_el_antes_una_correccion_legitima_se_rechazaba():
    """Una correccion que baja 1 nivel esta DENTRO del ruido, pero el criterio viejo la rechaza."""
    assert criterio_historico(-1) is False, "el criterio viejo la rechaza"
    assert evaluar(-1, MODO_SIN_REGRESION, MEDICION)["aprobado"] is True, (
        "con el juicio correcto pasa: -1 esta dentro de una banda de 4"
    )


def test_el_antes_un_mas_uno_de_puro_ruido_se_aceptaba():
    """Y al reves: un +1 indistinguible del ruido, que el criterio viejo aprobaba."""
    assert criterio_historico(+1) is True, "el criterio viejo lo aprueba"
    assert evaluar(+1, MODO_MEJORA, MEDICION)["aprobado"] is False, (
        "no supera la banda de 4: es indistinguible de una corrida afortunada"
    )


def test_el_criterio_viejo_da_el_MISMO_veredicto_para_ruido_y_para_mejora_real():
    """La razon de fondo: delta>0 no distingue un +1 de ruido de un +5 real. Los aprueba igual."""
    assert criterio_historico(+1) == criterio_historico(+5)
    assert evaluar(+1, MODO_MEJORA, MEDICION)["aprobado"] is False
    assert evaluar(+5, MODO_MEJORA, MEDICION)["aprobado"] is True


# ─── el modo sin-regresion NO es "aprobar cualquier cosa" ─────────────────────────────────────────

def test_sin_regresion_rechaza_una_baja_REAL():
    """Si no rechazara nada seria un sello, no un juicio: -5 cae fuera de la banda de 4."""
    r = evaluar(-5, MODO_SIN_REGRESION, MEDICION)
    assert r["aprobado"] is False
    assert "MAS ABAJO" in r["texto"]


def test_sin_regresion_no_afirma_que_mejore_y_lo_dice():
    r = evaluar(+2, MODO_SIN_REGRESION, MEDICION)
    assert r["aprobado"] is True
    assert "NO afirma que mejore" in r["texto"], (
        "un aprobado que se lea como 'mejoro' repite la confusion que este BL cierra"
    )


def test_el_borde_exacto_de_la_banda():
    """-4 esta EN la banda (se acepta), -5 fuera. El borde importa: es donde se decide."""
    assert evaluar(-4, MODO_SIN_REGRESION, MEDICION)["aprobado"] is True
    assert evaluar(-5, MODO_SIN_REGRESION, MEDICION)["aprobado"] is False
    # Para 'mejora' el borde es estricto: hay que SUPERAR la banda, no igualarla.
    assert evaluar(+4, MODO_MEJORA, MEDICION)["aprobado"] is False
    assert evaluar(+5, MODO_MEJORA, MEDICION)["aprobado"] is True


# ─── FAIL-CLOSED: sin banda medida no se juzga ────────────────────────────────────────────────────

@pytest.mark.parametrize("modo", [MODO_MEJORA, MODO_SIN_REGRESION])
def test_sin_medicion_es_INDETERMINADO_y_nunca_aprobado(modo):
    r = evaluar(+3, modo, None)
    assert r["indeterminado"] is True
    assert r["aprobado"] is False
    assert "INDETERMINADO" in r["texto"]


def test_una_medicion_NO_CONCLUYENTE_tampoco_sirve():
    """resolucion_del_gate devuelve `concluyente: False` cuando no pudo medir. Eso no es una banda."""
    med = {"veredicto": {"concluyente": False, "texto": "INDETERMINADO: con menos de 2 corridas..."}}
    assert banda_de_ruido(med)["conocida"] is False
    assert evaluar(+3, MODO_MEJORA, med)["indeterminado"] is True


def test_un_modo_no_declarado_no_elige_uno_por_default():
    """Adivinar cual de los dos juicios se pide seria el mismo defecto con otra cara."""
    r = evaluar(+1, "", MEDICION)
    assert r["indeterminado"] is True
    assert "MODO INVALIDO" in r["texto"]


# ─── la banda sale de la MEDICION, no de un numero elegido ────────────────────────────────────────

def test_la_banda_es_el_RANGO_medido_y_no_la_sigma():
    """Sigma (1,33) es mas angosta que el rango (4): usarla seria optimista justo donde no hay que serlo."""
    b = banda_de_ruido(MEDICION)
    assert b["conocida"] is True
    assert b["banda"] == 4.0
    assert b["banda"] != MEDICION["veredicto"]["sigma"]


def test_la_banda_cita_de_donde_sale():
    b = banda_de_ruido(MEDICION)
    assert "5 corridas" in b["porque"] and "min 7" in b["porque"], (
        "el numero tiene que venir con su origen, o vuelve a ser un umbral elegido a ojo"
    )
