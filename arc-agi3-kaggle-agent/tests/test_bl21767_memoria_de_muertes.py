"""[arc-agi3-kaggle-agent/tests/test_bl21767_memoria_de_muertes] BL.21767 -- GAME_OVER como HECHO
del modelo de mundo.

QUE PROTEGE, en orden de lo que mas duele romper:

 1. EL HECHO SE REGISTRA CON SU CONTEXTO. Antes del BL, `kaggle_adapter` disfrazaba el GAME_OVER
    de NOT_STARTED y el evento mas informativo de la partida se procesaba como el arranque: el
    agente no tenia DONDE anotar la muerte (sp80: 6 GAME_OVERs en 151 acciones, 0 niveles).
 2. EL DESCUENTO NO ES UN LOCKOUT. Se agota por aplicacion, lo gasta la supervivencia observada
    del mismo par y lo re-arma una muerte nueva -- el mismo cuidado que BL.21518 exigio del lado
    de los no-ops.
 3. SIN LA PALANCA, CERO DELTA. Con `memoriaDeMuertes` apagada las decisiones son IDENTICAS a las
    del agente anterior (que veia NOT_STARTED donde habia GAME_OVER): es la condicion para que el
    gate de merge pueda atribuirle el delta a la palanca y a ninguna otra cosa.
 4. EL INSTRUMENTO DE LOCALIDAD (scripts/medicion_de_muertes.py) clasifica bien: la exigencia
    expresa del BL es MEDIR si la muerte es local o de cadena ANTES de elegir mecanismo, y un
    clasificador roto convertiria la medicion en ruido con formato de veredicto.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from medicion_de_muertes import analizar_localidad, resumir_partida  # noqa: E402

from arc_agent.banderas import (  # noqa: E402
    BANDERAS_CONOCIDAS,
    MEMORIA_DE_MUERTES,
    Banderas,
)
from arc_agent.exploration_memory import (  # noqa: E402
    CASTIGO_POR_MUERTE_USOS,
    MemoriaDeMuertes,
    rank_candidates,
)
from arc_agent.policy import ExplorationPolicy  # noqa: E402
from arc_agent.prng import create_seeded_random  # noqa: E402
from arc_agent.types import FrameData, GameAction, GameState  # noqa: E402

SIN_PALANCAS = Banderas(())
SOLO_MUERTES = Banderas((MEMORIA_DE_MUERTES,))


# ============================================================================================
# banderas.py -- la palanca existe y es medible por separado
# ============================================================================================


def test_la_palanca_existe_y_se_enciende_sola() -> None:
    assert MEMORIA_DE_MUERTES in BANDERAS_CONOCIDAS
    banderas = Banderas.desde_texto(f"ninguna,+{MEMORIA_DE_MUERTES}")
    assert banderas.activas == (MEMORIA_DE_MUERTES,)


# ============================================================================================
# MemoriaDeMuertes -- el hecho y su descuento agotable
# ============================================================================================


def test_la_muerte_se_registra_con_todo_su_contexto() -> None:
    memoria = MemoriaDeMuertes()
    memoria.registrar_transicion(
        111, "ACTION6", murio=True, click=(7, 9), con_macro=True, paso=42
    )
    assert memoria.muertes_registradas == 1
    hecho = memoria.hechos[0]
    assert (hecho.firma, hecho.accion) == (111, "ACTION6")
    assert hecho.click == (7, 9)
    assert hecho.con_macro is True
    assert hecho.paso == 42


def test_castigadas_solo_desde_la_firma_que_mato() -> None:
    memoria = MemoriaDeMuertes()
    memoria.registrar_transicion(111, "ACTION1", murio=True)
    assert memoria.castigadas(111, (1, 2, 3)) == {GameAction.ACTION1}
    assert memoria.castigadas(222, (1, 2, 3)) == set()  # otra firma: otra evidencia
    assert memoria.castigadas(111, (2, 3)) == set()  # la accion no esta disponible


def test_el_descuento_se_agota_por_aplicacion_nunca_es_lockout() -> None:
    memoria = MemoriaDeMuertes()
    memoria.registrar_transicion(111, "ACTION1", murio=True)
    for _ in range(CASTIGO_POR_MUERTE_USOS):
        assert memoria.castigadas(111, (1,)) == {GameAction.ACTION1}
        memoria.aplicar_castigo(111, "ACTION1")
    # Agotado: la accion vuelve al ranking normal -- "mato una vez" no es "mata siempre".
    assert memoria.castigadas(111, (1,)) == set()
    assert memoria.evidencia_de(111, "ACTION1")["muertes"] == 1


def test_la_supervivencia_del_mismo_par_gasta_el_descuento() -> None:
    memoria = MemoriaDeMuertes()
    memoria.registrar_transicion(111, "ACTION1", murio=True)
    for _ in range(CASTIGO_POR_MUERTE_USOS):
        memoria.registrar_transicion(111, "ACTION1", murio=False)
    assert memoria.castigadas(111, (1,)) == set()
    assert memoria.evidencia_de(111, "ACTION1")["supervivencias"] == CASTIGO_POR_MUERTE_USOS


def test_una_muerte_nueva_rearma_el_descuento() -> None:
    memoria = MemoriaDeMuertes()
    memoria.registrar_transicion(111, "ACTION1", murio=True)
    for _ in range(CASTIGO_POR_MUERTE_USOS - 1):
        memoria.aplicar_castigo(111, "ACTION1")
    memoria.registrar_transicion(111, "ACTION1", murio=True)
    assert memoria.evidencia_de(111, "ACTION1")["castigoRestante"] == CASTIGO_POR_MUERTE_USOS


def test_sobrevivir_un_par_que_nunca_mato_no_crea_filas() -> None:
    """La memoria es O(muertes), no O(pasos): cada paso del episodio pasa por aca."""
    memoria = MemoriaDeMuertes()
    for paso in range(100):
        memoria.registrar_transicion(paso, "ACTION1", murio=False)
    assert memoria.muertes_registradas == 0
    assert memoria.evidencia_de(0, "ACTION1") == {
        "muertes": 0,
        "supervivencias": 0,
        "castigoRestante": 0,
    }


# ============================================================================================
# rank_candidates -- relegar no es excluir, y no toca el rng
# ============================================================================================


def _rng_contado(semilla: str):
    rng = create_seeded_random(semilla)
    llamadas = [0]

    def contado() -> float:
        llamadas[0] += 1
        return rng()

    return contado, llamadas


def test_la_castigada_va_al_fondo_pero_nunca_se_filtra() -> None:
    rng = create_seeded_random("bl21767")
    orden = rank_candidates((1, 2, 3), {}, set(), rng, castigadas={GameAction.ACTION1})
    assert orden[-1] is GameAction.ACTION1
    assert set(orden) == {GameAction.ACTION1, GameAction.ACTION2, GameAction.ACTION3}


def test_todas_castigadas_no_vacia_la_lista() -> None:
    rng = create_seeded_random("bl21767")
    castigo = {GameAction.ACTION1, GameAction.ACTION2}
    orden = rank_candidates((1, 2), {}, set(), rng, castigadas=castigo)
    assert set(orden) == castigo  # relegar todas = no relegar ninguna: algo se elige igual


def test_una_premiada_no_se_relega_el_progreso_real_gana() -> None:
    rng = create_seeded_random("bl21767")
    orden = rank_candidates(
        (1, 2, 3),
        {},
        set(),
        rng,
        rewarded_actions={GameAction.ACTION1},
        castigadas={GameAction.ACTION1},
    )
    assert orden[0] is GameAction.ACTION1


def test_el_castigo_no_consume_numeros_del_rng() -> None:
    """Reproducibilidad por seed: la secuencia del rng no puede depender del contenido de la
    memoria de muertes (mismo criterio que la particion de premiadas, BL.21557)."""
    rng_a, llamadas_a = _rng_contado("bl21767")
    rng_b, llamadas_b = _rng_contado("bl21767")
    sin = rank_candidates((1, 2, 3), {}, set(), rng_a)
    con = rank_candidates((1, 2, 3), {}, set(), rng_b, castigadas={GameAction.ACTION2})
    assert llamadas_a[0] == llamadas_b[0]
    assert [a for a in sin if a is not GameAction.ACTION2] == [
        a for a in con if a is not GameAction.ACTION2
    ]


# ============================================================================================
# ExplorationPolicy -- el lazo completo contra un entorno que MATA
# ============================================================================================


class PasilloConPozo:
    """La patologia de sp80, en juguete: la accion que mata sigue siendo ATRACTIVA para la
    exploracion. ACTION1 avanza hacia el pozo (en la celda 2, muere); ACTION2 vuelve al arranque,
    siempre viva. El ranker de novedad prefiere ACTION1 desde el borde del pozo -- su destino (el
    frame terminal) siempre esta menos visitado que el arranque, adonde vuelve ACTION2 -- y la
    macro comprometida re-emite ACTION1 sin pasar por el ranking: las DOS vias por las que el
    agente real re-muere. Tras el GAME_OVER el RESET repone el arranque: la partida SIGUE."""

    DISPONIBLES = (1, 2)
    LADO = 8

    def __init__(self) -> None:
        self._pos = 0
        self._guid = 0
        self.muertes = 0

    def _frame(self, estado: GameState) -> FrameData:
        self._guid += 1
        filas = [[0] * self.LADO for _ in range(self.LADO)]
        if estado is GameState.GAME_OVER:
            filas[4][7] = 9  # el pozo: un frame terminal propio, identico entre muertes
        else:
            filas[4][self._pos] = 5  # el avatar
        return FrameData(
            game_id="pozo",
            guid=f"g{self._guid}",
            frame=(tuple(tuple(f) for f in filas),),
            state=estado,
            available_actions=self.DISPONIBLES,
        )

    def frame(self) -> FrameData:
        return self._frame(GameState.NOT_FINISHED)

    def step(self, accion: GameAction) -> FrameData:
        if accion is GameAction.RESET:
            self._pos = 0
            return self.frame()
        if accion is GameAction.ACTION1:
            self._pos += 1
            if self._pos >= 2:
                self._pos = 0
                self.muertes += 1
                return self._frame(GameState.GAME_OVER)
        elif accion is GameAction.ACTION2:
            self._pos = 0
        return self.frame()


def _correr(banderas: Banderas, pasos: int = 80, semilla: str = "bl21767"):
    entorno = PasilloConPozo()
    politica = ExplorationPolicy(create_seeded_random(semilla), banderas)
    frame = entorno.frame()
    acciones: list[GameAction] = []
    for _ in range(pasos):
        decision = politica.decide(frame)
        acciones.append(decision.action)
        frame = entorno.step(decision.action)
    # BL.21913 -- DRENAJE FINAL, y por que el banco lo necesita. `registrar_transicion` corre DENTRO
    # de `decide` observando la transicion ANTERIOR: es la unica forma de saber en que estado
    # TERMINO la accion. Entonces el ultimo `step` del lazo queda sin observar mientras no haya un
    # `decide` mas, y la memoria reportaba una muerte MENOS que el entorno (26 contra 27, medido).
    # No era un bug de produccion: el adaptador real siempre vuelve a decidir despues de un
    # GAME_OVER — lo cubre `test_el_game_over_llega_a_la_politica_y_responde_reset`. Lo que faltaba
    # era que el arnes cerrara el lazo como lo cierra el runtime. La decision NO se agrega a
    # `acciones` ni se ejecuta contra el entorno: solo se le da a la politica la chance de OBSERVAR.
    politica.decide(frame)
    return politica, acciones, entorno


def test_el_game_over_llega_a_la_politica_y_responde_reset() -> None:
    """La rama terminal cubre GAME_OVER sin disfraz del adaptador: RESET y a seguir."""
    politica = ExplorationPolicy(create_seeded_random("bl21767"))
    entorno = PasilloConPozo()
    decision = politica.decide(entorno._frame(GameState.GAME_OVER))
    assert decision.action is GameAction.RESET


def test_la_muerte_del_lazo_queda_anotada_con_firma_y_accion() -> None:
    politica, _, entorno = _correr(SIN_PALANCAS)
    assert entorno.muertes > 0, "el entorno de juguete tiene que matar para ejercitar el BL"
    memoria = politica.memoria_de_muertes
    assert memoria.muertes_registradas == entorno.muertes
    # Toda muerte del pasillo la produce ACTION1 (la unica accion que llega al pozo).
    assert {hecho.accion for hecho in memoria.hechos} == {GameAction.ACTION1.value}


def test_con_la_palanca_muere_menos_que_sin_ella() -> None:
    """EL EFECTO, no la plomeria: mismo seed, mismo entorno; la unica diferencia es la palanca.
    Sin ella el agente re-elige la accion que ya lo mato (la novedad del contador la mantiene
    atractiva, como en sp80); con ella la relega mientras el descuento dura."""
    _, _, entorno_sin = _correr(SIN_PALANCAS)
    _, _, entorno_con = _correr(SOLO_MUERTES)
    assert entorno_con.muertes < entorno_sin.muertes


def test_sin_la_palanca_las_decisiones_son_identicas_al_agente_anterior() -> None:
    """El agente ANTERIOR veia NOT_STARTED donde habia GAME_OVER (mascara del adaptador). Con la
    palanca apagada, pasar el GAME_OVER crudo tiene que producir EXACTAMENTE las mismas
    decisiones: si esto se rompe, el gate no puede atribuirle el delta a la palanca."""
    entorno_nuevo = PasilloConPozo()
    entorno_viejo = PasilloConPozo()
    politica_nueva = ExplorationPolicy(create_seeded_random("bl21767"), SIN_PALANCAS)
    politica_vieja = ExplorationPolicy(create_seeded_random("bl21767"), SIN_PALANCAS)
    frame_nuevo = entorno_nuevo.frame()
    frame_viejo = entorno_viejo.frame()
    for paso in range(90):
        decision_nueva = politica_nueva.decide(frame_nuevo)
        # La mascara historica del adaptador, reproducida: GAME_OVER -> NOT_STARTED.
        enmascarado = (
            replace(frame_viejo, state=GameState.NOT_STARTED)
            if frame_viejo.state is GameState.GAME_OVER
            else frame_viejo
        )
        decision_vieja = politica_vieja.decide(enmascarado)
        assert decision_nueva.action is decision_vieja.action, f"paso {paso}"
        assert (decision_nueva.x, decision_nueva.y) == (decision_vieja.x, decision_vieja.y)
        frame_nuevo = entorno_nuevo.step(decision_nueva.action)
        frame_viejo = entorno_viejo.step(decision_vieja.action)


# ============================================================================================
# scripts/medicion_de_muertes.py -- el clasificador de localidad
# ============================================================================================


def _muerte(contexto: list[str], accion: int = 10) -> dict:
    return {"accion": accion, "contexto": contexto, "conMacroEnCurso": False, "nivelesAlMorir": 0}


def test_localidad_local_mismo_par_inmediato_y_letal() -> None:
    muertes = [_muerte(["a", "X"]), _muerte(["b", "X"])]
    analisis = analizar_localidad(muertes, {"X": 2, "a": 1, "b": 1})
    assert analisis["veredicto"] == "local"
    assert analisis["porProfundidad"]["1"]["letalidadDelParMasRepetido"] == 1.0


def test_localidad_local_debil_el_par_inmediato_casi_siempre_sobrevive() -> None:
    muertes = [_muerte(["a", "X"]), _muerte(["b", "X"])]
    analisis = analizar_localidad(muertes, {"X": 20, "a": 1, "b": 1})
    assert analisis["veredicto"] == "localDebil"


def test_localidad_cadena_el_patron_esta_mas_atras() -> None:
    """Los pares inmediatos difieren entre muertes, pero a profundidad 2 se repite el mismo par:
    penalizar la ultima accion seria supersticion -- el veredicto tiene que decirlo."""
    muertes = [_muerte(["C", "x"]), _muerte(["C", "y"])]
    analisis = analizar_localidad(muertes, {"C": 2, "x": 1, "y": 1})
    assert analisis["veredicto"] == "cadena"


def test_localidad_sin_patron_repetido() -> None:
    muertes = [_muerte(["a", "x"]), _muerte(["b", "y"])]
    analisis = analizar_localidad(muertes, {"a": 1, "x": 1, "b": 1, "y": 1})
    assert analisis["veredicto"] == "sinPatronRepetido"


def test_localidad_sin_muertes() -> None:
    assert analizar_localidad([], {})["veredicto"] == "sinMuertes"


def test_resumir_partida_deriva_el_presupuesto_perdido_por_morir() -> None:
    """Las acciones de cada tramo que TERMINO en muerte: 30 del arranque a la primera, 20 de ahi
    a la segunda -- 50 de 100 = mitad del presupuesto en trayectorias mortales."""
    fila = resumir_partida(
        "sp80",
        "s1",
        acciones=100,
        niveles=0,
        muertes=[_muerte(["a"], accion=30), _muerte(["b"], accion=50)],
        conteo_de_pares={"a": 1, "b": 1},
        estado_final="GameState.NOT_FINISHED",
    )
    assert fila["gameOvers"] == 2
    assert fila["accionesEnTrayectoriasMortales"] == 50
    assert fila["fraccionDelPresupuestoEnTrayectoriasMortales"] == 0.5
