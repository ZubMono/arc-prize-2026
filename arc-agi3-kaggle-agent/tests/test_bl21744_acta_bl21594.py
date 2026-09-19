"""[arc-agi3-kaggle-agent/tests/test_bl21744_acta_bl21594] BL.21744 -- LA INVARIANCIA QUE SOSTIENE
EL ACTA DE BL.21594, verificada como propiedad y no escrita como parrafo de un commit.

BL.21594 se rechazo por `accionesEnBotonesMuertos` (1193 -> 1202, 0,8% PEOR). Cuando BL.21744
descubrio que el banco tenia el objetivo fuera de la reticula de 19 de los 25 mundos, la pregunta
inmediata fue si ese rechazo lo habia decidido un instrumento roto. La respuesta es no, y esto lo
demuestra: la colocacion del objetivo NO toca la columna que decidio.

Vive en su propio archivo desde la correccion del 2026-08-19: el guard de alcanzabilidad y esta
acta responden preguntas distintas, y juntos pasaban el limite de 500 lineas del repo.

A QUE PROFUNDIDAD VALE CADA AFIRMACION (medido, no supuesto). `accionesEnBotonesMuertos` es
invariante a 40 y tambien a los 200 pasos del protocolo real. Las otras columnas NO: a 200 pasos
`pasosProductivos` se mueve (3074 contra 3072) porque al cobrar un nivel el objetivo se RECOLOCA y
ese paso pasa a contar como productivo, y la geometria clavada llega a cobrar un nivel via el
barrido del repintado. Por eso el test de las columnas ajenas corre a las DOS profundidades y
declara en cada una lo que de verdad se sostiene, en vez de calibrar a 40 y extrapolar -- que es
exactamente el error que este mismo BL denuncio para el costo del gate."""
from __future__ import annotations

import random

from arc_agent.types import ActionDecision, GameAction

from tests.support.geometria_de_mundos import ALTO_TABLERO, posicion_del_objetivo
from tests.support import mundos_medidos
from tests.support.lazo_cerrado import PASOS_POR_PARTIDA, jugar, totales
from tests.support.mundos_medidos import MUNDOS


def _decision(boton: str, x: int | None = None, y: int | None = None) -> ActionDecision:
    return ActionDecision(action=GameAction[boton], x=x, y=y)


#: MEDIDO en la verificacion de BL.21744, corriendo el banco VIEJO (`git show 6f6afbb2f0^`, el de
#: la geometria con el objetivo clavado) y el de HOY con la MISMA politica de dev, la misma semilla
#: ("lazo") y los mismos 40 pasos por juego:
#:
#:   columna                     banco viejo   banco de hoy
#:   accionesEnBotonesMuertos             65             65   <- IDENTICO
#:   juegosConMapeoResuelto               16             16   <- IDENTICO
#:   niveles                               0             10
#:   pasosProductivos                    159            236
#:   distancia                           607            626
#:
#: De ahi sale el veredicto sobre BL.21594: se lo rechazo por `accionesEnBotonesMuertos`
#: (1193 -> 1202, o sea 0,8% PEOR), y esa columna NO la toca la colocacion del objetivo, asi que
#: NO fue descartado por el instrumento roto. Lo que si hay que tachar de su acta es "niveles
#: EMPATARON": esa columna era cero por construccion en 19 de 25 mundos y no podia devolver otra
#: cosa. Este test deja la invariancia como PROPIEDAD verificada y no como parrafo de un commit.
MUNDOS_CON_OBJETIVO_MOVIDO_MINIMO = 10


class _PoliticaDeGuion:
    """Politica de GUION: repite un ciclo fijo de botones e IGNORA el frame. Es lo que permite
    aislar la variable -- dos corridas con EXACTAMENTE las mismas acciones y distinta colocacion
    del objetivo -- que con una politica real no se podria, porque veria frames distintos y
    elegiria distinto."""

    def __init__(self, mundo) -> None:
        botones = [f"ACTION{n}" for n in mundo.acciones if n != 6]
        self._ciclo = botones + ["ACTION6"]
        self._i = 0

    def decide(self, frame) -> ActionDecision:
        boton = self._ciclo[self._i % len(self._ciclo)]
        self._i += 1
        if boton == "ACTION6":
            return _decision("ACTION6", 7 + self._i % 40, 5 + self._i % 30)
        return _decision(boton)


