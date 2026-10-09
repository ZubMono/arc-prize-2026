"""[arc-agi3-kaggle-agent/tests/test_bl21702_reset_congelado] BL.21702 -- el DISPARADOR del RESET
voluntario, que es la parte delicada de todo el BL: cuesta una accion y puede perder progreso real
del nivel.

EL RESET ESTA REFUTADO COMO PALANCA GENERAL y la mitad de este archivo son CONTRAEJEMPLOS. Medido
en los entornos reales (151 acciones por juego), el RESET involuntario ya se dispara solo y no
destraba nada: sp80 6 por partida, su15 4, tn36 2, tu93 2, lf52 2, dc22 1, sb26 1, y los siete
siguen en 0 niveles. Solo tiene sentido donde el tablero esta CONGELADO y no hay game-over que
rescate: lf52 (47 revisitas con gap=1) y dc22 (54). Por eso aca se afirma tanto que dispara en un
tablero congelado como que NO dispara en un ciclo largo, sin cobertura de coordenadas, sin
acciones distintas, sobre progreso reciente o con la palanca apagada.

Ver `arc_agent/estado_congelado.py` para las cinco condiciones y sus umbrales.
"""
from __future__ import annotations

from arc_agent.banderas import RESET_POR_CONGELAMIENTO, Banderas
from arc_agent.estado_congelado import (
    ACCIONES_DISTINTAS_MINIMAS,
    COORDENADAS_DISTINTAS_MINIMAS,
    PASOS_DE_GRACIA_TRAS_PROGRESO,
    PASOS_ENTRE_RESETS_VOLUNTARIOS,
    PASOS_SIN_CAMBIO_PARA_RESET,
    RESETS_VOLUNTARIOS_MAX,
    VENTANA_DE_CONGELAMIENTO,
    DetectorDeCongelamiento,
)
from arc_agent.types import GameAction
from tests.support.entornos_bl21702 import (
    CicloLargo,
    ClickConFirmaSiempreNueva,
    TableroCongelado,
    correr,
)

SIN_PALANCAS = Banderas(())
SOLO_RESET = Banderas((RESET_POR_CONGELAMIENTO,))


def _llenar_ventana(
    detector: DetectorDeCongelamiento,
    *,
    hubo_cambio: bool = False,
    coordenadas: int = COORDENADAS_DISTINTAS_MINIMAS,
    acciones: tuple[str, ...] = ("ACTION6", "ACTION1"),
    desde: int = 0,
) -> int:
    """Alimenta una ventana completa. Devuelve el paso siguiente al ultimo observado."""
    paso = desde
    for i in range(VENTANA_DE_CONGELAMIENTO):
        detector.observar(
            hubo_cambio,
            acciones[i % len(acciones)],
            (i % max(1, coordenadas), 0),
            False,
            paso,
        )
        paso += 1
    return paso


def test_el_reset_no_se_dispara_antes_de_llenar_la_ventana() -> None:
    detector = DetectorDeCongelamiento(SOLO_RESET)
    for paso in range(VENTANA_DE_CONGELAMIENTO - 1):
        detector.observar(False, "ACTION6", (paso, 0), False, paso)
        assert detector.debe_resetear(paso, ["ACTION6"]) is False


def test_el_reset_no_se_dispara_si_el_tablero_SE_MUEVE() -> None:
    """EL CONTRAEJEMPLO IMPORTANTE. En cinco de los siete juegos las revisitas son ciclos LARGOS de
    periodo fijo (tn36 62, tu93 51, sb26 ~73, su15 ~35) con el frame cambiando en cada paso: eso NO
    es congelamiento y el RESET esta refutado ahi por medicion."""
    detector = DetectorDeCongelamiento(SOLO_RESET)
    paso = _llenar_ventana(detector, hubo_cambio=True)
    assert detector.pasos_sin_cambio_en_ventana == 0
    assert detector.debe_resetear(paso, ["ACTION6"]) is False


def test_el_reset_no_se_dispara_con_congelamiento_parcial() -> None:
    detector = DetectorDeCongelamiento(SOLO_RESET)
    paso = 0
    for i in range(VENTANA_DE_CONGELAMIENTO):
        congelado = i < PASOS_SIN_CAMBIO_PARA_RESET - 1
        detector.observar(not congelado, "ACTION6", (i, 0), False, paso)
        paso += 1
    assert detector.pasos_sin_cambio_en_ventana < PASOS_SIN_CAMBIO_PARA_RESET
    assert detector.debe_resetear(paso, ["ACTION6"]) is False


def test_el_reset_no_se_dispara_si_no_se_probaron_acciones_distintas() -> None:
    """"No supe que probar" no es "el juego esta trabado"."""
    detector = DetectorDeCongelamiento(SOLO_RESET)
    paso = _llenar_ventana(detector, acciones=("ACTION1",))
    assert detector.debe_resetear(paso, ["ACTION1", "ACTION2", "ACTION3"]) is False


def test_el_reset_no_se_dispara_sin_cobertura_de_coordenadas_en_un_juego_de_click() -> None:
    """En un juego de click la pregunta es DONDE: reiniciar sin haber barrido nada seria confundir
    falta de exploracion con bloqueo."""
    detector = DetectorDeCongelamiento(SOLO_RESET)
    paso = _llenar_ventana(detector, coordenadas=COORDENADAS_DISTINTAS_MINIMAS - 1)
    assert detector.coordenadas_en_ventana < COORDENADAS_DISTINTAS_MINIMAS
    assert detector.debe_resetear(paso, ["ACTION6", "ACTION1"]) is False


