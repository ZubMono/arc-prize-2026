"""[arc-agi3-kaggle-agent/world_model/estadistica_de_coocurrencia] BL.21704 -- la maquinaria
estadistica con la que `relaciones_no_locales.py` decide si una co-ocurrencia entre dos regiones
lejanas es senal o ruido. Sin estado: funciones puras sobre mascaras de bits.

EL RIESGO PRINCIPAL NO ES "CORRELACION NO ES CAUSA": ES QUE EL NULO ANALITICO MIENTE. La etapa 1 de
BL.21704 corrio el pipeline entero sobre datos PERMUTADOS -- o sea, sobre puro ruido con los
marginales reales -- y sobrevivieron 45 pares a Benjamini-Hochberg y 34 a Bonferroni, con 11 de 20
juegos mostrando al menos un par "significativo" falso por construccion. Esa es la razon de que
este modulo tenga DOS nulos y no uno:

  * `cola_binomial` es el nulo ANALITICO. Sirve para ORDENAR candidatos barato y alimentar BH; su
    supuesto de independencia entre pasos es falso en un juego (las trayectorias son suaves).
  * `umbral_del_nulo_empirico` es el nulo que MANDA: desplazamiento CIRCULAR de la region destino,
    que conserva sus marginales exactos y destruye solo la alineacion temporal.

Y el denominador de BH es HONESTO: se corrige por TODOS los tests hechos (pares no locales x 3
direcciones), no por los que llegaron a co-ocurrir. Elegir el denominador despues de ver el dato es
la forma mas comun de fabricar significancia.

Solo stdlib -- viaja al entregable de Kaggle.
"""
from __future__ import annotations

import math
from typing import Final

#: Co-activaciones minimas para siquiera testear un par. Medido: por debajo de 5 el conteo explota
#: (757.920 candidatos a nivel celda); con 5 quedan 1.696 candidatos sobre 223.302 tests.
MIN_SOPORTE: Final[int] = 5

#: Alfa de Benjamini-Hochberg. Bonferroni queda como referencia (213 pares contra 318 de BH sobre
#: el mismo corpus): NO es la restriccion vinculante -- la restriccion vinculante es que el nulo
#: binomial esta equivocado, y eso no lo arregla apretar el alfa.
ALFA_BH: Final[float] = 0.05

#: lag0 + las dos direcciones de lag1. La ventana de desfase es {0, 1} y NADA MAS: medido, lag0
#: lleva la senal y lag1 es sensiblemente mas ruidoso (en sp80 el nulo dio 8-14 sobrevivientes de
#: lag1 contra 5 observados), asi que lag1 solo entra con el nulo condicionado a la accion.
DIRECCIONES_POR_PAR: Final[int] = 3

#: Barajas del nulo empirico. 20 era el minimo para leer un percentil 95 sin interpolar (el 19.o
#: valor ordenado) y era TAMBIEN el defecto medido como SESGADO: con `paso = pasos // (cuantos+1)`
#: los 20 offsets caian todos en multiplos de ese paso, o sea en una sub-red de los desplazamientos
#: posibles. Contrastado sobre los candidatos reales de cuatro partidas de lp85, ese nulo aceptaba
#: entre 14% y 26% MAS pares que el nulo circular exhaustivo (86->64, 636->528, 1032->734,
#: 547->415), siempre en la direccion permisiva. Ahora el nulo es EXHAUSTIVO mientras la ventana lo
#: permita -- rotar enteros es barato -- y por encima de ese tope se muestrea con un paso COPRIMO
#: con `pasos-1`, que recorre todos los residuos en vez de una sub-red.
BARAJAS_DEL_NULO: Final[int] = 120
PERCENTIL_DEL_NULO: Final[int] = 95

#: Por debajo de esta cantidad de desplazamientos posibles el nulo se corre ENTERO (todos los
#: offsets de 1 a `pasos-1`). Es el nulo de referencia, no una aproximacion.
MAX_OFFSETS_EXHAUSTIVOS: Final[int] = 240


def cola_binomial(exitos: int, ensayos: int, p: float) -> float:
    """P(X >= exitos) con X ~ Binomial(ensayos, p), por recurrencia sobre la razon de terminos
    consecutivos -- sin factoriales gigantes, sin tabla y sin dependencias.

    Es el nulo ANALITICO, y la etapa 1 midio que MIENTE (deja pasar ~45 pares de puro ruido). Se
    conserva porque ordena los candidatos para BH de forma barata; el filtro vinculante es
    `umbral_del_nulo_empirico`."""
    if exitos <= 0:
        return 1.0
    if ensayos <= 0 or exitos > ensayos:
        return 0.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    log_termino = (
        math.lgamma(ensayos + 1)
        - math.lgamma(exitos + 1)
        - math.lgamma(ensayos - exitos + 1)
        + exitos * math.log(p)
        + (ensayos - exitos) * math.log1p(-p)
    )
    if log_termino < -745.0:
        return 0.0
    termino = math.exp(log_termino)
    total = termino
    razon_base = p / (1.0 - p)
    for k in range(exitos, ensayos):
        termino *= (ensayos - k) / (k + 1) * razon_base
        total += termino
        if termino < total * 1e-15:
            break
    return min(1.0, total)