def _otra_colocacion(mundo, rng=None, avatar=None) -> tuple[int, int]:
    """La MISMA regla de colocacion pero con otro sorteo: el objetivo cae en una celda distinta e
    igual de legitima de la reticula del mundo."""
    return posicion_del_objetivo(mundo, rng or random.Random("otra-colocacion"), avatar)


#: Las DOS profundidades a las que se verifica el acta. 40 es la del experimento original; 200 es
#: `PASOS_POR_PARTIDA`, o sea la que usan de verdad el banco de la valvula de Kaggle y el gate. Una
#: propiedad verificada solo a 40 no puede sostener una conclusion sobre corridas de 200 -- es el
#: mismo error de calibracion que este BL denuncio para el costo del gate, y la refutacion del
#: 2026-08-19 mostro que aca se habia cometido: a 200 pasos `pasosProductivos` SI se mueve.
PROFUNDIDADES_VERIFICADAS = (40, PASOS_POR_PARTIDA)

#: La UNICA columna sobre la que se decidio el rechazo de BL.21594. Es la que tiene que ser
#: invariante a la colocacion del objetivo a CUALQUIER profundidad, y la que se verifica en las dos.
COLUMNA_QUE_DECIDIO = "accionesEnBotonesMuertos"


def _correr_el_guion(pasos: int = 40) -> dict[str, dict[str, object]]:
    return {
        m.nombre: jugar(m, lambda _rng, mundo=m: _PoliticaDeGuion(mundo), pasos, "invariancia")
        for m in MUNDOS
    }


def test_la_metrica_que_decide_no_depende_de_donde_este_el_objetivo(monkeypatch) -> None:
    """PROPIEDAD: con las MISMAS acciones, `accionesEnBotonesMuertos` da lo mismo aunque el
    objetivo se mueva. De ella depende que el rechazo de BL.21594 siga en pie, y es la que habria
    que romper para que un arreglo de geometria futuro invalide esa acta sin que nadie se entere."""
    movidos = [m.nombre for m in MUNDOS if _otra_colocacion(m) != posicion_del_objetivo(m)]
    assert len(movidos) >= MUNDOS_CON_OBJETIVO_MOVIDO_MINIMO, sorted(movidos)

    for pasos in PROFUNDIDADES_VERIFICADAS:
        with monkeypatch.context() as parche:
            guion = _correr_el_guion(pasos)
            assert sum(int(f[COLUMNA_QUE_DECIDIO]) for f in guion.values()) >= 1, (
                "el guion no gasto una sola accion en un boton muerto: el test no probaria nada"
            )
            parche.setattr(mundos_medidos, "posicion_del_objetivo", _otra_colocacion)
            movido = _correr_el_guion(pasos)

        for nombre, fila in guion.items():
            assert fila["porAccion"] == movido[nombre]["porAccion"], f"{nombre} a {pasos} pasos"
            assert fila[COLUMNA_QUE_DECIDIO] == movido[nombre][COLUMNA_QUE_DECIDIO], (
                f"{nombre} a {pasos} pasos: la metrica que decide un merge cambio al mover el "
                "objetivo -- si eso pasa, el acta de BL.21594 hay que rehacerla"
            )


#: Columnas que el banco reporta y que NO son `niveles`. A 40 pasos ninguna se mueve al cambiar
#: donde esta el objetivo. A los 200 del protocolo real si se mueve `pasosProductivos` (la
#: recolocacion del objetivo al cobrar un nivel cuenta como paso productivo), y el test de abajo lo
#: declara como cota en vez de afirmar que la colocacion "no entra en ninguna otra cuenta" -- que
#: era falso a la profundidad que el proyecto usa de verdad.
COLUMNAS_AJENAS_AL_OBJETIVO = (
    "accionesEnBotonesMuertos",
    "clicksProductivos",
    "distancia",
    "juegosConMapeoResuelto",
    "pasosHastaMapeoResuelto",
    "pasosProductivos",
)


