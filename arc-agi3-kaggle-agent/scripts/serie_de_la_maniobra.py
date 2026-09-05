"""[arc-agi3-kaggle-agent/scripts/serie_de_la_maniobra] BL.21728 + BL.21765 -- los predicados sobre
SERIES NUMERICAS de la maniobra (la ocupacion, las distancias) y el minimo de pasos que tiene que
moverse una serie para que se la pueda llamar TENDENCIA.

Vive aparte de `maniobra_previa` por tamano: aquel modulo cruzo el limite de lineas al agregarsele
el saldo de objetos por paso (BL.21765). Aca estan los predicados sobre listas de numeros -- no
conocen `PasoPrevio` ni `VistaDeLaManiobra` y no importan nada del proyecto. `maniobra_previa` los
re-exporta, asi que ningun llamador cambia.

Stdlib pura, sin imports del resto del paquete. SOLO REPO."""
from __future__ import annotations

from typing import Sequence

#: Pasos que TIENEN que moverse en la direccion afirmada para llamar TENDENCIA a una serie. DOS, por
#: el mismo argumento por el que `creciente_monotona` exige >= 3 puntos: con un solo paso movil la
#: serie no es una tendencia sino un ESCALON, y no hay forma de distinguir "el agente venia
#: llenando" de "algo cambio una vez y despues nada". Medido sobre el corpus persistido: g50t (los
#: dos eventos) cumple "monotona no decreciente" con UN salto de +0,58pp en el primer paso y ocho
#: pasos planos despues; m0r0 lo cumple con 4 pasos que suben +0,05pp cada uno. Con este minimo, el
#: primero se cae y el segundo queda -- que es exactamente la distincion que interesa.
#:
#: BL.21765 lo reusa sobre el eje de los OBJETOS (`pasos_que_hacen_aparecer_netamente...`): el mismo
#: argumento, contando pasos con saldo neto de clusters en vez de pasos que mueven la ocupacion.
MINIMO_DE_PASOS_QUE_MUEVEN = 2


def sin_variacion(valores: Sequence[float]) -> bool:
    """True si todos los valores son el MISMO float. Comparacion exacta y no con tolerancia a
    proposito: `fraccion_no_fondo` es un cociente de enteros sobre la misma grilla, asi que dos
    frames con la misma cantidad de celdas ocupadas dan bit a bit el mismo valor. Una tolerancia
    convertiria "casi igual" en "igual" y eso es justo lo que este modulo no puede hacer."""
    return len(set(valores)) <= 1


def creciente_monotona(valores: Sequence[float]) -> bool:
    """Serie no decreciente que TERMINA mas arriba de donde empezo, con al menos 3 puntos.

    El >= 3 y el `final > inicial` no son decoracion: con dos puntos cualquier subida es "monotona",
    y una serie constante cumple "no decreciente" sin haber crecido nunca."""
    return (
        len(valores) >= 3
        and all(valores[i] >= valores[i - 1] for i in range(1, len(valores)))
        and valores[-1] > valores[0]
    )


def decreciente_monotona(valores: Sequence[float]) -> bool:
    """Espejo de `creciente_monotona`: no creciente y termina mas abajo de donde empezo."""
    return (
        len(valores) >= 3
        and all(valores[i] <= valores[i - 1] for i in range(1, len(valores)))
        and valores[-1] < valores[0]
    )


def pasos_que_suben(valores: Sequence[float]) -> int:
    """Cuantas transiciones de la serie suben ESTRICTAMENTE. Es el numero de frames REALES detras
    de un veredicto de llenado: los pasos planos no lo sostienen, solo no lo contradicen."""
    return sum(1 for i in range(1, len(valores)) if valores[i] > valores[i - 1])


def pasos_que_bajan(valores: Sequence[float]) -> int:
    """Espejo de `pasos_que_suben`."""
    return sum(1 for i in range(1, len(valores)) if valores[i] < valores[i - 1])


def tendencia_creciente(valores: Sequence[float]) -> bool:
    """Monotona creciente Y sostenida por al menos `MINIMO_DE_PASOS_QUE_MUEVEN` pasos que suben de
    verdad. Es el predicado que usan los criterios de objetivo; `creciente_monotona` (sin el minimo)
    queda para poder mostrar el contraste contra la medicion vieja."""
    return creciente_monotona(valores) and pasos_que_suben(valores) >= MINIMO_DE_PASOS_QUE_MUEVEN


def tendencia_decreciente(valores: Sequence[float]) -> bool:
    """Espejo de `tendencia_creciente`."""
    return decreciente_monotona(valores) and pasos_que_bajan(valores) >= MINIMO_DE_PASOS_QUE_MUEVEN


__all__ = [
    "MINIMO_DE_PASOS_QUE_MUEVEN",
    "creciente_monotona",
    "decreciente_monotona",
    "pasos_que_bajan",
    "pasos_que_suben",
    "sin_variacion",
    "tendencia_creciente",
    "tendencia_decreciente",
]