def indice_de_corte_bh(p_valores: list[float], denominador: int) -> int:
    """Cuantos de los p-valores ORDENADOS ascendentemente sobreviven a Benjamini-Hochberg.

    `denominador` es la cantidad TOTAL de tests hechos, que casi nunca coincide con
    `len(p_valores)`: los pares que ni siquiera llegaron al soporte minimo tambien se testearon."""
    if not p_valores or denominador <= 0:
        return 0
    corte = 0
    for rango, p in enumerate(p_valores, 1):
        if p <= ALFA_BH * rango / denominador:
            corte = rango
    return corte


def _coprimo_con(n: int, arranque: int) -> int:
    """Primer entero >= `arranque` (y < n) coprimo con `n`. Un paso coprimo recorre TODOS los
    residuos modulo n antes de repetirse; uno que comparta divisor con n recorre solo la sub-red de
    sus multiplos -- que es exactamente el defecto que se midio en el nulo anterior."""
    if n <= 2:
        return 1
    for candidato in range(max(1, min(arranque, n - 1)), n):
        if math.gcd(candidato, n) == 1:
            return candidato
    return 1


def desplazamientos_del_nulo(pasos: int, cuantos: int = BARAJAS_DEL_NULO) -> list[int]:
    """Desplazamientos circulares del nulo empirico, DETERMINISTAS a proposito.

    El repo pinnea flotantes en tests de paridad entre el puerto Python y el TS; un nulo sembrado
    con el `rng` de la politica haria que dos corridas con la MISMA semilla dieran vocabularios
    distintos segun cuantos numeros consumio antes la exploracion.

    EL NULO ES EXHAUSTIVO MIENTRAS LA VENTANA LO PERMITA. Rotar un entero y contar sus bits cuesta
    nanosegundos, asi que con `pasos - 1 <= MAX_OFFSETS_EXHAUSTIVOS` se corren TODOS los
    desplazamientos y el percentil 95 es el del nulo circular completo, sin muestreo ni sesgo. Por
    encima de ese tope se toma un paso COPRIMO con `pasos - 1`, que barre todos los residuos; el
    defecto medido de la version anterior era justamente que su paso (`pasos // 21`) divide a la
    ventana y solo visitaba sus multiplos."""
    if pasos <= 2 or cuantos <= 0:
        return []
    posibles = pasos - 1
    if posibles <= MAX_OFFSETS_EXHAUSTIVOS:
        return list(range(1, pasos))
    paso = _coprimo_con(posibles, max(1, posibles // (cuantos + 1)))
    vistos: list[int] = []
    visto: set[int] = set()
    for i in range(1, cuantos * 3 + 1):
        offset = ((i * paso) % posibles) + 1
        if offset not in visto:
            visto.add(offset)
            vistos.append(offset)
        if len(vistos) >= cuantos:
            break
    return vistos


def rotar_circular(mascara: int, offset: int, pasos: int) -> int:
    """Rota la mascara de pasos dentro de la ventana de `pasos` bits. Conserva el popcount EXACTO
    -- por eso el nulo mantiene los marginales de la region y solo rompe la alineacion temporal."""
    if pasos <= 0:
        return 0
    total = (1 << pasos) - 1
    offset %= pasos
    if offset == 0:
        return mascara & total
    return ((mascara << offset) | ((mascara & total) >> (pasos - offset))) & total


def coocurrencias(firma_origen: int, firma_destino: int, desfase: int) -> int:
    """Mascara de los pasos en que se da la co-activacion, indexada por el paso de ORIGEN -- que es
    donde vive la accion que la causo, y por eso el histograma de acciones se arma sobre esta
    mascara y no sobre la del destino."""
    if desfase == 0:
        return firma_origen & firma_destino
    return firma_origen & (firma_destino >> 1)


def umbral_del_nulo_empirico(
    firma_origen: int, firma_destino: int, desfase: int, pasos: int
) -> float:
    """Percentil `PERCENTIL_DEL_NULO` del soporte bajo desplazamiento circular del DESTINO.

    Devuelve `inf` cuando la ventana es demasiado corta para barajar: sin nulo no se acepta nada,
    que es el lado correcto en el que fallar."""
    offsets = desplazamientos_del_nulo(pasos)
    if not offsets:
        return math.inf
    nulos = sorted(
        coocurrencias(firma_origen, rotar_circular(firma_destino, o, pasos), desfase).bit_count()
        for o in offsets
    )
    indice = min(len(nulos) - 1, (PERCENTIL_DEL_NULO * len(nulos) + 99) // 100 - 1)
    return float(nulos[indice])