def _colocacion_clavada(mundo, rng=None, avatar=None) -> tuple[int, int]:
    """La colocacion EXACTA de antes de BL.21744: la misma constante para los 25 mundos, sin mirar
    la mecanica de ninguno. Es la geometria rota, reproducida tal cual."""
    return (ALTO_TABLERO - 4, 3)


def test_con_la_geometria_ROTA_de_antes_la_columna_que_decidio_no_se_mueve(monkeypatch) -> None:
    """EL TEST QUE SOSTIENE EL ACTA DE BL.21594, con la variable AISLADA y a las DOS profundidades.

    El test de mas arriba mueve el objetivo a OTRA celda legitima de la reticula. Esto es distinto y
    mas fuerte: reproduce la geometria ROTA de verdad -- el objetivo clavado en la celda (57, 3)
    para los 25 mundos, que es lo que habia cuando se midio BL.21594 -- y compara TODAS las columnas
    del banco contra las de hoy, con las mismas acciones y la misma semilla.

    QUE SE SOSTIENE Y A QUE PROFUNDIDAD (medido 2026-08-18 y re-medido a 200 el 2026-08-19):

      - `accionesEnBotonesMuertos`, la columna que DECIDIO el rechazo: identica a 40 pasos (65
        contra 65) y tambien a 200 (564 contra 564). El acta de BL.21594 queda en pie: el defecto
        del banco no podia tocar esa columna ni un entero.
      - Las otras cinco columnas ajenas: identicas a 40 pasos. A 200 se mueve `pasosProductivos`
        (3074 contra 3072), y por una razon concreta -- al cobrar un nivel el objetivo se RECOLOCA,
        el tablero cambia y ese paso pasa a contar como productivo. O sea que a la profundidad real
        la colocacion SI entra en una segunda cuenta, y el docstring que decia que no entraba en
        ninguna estaba calibrado a 40 pasos. Queda verificado como COTA: la unica columna que puede
        moverse ademas de `niveles` es esa.
      - `niveles`: la geometria clavada mide estrictamente MENOS que la de hoy a las dos
        profundidades. A 40 da cero; a 200 ya no es cero (re86 llega por el barrido del repintado),
        asi que la afirmacion fuerte que vale es la comparativa, no el cero absoluto."""
    for pasos in PROFUNDIDADES_VERIFICADAS:
        with monkeypatch.context() as parche:
            guion = _correr_el_guion(pasos)
            parche.setattr(mundos_medidos, "posicion_del_objetivo", _colocacion_clavada)
            roto = _correr_el_guion(pasos)

        totales_hoy, totales_roto = totales(guion), totales(roto)
        movidas = {c for c in COLUMNAS_AJENAS_AL_OBJETIVO if totales_hoy[c] != totales_roto[c]}

        assert COLUMNA_QUE_DECIDIO not in movidas, (
            f"a {pasos} pasos, {COLUMNA_QUE_DECIDIO} cambio al volver a la geometria clavada "
            f"({totales_roto[COLUMNA_QUE_DECIDIO]} contra {totales_hoy[COLUMNA_QUE_DECIDIO]}): la "
            "columna que decidio el rechazo de BL.21594 dejo de estar a salvo del instrumento roto "
            "y el acta hay que rehacerla"
        )
        esperadas = set() if pasos <= 40 else {"pasosProductivos"}
        assert movidas <= esperadas, (
            f"a {pasos} pasos se movieron columnas ajenas no declaradas: {sorted(movidas)}. Cada "
            "columna que dependa de donde esta el objetivo es una via por la que un cambio de "
            "geometria puede simular una mejora, asi que hay que medirla y declararla aca"
        )
        assert totales_hoy["niveles"] > totales_roto["niveles"], (
            f"a {pasos} pasos la geometria clavada midio {totales_roto['niveles']} niveles y la de "
            f"hoy {totales_hoy['niveles']}: si la rota deja de medir menos, el arreglo de geometria "
            "se perdio"
        )