def test_el_reset_no_se_dispara_sobre_progreso_reciente() -> None:
    """La condicion que protege el caso caro: un RESET tras subir de nivel tira justo lo ganado."""
    detector = DetectorDeCongelamiento(SOLO_RESET)
    detector.observar(False, "ACTION6", (0, 0), True, 0)  # subio de nivel en el paso 0
    paso = _llenar_ventana(detector, desde=1)
    assert paso - 0 < PASOS_DE_GRACIA_TRAS_PROGRESO
    assert detector.debe_resetear(paso, ["ACTION6", "ACTION1"]) is False


def test_el_reset_se_dispara_con_toda_la_evidencia_junta() -> None:
    detector = DetectorDeCongelamiento(SOLO_RESET)
    paso = _llenar_ventana(detector)
    assert detector.pasos_sin_cambio_en_ventana >= PASOS_SIN_CAMBIO_PARA_RESET
    assert detector.coordenadas_en_ventana >= COORDENADAS_DISTINTAS_MINIMAS
    assert len(("ACTION6", "ACTION1")) >= ACCIONES_DISTINTAS_MINIMAS
    assert detector.debe_resetear(paso, ["ACTION6", "ACTION1"]) is True


def test_con_la_palanca_apagada_el_reset_no_se_dispara_nunca() -> None:
    detector = DetectorDeCongelamiento(SIN_PALANCAS)
    paso = _llenar_ventana(detector)
    assert detector.activo is False
    assert detector.debe_resetear(paso, ["ACTION6", "ACTION1"]) is False


def test_tras_un_reset_la_ventana_se_vacia_y_hay_que_esperar() -> None:
    """Sin vaciar la ventana el segundo reset saldria en el paso siguiente, con la evidencia del
    tablero ANTERIOR al reinicio."""
    detector = DetectorDeCongelamiento(SOLO_RESET)
    paso = _llenar_ventana(detector)
    assert detector.debe_resetear(paso, ["ACTION6", "ACTION1"]) is True
    detector.registrar_reset(paso)
    assert detector.resets_voluntarios == 1
    assert detector.pasos_sin_cambio_en_ventana == 0
    siguiente = _llenar_ventana(detector, desde=paso + 1)
    # La ventana volvio a llenarse pero la espera todavia no paso.
    assert siguiente - paso < PASOS_ENTRE_RESETS_VOLUNTARIOS
    assert detector.debe_resetear(siguiente, ["ACTION6", "ACTION1"]) is False
    assert detector.debe_resetear(
        paso + PASOS_ENTRE_RESETS_VOLUNTARIOS, ["ACTION6", "ACTION1"]
    ) is True


def test_el_presupuesto_de_resets_voluntarios_es_finito() -> None:
    detector = DetectorDeCongelamiento(SOLO_RESET)
    paso = 0
    for _ in range(RESETS_VOLUNTARIOS_MAX):
        paso = _llenar_ventana(detector, desde=paso)
        paso += PASOS_ENTRE_RESETS_VOLUNTARIOS
        assert detector.debe_resetear(paso, ["ACTION6", "ACTION1"]) is True
        detector.registrar_reset(paso)
    paso = _llenar_ventana(detector, desde=paso + 1)
    paso += PASOS_ENTRE_RESETS_VOLUNTARIOS
    assert detector.resets_voluntarios == RESETS_VOLUNTARIOS_MAX
    assert detector.debe_resetear(paso, ["ACTION6", "ACTION1"]) is False


# --- integracion con la politica --------------------------------------------------------------


def test_la_politica_reinicia_un_tablero_congelado_y_solo_ahi() -> None:
    politica, acciones = correr(TableroCongelado(), SOLO_RESET)
    assert politica.resets_voluntarios >= 1
    assert GameAction.RESET in acciones
    # Y el presupuesto se respeta: nunca se vuelve un tic.
    assert politica.resets_voluntarios <= RESETS_VOLUNTARIOS_MAX


def test_la_politica_no_reinicia_un_ciclo_largo_aunque_revisite() -> None:
    """La medicion refuto el RESET para los cinco juegos de ciclo largo: aca se afirma que el
    disparador NO los alcanza."""
    politica, acciones = correr(CicloLargo(), SOLO_RESET)
    assert politica.resets_voluntarios == 0
    assert GameAction.RESET not in acciones


def test_sin_la_palanca_la_politica_nunca_reinicia_por_su_cuenta() -> None:
    politica, acciones = correr(TableroCongelado(), SIN_PALANCAS)
    assert politica.resets_voluntarios == 0
    assert GameAction.RESET not in acciones


# ============================================================================================


# LINEA BASE -- con todo apagado NINGUNA pieza de BL.21702 se activa
# ============================================================================================


def test_con_todo_apagado_ninguna_pieza_de_bl21702_se_activa() -> None:
    """Es lo que vuelve valida la linea base del gate medida con la MISMA build
    (`--banderas ninguna`): si alguna pieza se colara, el delta del gate no mediria las palancas."""
    politica, _ = correr(ClickConFirmaSiempreNueva(), SIN_PALANCAS, pasos=60)
    assert politica.resets_voluntarios == 0
    assert politica.cortes_de_macro_por_estado_repetido == 0
    assert politica.memoria_de_clicks.memoria_transversal_activa is False
    assert politica.memoria_de_clicks.penalizacion_transversal(0, 0) == 0.0
    assert politica.detector_de_congelamiento.activo is False


def test_con_todo_encendido_las_piezas_si_se_activan() -> None:
    """La contracara: sin esto, el test de arriba pasaria igual con las palancas rotas."""
    politica, _ = correr(ClickConFirmaSiempreNueva(), Banderas.todas(), pasos=60)
    assert politica.memoria_de_clicks.memoria_transversal_activa is True
    assert politica.detector_de_congelamiento.activo is True
