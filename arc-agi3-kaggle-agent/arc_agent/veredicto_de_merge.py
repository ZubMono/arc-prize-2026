"""veredicto_de_merge.py — BL.22855. Separar los DOS juicios que el gate confundia en uno.

EL DEFECTO, MEDIDO 2026-08-26. `gate_de_merge.py` rechazaba (exit 1) todo `delta <= 0`, y con ese
unico umbral juzgaba dos preguntas distintas:

    "¿este cambio MEJORA el score?"   -> exige una metrica que DISCRIMINE.
    "¿este cambio NO ROMPE nada?"     -> alcanza con que no empeore mas alla del ruido.

Y el instrumento mide ruido: 5 corridas del MISMO codigo (200 pasos, 25 juegos, solo variando la
semilla) dieron 11, 9, 9, 8, 7 niveles. Rango 4, sigma 1,48 sobre una media de 8,8. Con 1 corrida
por lado -- como corre el gate -- lo minimo distinguible del ruido es un salto de ~4,1 niveles: una
mejora del 47% de golpe. Detectar +1 nivel exigiria 34 corridas (~23 h de CPU) POR CAMBIO.

CONSECUENCIA de mezclarlos, y el veto quedaba del lado equivocado en LOS DOS casos: una correccion
legitima que no completa un nivel nuevo se RECHAZA, y un +1 afortunado (puro ruido) se ACEPTA.

LA BANDA NO SE ELIGE A OJO. Sale de `resolucion_del_gate.py`, que es re-ejecutable y ya existe. Si
no hay medicion fresca para la configuracion en uso, este modulo NO puede juzgar y lo DICE
(fail-closed) en vez de asumir un numero -- asumirlo seria reintroducir el mismo defecto con otra cara.

PURO: sin archivos, sin red, sin reloj. Los numeros entran ya medidos.
"""

from __future__ import annotations

MODO_MEJORA = "mejora"
MODO_SIN_REGRESION = "sin-regresion"
MODOS = (MODO_MEJORA, MODO_SIN_REGRESION)


def banda_de_ruido(medicion: dict | None) -> dict:
    """La banda de ruido del instrumento, leida de la medicion de resolucion_del_gate.

    Devuelve `{'conocida': bool, 'banda': float|None, 'porque': str}`. `conocida=False` NO es
    "banda cero": es "no se midio", y el llamador tiene que tratarlo distinto.
    """
    if not isinstance(medicion, dict):
        return {
            "conocida": False,
            "banda": None,
            "porque": "no hay medicion de resolucion del gate. Correr: python3 scripts/resolucion_del_gate.py",
        }
    v = medicion.get("veredicto") or {}
    if not v.get("concluyente"):
        return {
            "conocida": False,
            "banda": None,
            "porque": f"la medicion existe pero no es concluyente: {v.get('texto', 'sin texto')}",
        }
    rango = v.get("rango")
    if not isinstance(rango, (int, float)):
        return {"conocida": False, "banda": None, "porque": "la medicion no trae `rango` numerico"}
    # La banda es el RANGO medido, no la sigma: el rango es lo que el instrumento de VERDAD se movio
    # entre corridas identicas, y es lo que hay que superar para afirmar cualquier cosa. Usar sigma
    # (1,33 contra un rango de 4) daria una banda mas angosta que lo observado -- optimista justo
    # donde el optimismo es el defecto.
    return {
        "conocida": True,
        "banda": float(rango),
        "porque": (
            f"banda = {rango} niveles, el RANGO medido entre {v.get('total', '?')} corridas del mismo "
            f"codigo (min {v.get('min')}, max {v.get('max')}, sigma {v.get('sigma')})"
        ),
    }


def evaluar(delta: int, modo: str, medicion: dict | None = None) -> dict:
    """El veredicto de merge para un delta, segun QUE se esta juzgando.

    @returns {'aprobado': bool, 'indeterminado': bool, 'texto': str}
    """
    if modo not in MODOS:
        return {
            "aprobado": False,
            "indeterminado": True,
            "texto": (
                f"MODO INVALIDO: '{modo}'. Los dos juicios son distintos y hay que declarar cual se "
                f"pide: {' | '.join(MODOS)}. Adivinarlo seria el mismo defecto que este modulo cierra."
            ),
        }

    b = banda_de_ruido(medicion)

    if modo == MODO_MEJORA:
        if not b["conocida"]:
            # Sin banda no se puede afirmar una mejora: cualquier delta positivo podria ser ruido.
            return {
                "aprobado": False,
                "indeterminado": True,
                "texto": (
                    "INDETERMINADO -- no se puede afirmar una mejora sin saber cuanto se mueve el "
                    f"instrumento solo. {b['porque']}"
                ),
            }
        if delta > b["banda"]:
            return {
                "aprobado": True,
                "indeterminado": False,
                "texto": f"APROBADO (mejora): delta {delta:+d} SUPERA la banda de ruido. {b['porque']}",
            }
        return {
            "aprobado": False,
            "indeterminado": False,
            "texto": (
                f"RECHAZADO (mejora): delta {delta:+d} NO supera la banda de ruido de {b['banda']:g} "
                f"niveles, asi que es indistinguible de una corrida afortunada. {b['porque']}\n"
                "Si el cambio es una CORRECCION y no una mejora de score, el modo correcto es "
                f"'{MODO_SIN_REGRESION}'."
            ),
        }

    # MODO_SIN_REGRESION: alcanza con no empeorar MAS ALLA del ruido conocido.
    if not b["conocida"]:
        return {
            "aprobado": False,
            "indeterminado": True,
            "texto": (
                "INDETERMINADO -- 'sin regresion' necesita la banda para saber si una baja es ruido o "
                f"es real. {b['porque']}\n"
                "FAIL-CLOSED a proposito: asumir una banda seria volver a inventar el numero que este "
                "modulo vino a medir."
            ),
        }
    if delta >= -b["banda"]:
        return {
            "aprobado": True,
            "indeterminado": False,
            "texto": (
                f"APROBADO (sin regresion): delta {delta:+d} esta dentro de la banda de ruido de "
                f"{b['banda']:g} niveles -- no hay evidencia de que este cambio rompa nada. {b['porque']}\n"
                "OJO: esto NO afirma que mejore. Para eso hace falta el modo 'mejora' y una metrica "
                "que discrimine."
            ),
        }
    return {
        "aprobado": False,
        "indeterminado": False,
        "texto": (
            f"RECHAZADO (sin regresion): delta {delta:+d} cae MAS ABAJO que la banda de ruido de "
            f"{b['banda']:g} niveles. Esa baja no se explica por el instrumento. {b['porque']}"
        ),
    }
