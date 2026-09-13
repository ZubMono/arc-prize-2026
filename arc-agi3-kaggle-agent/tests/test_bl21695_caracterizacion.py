"""[arc-agi3-kaggle-agent/tests] BL.21695 paso 1 -- CARACTERIZACION de los completados
capturados y presupuesto del barrido.

Estos tests fijan los CRITERIOS con los que se cuenta evidencia a favor de cada candidato a
objetivo. Un criterio que da positivo donde no corresponde (el caso clasico: el color del propio
avatar, que siempre esta a distancia 0 de si mismo) infla la cobertura aparente del vocabulario y
lleva a postular una categoria que el dato no sostiene.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from barrido_de_captura import (  # noqa: E402
    ACCIONES_POR_CORRIDA,
    JUEGOS_QUE_CLICKEAN,
    JUEGOS_QUE_PUNTUAN,
    SEMILLAS_POR_JUEGO,
    plan_de_corridas,
)
from caracterizacion_de_niveles import (  # noqa: E402
    componente_bajo_el_click,
    conteos_por_color,
    distancia_a_colores,
    fraccion_no_fondo,
    medir_evento,
    trayectoria_del_movil,
)
from caracterizar_completados import (  # noqa: E402
    prueba_de,
    resumen_de_candidatos,
    se_sostiene,
    transiciones_distintas,
)


# --- Caracterizacion ---------------------------------------------------------------------------


def _ventana(
    grillas: list[list[list[int]]],
    paso_del_evento: int,
    juego: str = "j1",
    click_del_evento: tuple[int, int] | None = None,
) -> dict:
    frames = []
    for i, grilla in enumerate(grillas):
        es_evento = i == paso_del_evento and click_del_evento is not None
        frames.append(
            {
                "paso": i,
                "accion": "ACTION6" if es_evento else "ACTION1",
                "x": click_del_evento[0] if es_evento else None,
                "y": click_del_evento[1] if es_evento else None,
                "accionesDisponibles": [1, 2, 3, 4],
                "grilla": grilla,
                "nivelesCompletados": 1 if i >= paso_del_evento else 0,
                "nivelesParaGanar": 3,
                "estado": "NOT_FINISHED",
                "reinicioCompleto": False,
            }
        )
    return {
        "juego": juego,
        "corrida": f"harness-local:{juego}:t",
        "modelo": "harness-local",
        "pasoDelEvento": paso_del_evento,
        "nivelPrevio": 0,
        "nivelNuevo": 1,
        "framesAntes": paso_del_evento,
        "framesDespues": len(grillas) - paso_del_evento - 1,
        "frames": frames,
    }


def _tablero(coloreadas: dict[tuple[int, int], int], lado: int = 12) -> list[list[int]]:
    grilla = [[0 for _ in range(lado)] for _ in range(lado)]
    for (y, x), color in coloreadas.items():
        grilla[y][x] = color
    return grilla


def test_conteos_por_color_usa_las_componentes_conexas_existentes():
    grilla = _tablero({(1, 1): 7, (1, 2): 7, (5, 5): 7, (8, 8): 3})
    conteos = conteos_por_color(grilla)
    assert conteos[7].celdas == 3 and conteos[7].componentes == 2
    assert conteos[3].celdas == 1 and conteos[3].componentes == 1
    assert 0 not in conteos  # el fondo no se cuenta como objeto


def test_fraccion_no_fondo_mide_ocupacion():
    assert fraccion_no_fondo(_tablero({(0, 0): 4}, lado=10)) == 0.01


def test_distancia_a_colores_es_chebyshev():
    grilla = _tablero({(0, 0): 4})
    assert distancia_a_colores(grilla, centro_y=3.0, centro_x=4.0)[4] == 4


#: Indice del frame del evento en `_grillas_de_recoleccion`. La recoleccion COMPLETA ocurre en los
#: cuatro primeros frames y el evento es el QUINTO: desde BL.21728 los criterios de objetivo se
#: evaluan sin el frame del evento, asi que una fixture donde el ultimo coleccionable desaparece
#: JUSTO en el evento no probaria recoleccion -- probaria el artefacto que ese BL vino a sacar.
EVENTO_DE_RECOLECCION = 4


def _grillas_de_recoleccion() -> list[list[list[int]]]:
    """Tres coleccionables que desaparecen de a uno DURANTE la maniobra, y recien despues el
    tablero se rehace: la firma de RECOLECTAR-TODO."""
    puntos = [(2, 2), (4, 4), (6, 6)]
    grillas = []
    for restantes in (3, 2, 1, 0):
        grillas.append(_tablero({p: 7 for p in puntos[:restantes]}))
    grillas.append(_tablero({(0, 0): 9, (0, 1): 9}))
    return grillas


def test_recoleccion_deja_el_color_agotado_y_el_vaciado_monotono():
    medicion = medir_evento(
        _ventana(_grillas_de_recoleccion(), paso_del_evento=EVENTO_DE_RECOLECCION)
    )
    assert medicion is not None
    # La maniobra -- no el frame del evento -- es la que agota el color y vacia el tablero.
    assert medicion.maniobra.colores_agotados_en_la_maniobra == (7,)
    assert medicion.maniobra.vaciado_monotono_en_la_maniobra is True
    assert medicion.maniobra.llenado_monotono_en_la_maniobra is False
    assert se_sostiene("recolectarTodo", medicion) is True
    assert se_sostiene("pintarRegion", medicion) is False


#: Indice del frame del evento en `_grillas_de_llegada`. La LLEGADA ocurre en el ultimo frame de la
#: maniobra y el evento es el siguiente, por la misma razon que en `_grillas_de_recoleccion`: desde
#: BL.21728 `alcanzarDestino` se evalua sin el frame del evento.
EVENTO_DE_LLEGADA = 6


def _grillas_de_llegada() -> list[list[list[int]]]:
    """Un bloque 2x2 movil que se acerca a una columna estatica hasta quedar pegado, y recien
    despues el tablero se rehace: la firma de ALCANZAR-DESTINO."""
    grillas = []
    for columna in (2, 3, 4, 5, 6, 7):
        celdas = {(4, 9): 7, (5, 9): 7}
        for dy in (0, 1):
            for dx in (0, 1):
                celdas[(4 + dy, columna + dx)] = 5
        grillas.append(_tablero(celdas))
    grillas.append(_tablero({(0, 0): 3, (0, 1): 3}))
    return grillas


def test_llegada_detecta_traslacion_y_aproximacion_monotona():
    ventana = _ventana(_grillas_de_llegada(), paso_del_evento=EVENTO_DE_LLEGADA)
    # Sobre los frames de la MANIOBRA: el frame del evento rehace el tablero y lo que se detecte
    # ahi no es el movimiento del avatar.
    posiciones = trayectoria_del_movil(ventana["frames"][:EVENTO_DE_LLEGADA])
    assert len(posiciones) >= 3
    assert all(p.dx > 0 and p.dy == 0 for p in posiciones)

    medicion = medir_evento(ventana)
    assert medicion is not None
    assert medicion.pasos_con_traslacion >= 3
    assert 7 in medicion.aproximacion_monotona
    assert 7 in medicion.colores_alcanzados
    assert se_sostiene("alcanzarDestino", medicion) is True


def test_el_color_del_propio_movil_no_alcanza_para_alcanzar_destino():
    # El bloque movil esta SIEMPRE a distancia 0 de su propio color: si el criterio no exigiera que
    # el color alcanzado sea el mismo que se aproximo, cualquier juego con un avatar daria positivo.
    ventana = _ventana(_grillas_de_llegada(), paso_del_evento=EVENTO_DE_LLEGADA)
    medicion = medir_evento(ventana)
    assert medicion is not None
    assert 5 in medicion.colores_alcanzados
    assert 5 not in medicion.aproximacion_monotona


def test_sin_frame_previo_no_hay_evento_que_medir():
    ventana = _ventana([_tablero({(0, 0): 4})], paso_del_evento=0)
    assert medir_evento(ventana) is None


# --- Presupuesto del barrido ------------------------------------------------------------------


def test_el_barrido_cuesta_menos_que_correr_el_mismo_plan_al_tope_del_entregable():
    # La razon de ser del presupuesto acotado: la maquina ya colapso una vez por mediciones, y
    # BL.21783 midio que el tramo 1.600 -> 4.000 suma UN nivel por semilla DENTRO del ruido (desvio
    # entre semillas 1,58). Pagar profundidad compra ruido; la muestra la compran las semillas.
    plan = plan_de_corridas(list(JUEGOS_QUE_PUNTUAN))
    assert ACCIONES_POR_CORRIDA < 4000
    assert sum(c.pasos for c in plan) < 4000 * len(plan)
    # Y el presupuesto tiene que cubrir los momentos de llegada MEDIDOS con el agente de hoy
    # (BL.21783): 93 g50t, 128 ft09, 558-734 sc25 (tres niveles), 68 lp85, 2-4 vc33.
    assert ACCIONES_POR_CORRIDA >= 734


def test_el_barrido_gasta_la_cpu_en_semillas_y_no_en_profundidad():
    # CORRECCION DE BL.21794. Hasta este BL el plan ajustaba el presupuesto de cada juego a los
    # pasos en que habia subido de nivel en el mapa VIEJO. BL.21783 volvio a medir con el agente y
    # el banco de hoy: "ninguna de las accion es de subida del mapa viejo se reproduce" -- g50t
    # subia en 154 y ahora sube en 93 con una semilla y en 1.939 con otra, un factor de 20. Un
    # presupuesto ajustado a numeros que ya no se reproducen no es ajuste. Lo que la evidencia SI
    # sostiene es que la muestra la compran las SEMILLAS, y eso es lo que este contrato fija.
    plan = plan_de_corridas(["vc33", "sc25"])
    assert len({c.pasos for c in plan}) == 1, "el presupuesto es UNO SOLO para todos los juegos"
    for juego in ("vc33", "sc25"):
        normales = [c for c in plan if c.juego == juego and c.fase == "normal"]
        assert len(normales) == SEMILLAS_POR_JUEGO
        assert len({c.semilla for c in normales}) == SEMILLAS_POR_JUEGO


def test_la_primera_ronda_cubre_todos_los_juegos_y_las_dos_fases():
    # El orden es por RONDA DE SEMILLA y no por juego: en un box compartido el barrido se corta
    # (BL.21763 alcanzo a medir UN juego de SEIS), y con el orden por juego un corte deja el corpus
    # con todas las semillas de los primeros y CERO de los ultimos -- el sesgo exacto que BL.21794
    # vino a sacar ("que ningun tipo quede sostenido por un solo mundo").
    plan = plan_de_corridas(list(JUEGOS_QUE_PUNTUAN))
    primera_ronda = [c for c in plan if c.semilla.endswith("1")]
    assert {c.juego for c in primera_ronda} == set(JUEGOS_QUE_PUNTUAN)
    assert {c.fase for c in primera_ronda} == {"normal", "fondo"}
    assert plan[: len(primera_ronda)] == primera_ronda


def test_la_fase_de_fondo_solo_toca_juegos_que_clickean():
    # g50t queda afuera con un numero medido: 0 coordenadas distintas clickeadas en 4.001 acciones
    # (BL.21783). Redirigirle clicks al fondo no redirige nada y solo gasta box.
    plan = plan_de_corridas(list(JUEGOS_QUE_PUNTUAN))
    de_fondo = {c.juego for c in plan if c.fase == "fondo"}
    assert de_fondo == set(JUEGOS_QUE_CLICKEAN)
    assert "g50t" not in de_fondo
    assert all(c.fraccion_al_fondo > 0 for c in plan if c.fase == "fondo")
    assert all(c.fraccion_al_fondo == 0 for c in plan if c.fase == "normal")


def test_el_click_que_resolvio_el_nivel_se_atribuye_a_la_componente_tocada():
    antes = _tablero({(2, 2): 7, (2, 3): 7, (8, 8): 3})
    despues = _tablero({(8, 8): 3})
    ventana = _ventana([antes, antes, despues], paso_del_evento=2, click_del_evento=(3, 2))
    medicion = medir_evento(ventana)
    assert medicion is not None
    assert medicion.accion_del_evento == "ACTION6"
    assert medicion.click_del_evento == (3, 2)
    assert (medicion.color_clickeado, medicion.celdas_de_la_componente_clickeada) == (7, 2)
    assert se_sostiene("resueltoTocandoUnObjeto", medicion) is True


def test_un_click_al_fondo_no_cuenta_como_tocar_un_objeto():
    antes = _tablero({(2, 2): 7})
    despues = _tablero({})
    ventana = _ventana([antes, antes, despues], paso_del_evento=2, click_del_evento=(11, 11))
    medicion = medir_evento(ventana)
    assert medicion is not None
    assert medicion.click_del_evento == (11, 11)
    assert medicion.color_clickeado is None
    assert se_sostiene("resueltoTocandoUnObjeto", medicion) is False


def test_componente_bajo_el_click_ignora_coordenadas_fuera_de_la_grilla():
    assert componente_bajo_el_click(_tablero({(1, 1): 5}), x=99, y=99) is None


def test_los_clusters_del_evento_se_desglosan_por_tipo():
    # Tres coleccionables que desaparecen a la vez: el desglose tiene que decir "3 desapariciones",
    # que es MAS informacion que la firma global (`detectar_mecanica` devuelve "desconocida" en
    # cuanto los clusters no son homogeneos).
    antes = _tablero({(2, 2): 7, (5, 5): 7, (8, 8): 7})
    despues = _tablero({})
    medicion = medir_evento(_ventana([antes, antes, despues], paso_del_evento=2))
    assert medicion is not None
    assert medicion.tipos_de_cluster.get("desaparicion") == 3
    assert medicion.sobre_el_tope_de_mecanica is False


def test_la_grilla_entera_de_64x64_ya_no_calla_al_detector():
    # BL.21741: con el tope MEDIDO (4096 = la grilla 64x64 completa), una transicion que reescribe
    # el tablero entero SI se analiza. Antes, con el tope de 2048 elegido a ojo, este era justo el
    # caso que el detector no miraba -- y las subidas de nivel son siempre el frame que mas cambia.
    from arc_agent.world_model.object_mechanics import MAX_CELDAS_CAMBIADAS

    antes = [[0 for _ in range(64)] for _ in range(64)]
    despues = [[3 if (y + x) % 2 else 5 for x in range(64)] for y in range(64)]
    medicion = medir_evento(_ventana([antes, antes, despues], paso_del_evento=2))
    assert medicion is not None
    assert medicion.celdas_cambiadas == 64 * 64 <= MAX_CELDAS_CAMBIADAS
    assert medicion.sobre_el_tope_de_mecanica is False
    assert medicion.tipos_de_cluster != {}
    assert medicion.pantalla_nueva is True
    assert prueba_de("eventoSobreElTopeDeMecanica")(medicion) is False


def test_por_encima_del_tope_el_informe_distingue_no_mire_de_no_hubo_cambios():
    # El informe tiene que poder distinguir "no vi clusters porque no hubo cambios" de "no vi
    # clusters porque cambio demasiado". Por encima del tope, `detectar_mecanica` NO analiza y lo
    # dice con tipo propio (`sobreElTope`, BL.21741) en vez de con un "desconocida" mudo.
    from arc_agent.world_model.object_mechanics import MAX_CELDAS_CAMBIADAS

    lado = 72  # 5.184 celdas: por encima del tope medido
    antes = [[0 for _ in range(lado)] for _ in range(lado)]
    despues = [[3 if (y + x) % 2 else 5 for x in range(lado)] for y in range(lado)]
    medicion = medir_evento(_ventana([antes, antes, despues], paso_del_evento=2))
    assert medicion is not None
    assert medicion.celdas_cambiadas > MAX_CELDAS_CAMBIADAS
    assert medicion.sobre_el_tope_de_mecanica is True
    assert medicion.tipos_de_cluster == {}
    assert medicion.firma_del_evento == "sobreElTope"
    assert prueba_de("eventoSobreElTopeDeMecanica")(medicion) is True


def test_el_resumen_marca_muestra_chica_con_un_solo_juego():
    mediciones = [
        medir_evento(_ventana(_grillas_de_recoleccion(), paso_del_evento=EVENTO_DE_RECOLECCION, juego="ft09")),
    ]
    resumen = resumen_de_candidatos([m for m in mediciones if m is not None])
    assert resumen["recolectarTodo"]["eventos"] == 1
    assert resumen["recolectarTodo"]["muestraChica"] is True


def test_varias_semillas_del_mismo_nivel_son_UNA_transicion():
    # 3 corridas que superan el nivel 1 de lp85 son 3 eventos pero UNA sola observacion del mundo.
    mediciones = [
        medir_evento(_ventana(_grillas_de_recoleccion(), paso_del_evento=EVENTO_DE_RECOLECCION, juego="lp85"))
        for _ in range(3)
    ]
    validas = [m for m in mediciones if m is not None]
    assert len(validas) == 3
    assert transiciones_distintas(validas) == {("lp85", 1)}
    resumen = resumen_de_candidatos(validas)
    assert resumen["recolectarTodo"]["eventos"] == 3
    assert resumen["recolectarTodo"]["transicionesDistintas"] == 1


def test_el_resumen_deja_de_marcar_muestra_chica_con_dos_juegos():
    mediciones = [
        medir_evento(_ventana(_grillas_de_recoleccion(), paso_del_evento=EVENTO_DE_RECOLECCION, juego="ft09")),
        medir_evento(_ventana(_grillas_de_recoleccion(), paso_del_evento=EVENTO_DE_RECOLECCION, juego="lp85")),
    ]
    resumen = resumen_de_candidatos([m for m in mediciones if m is not None])
    assert resumen["recolectarTodo"]["eventos"] == 2
    assert resumen["recolectarTodo"]["muestraChica"] is False
