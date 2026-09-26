"""[arc-agi3-kaggle-agent/tests] BL.21794 -- la corrida de CAPTURA que fuerza clicks al FONDO.

QUE PROBLEMA MEDIDO FIJA ESTE ARCHIVO. `resueltoTocandoUnObjeto` murio 0/14 sobre el corpus de
BL.21728 y NO por falta de percepcion: en los 6 eventos de click TODOS los clicks previos de la
ventana cayeron tambien sobre un objeto (ft09 9/9, lp85 9/9, vc33 1/1 y 9/9). El insumo
`clicks_previos_en_objeto == clicks_previos` tomo UN SOLO valor en toda la muestra, o sea VARIANZA
CERO: el click que gano no se distingue de los que no ganaron, y ningun criterio -- por fino que
sea -- puede discriminar sobre una constante. La unica salida es otra MUESTRA.

LOS TRES INVARIANTES QUE NO SE PUEDEN AFLOJAR, y por eso tienen test propio:

  1. LA ATRIBUCION SIGUE SIENDO HONESTA. La politica le acredita el resultado del click a
     `_prev_click`, la celda que ELLA eligio. Redirigir el click sin corregir ese campo mete
     plantillas, anti-plantillas y penalizaciones transversales sobre una celda que nunca se
     clickeo -- evidencia falsa DENTRO del agente, en el mismo BL cuyo objetivo es no producir
     evidencia falsa. Si el campo no existe, la redireccion se APAGA ENTERA.
  2. "FONDO" ES LA MISMA DEFINICION QUE USA EL ANALISIS. Con dos definiciones, la muestra nueva no
     contestaria la pregunta que la motivo.
  3. LA CORRIDA ES REPRODUCIBLE. La semilla de la redireccion sale de `MyAgent.SEMILLA` y no del
     lote (que lleva la hora): una ventana que no se puede volver a producir no es evidencia.

La clasificacion de frames que este mismo BL agrega vive en
`test_bl21794_clasificacion_de_frames.py` -- son dos contratos independientes y el archivo unico
cruzaba el limite de tamano.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from arc_agent.world_model.grid import detect_background_color  # noqa: E402
from caracterizacion_de_niveles import componente_bajo_el_click  # noqa: E402
from cobertura_de_fondo import (  # noqa: E402
    RedireccionAlFondo,
    celdas_de_fondo,
    elegir_celda_de_fondo,
)
from maniobra_previa import VistaDeLaManiobra  # noqa: E402

LADO = 8


def _tablero(pintadas: dict[tuple[int, int], int]) -> list[list[int]]:
    """Tablero de fondo 0 con las celdas `(x, y)` pintadas del color indicado."""
    grilla = [[0 for _ in range(LADO)] for _ in range(LADO)]
    for (x, y), color in pintadas.items():
        grilla[y][x] = color
    return grilla


# --- el fondo es EL MISMO que usa el analisis --------------------------------------------------


def test_el_fondo_de_la_captura_es_el_mismo_que_el_del_analisis():
    """La captura y el informe tienen que llamar FONDO a lo mismo.

    `componente_bajo_el_click` decide "el click cayo sobre un objeto" con
    `grilla[y][x] != detect_background_color(grilla)`. Si la corrida de cobertura usara otra
    definicion de fondo, la muestra nueva no contestaria la pregunta que la motivo: podria estar
    llena de clicks que el analisis sigue contando como "sobre un objeto"."""
    grilla = _tablero({(2, 2): 5, (3, 2): 5})
    fondo = detect_background_color(grilla)
    for x, y in celdas_de_fondo(grilla):
        assert grilla[y][x] == fondo
        assert componente_bajo_el_click(grilla, x, y) is None
    assert componente_bajo_el_click(grilla, 2, 2) is not None
    assert (2, 2) not in celdas_de_fondo(grilla)


def test_sin_celdas_de_fondo_no_se_inventa_una():
    """Una grilla de un solo color no tiene "objeto" ni "fondo" que elegir de a dos, y una grilla
    vacia no tiene nada. En los dos casos la eleccion devuelve algo consistente en vez de romper:
    la captura NUNCA puede tumbar la partida (mismo invariante que el sink de replay)."""
    assert celdas_de_fondo([]) == []
    assert elegir_celda_de_fondo([], lambda: 0.5) is None
    llena = [[3 for _ in range(LADO)] for _ in range(LADO)]
    assert len(celdas_de_fondo(llena)) == LADO * LADO


def test_la_celda_elegida_esta_dentro_de_la_grilla_con_el_sorteo_en_el_borde():
    """`rng()` devuelve [0, 1): un 0,999... no puede indexar fuera de la lista. El clamp existe
    porque un IndexError aca tumbaria la partida entera por una celda."""
    grilla = _tablero({(0, 0): 4})
    for sorteo in (0.0, 0.5, 0.999999999):
        x, y = elegir_celda_de_fondo(grilla, lambda: sorteo)
        assert 0 <= x < LADO and 0 <= y < LADO
        assert grilla[y][x] == detect_background_color(grilla)


# --- la atribucion no se rompe -----------------------------------------------------------------


class _AccionFalsa:
    """Lo minimo del `GameAction` oficial que usa la redireccion: `is_complex`, `set_data`,
    `action_data` y `reasoning`."""

    def __init__(self, x: int, y: int, compleja: bool = True) -> None:
        self.action_data = type("Datos", (), {"x": x, "y": y})()
        self._compleja = compleja
        self.reasoning: object = {"x": x, "y": y, "razonamiento": "del ranker"}

    def is_complex(self) -> bool:
        return self._compleja

    def set_data(self, datos: dict) -> None:
        self.action_data = type("Datos", (), dict(datos))()


class _PoliticaFalsa:
    def __init__(self) -> None:
        self._prev_click: tuple[int, int] | None = None


class _AgenteFalso:
    def __init__(self, con_politica: bool = True, politica_sin_campo: bool = False) -> None:
        if con_politica:
            self._politica = object() if politica_sin_campo else _PoliticaFalsa()
        self.emitidas: list[_AccionFalsa] = []

    def choose_action(self, frames, latest_frame):  # noqa: ANN001
        accion = _AccionFalsa(2, 2)
        self.emitidas.append(accion)
        return accion


class _FrameFalso:
    def __init__(self, grilla: list[list[int]]) -> None:
        self.frame = [grilla]


def test_redirigir_corrige_la_celda_a_la_que_se_le_atribuye_el_resultado():
    """EL INVARIANTE 1. Tras redirigir, `_prev_click` tiene que ser la celda REALMENTE clickeada.

    Sin esto, `policy._atribuir_click` -> `ClickMemory.registrar_resultado` aprende sobre la celda
    del ranker: marca como probada una coordenada que nadie toco, le suma o le resta plantilla
    segun un cambio que produjo OTRA celda, y contamina la memoria transversal. El corpus saldria
    bien y el agente saldria roto."""
    grilla = _tablero({(2, 2): 5, (3, 2): 5})
    agente = _AgenteFalso()
    redireccion = RedireccionAlFondo(1.0, "semilla-de-prueba")
    assert redireccion.enganchar(agente) is True

    accion = agente.choose_action([], _FrameFalso(grilla))

    x, y = accion.action_data.x, accion.action_data.y
    assert grilla[y][x] == detect_background_color(grilla), "el click no quedo en el fondo"
    assert agente._politica._prev_click == (x, y)
    assert redireccion.resumen()["clicksRedirigidos"] == 1
    assert accion.reasoning["redirigidoAlFondo"] is True


def test_sin_prev_click_la_redireccion_se_apaga_entera():
    """EL INVARIANTE 1, del otro lado. Una politica que no expone `_prev_click` no permite corregir
    la atribucion, y entonces NO se redirige nada: es preferible una corrida de captura que no
    aporte cobertura de fondo a un corpus con evidencia falsa adentro del agente. Fail-closed."""
    agente = _AgenteFalso(politica_sin_campo=True)
    redireccion = RedireccionAlFondo(1.0, "s")
    assert redireccion.enganchar(agente) is False
    assert redireccion.resumen()["apagadaPorAtribucion"] is True

    agente_sin_politica = _AgenteFalso(con_politica=False)
    assert RedireccionAlFondo(1.0, "s").enganchar(agente_sin_politica) is False


def test_fraccion_cero_no_engancha_nada():
    """Sin la bandera la partida corre EXACTAMENTE como la entregada: ni un wrapper de mas."""
    agente = _AgenteFalso()
    assert RedireccionAlFondo(0.0, "s").enganchar(agente) is False
    # El enganche sustituye el metodo LIGADO en la instancia; si no engancho, la instancia no tiene
    # `choose_action` propio y la llamada sigue resolviendo por la clase.
    assert "choose_action" not in agente.__dict__


def test_una_accion_que_no_es_click_pasa_intacta_y_no_consume_el_sorteo():
    """La fraccion es "de los CLICKS", no "de las acciones". Si el sorteo avanzara con cada accion,
    en un juego de flechas con un click ocasional la fraccion efectiva no se pareceria a la pedida
    y la muestra quedaria descripta con un numero que no es el que rige."""
    grilla = _tablero({(2, 2): 5})
    redireccion = RedireccionAlFondo(0.5, "s")
    politica = _PoliticaFalsa()
    flecha = _AccionFalsa(0, 0, compleja=False)
    devuelta = redireccion._quizas_redirigir(flecha, _FrameFalso(grilla), politica)
    assert devuelta is flecha
    assert redireccion.resumen()["clicksEmitidos"] == 0
    assert politica._prev_click is None


def test_la_linea_base_de_clicks_deja_de_estar_saturada_cuando_hay_clicks_al_fondo():
    """LA RAZON DE SER DEL BL, escrita como contrato sobre el predicado que mato al candidato.

    `linea_base_de_click_saturada` es True cuando TODOS los clicks previos cayeron sobre un objeto.
    Con la muestra vieja (9/9) es True y `resueltoTocandoUnObjeto` no puede dar True nunca. Basta
    UN click al fondo en la ventana para que el rasgo recupere varianza."""
    saturada = VistaDeLaManiobra(frames_previos=9, clicks_previos=9, clicks_previos_en_objeto=9)
    assert saturada.linea_base_de_click_saturada is True
    con_fondo = VistaDeLaManiobra(frames_previos=9, clicks_previos=9, clicks_previos_en_objeto=8)
    assert con_fondo.linea_base_de_click_saturada is False


def test_la_misma_semilla_redirige_los_mismos_clicks():
    """REPRODUCIBILIDAD. Una corrida de captura tiene que poder volver a producirse: una ventana
    irreproducible no es evidencia. Por eso la semilla de la redireccion sale de `MyAgent.SEMILLA`
    y NO del lote (que lleva la hora): con el lote adentro, la misma `--semilla` sorteaba otros
    clicks y daba otra partida."""
    grilla = _tablero({(2, 2): 5, (3, 3): 5})
    frame = _FrameFalso(grilla)

    def celdas_con(semilla: str) -> list[tuple[int, int]]:
        redireccion = RedireccionAlFondo(1.0, semilla)
        politica = _PoliticaFalsa()
        elegidas = []
        for _ in range(8):
            accion = _AccionFalsa(2, 2)
            redireccion._quizas_redirigir(accion, frame, politica)
            elegidas.append((accion.action_data.x, accion.action_data.y))
        return elegidas

    assert celdas_con("vc33:bl21794-f1") == celdas_con("vc33:bl21794-f1")
    assert celdas_con("vc33:bl21794-f1") != celdas_con("vc33:bl21794-f2")


@pytest.mark.parametrize("fraccion", [-1.0, 0.0, 0.5, 1.0, 2.0])
def test_la_fraccion_se_clampa_al_rango_valido(fraccion: float):
    """Una fraccion fuera de [0, 1] es un error de invocacion, no una licencia para redirigir mas
    veces que clicks hay. Se clampa y se REPORTA la efectiva, que es la que describe la muestra."""
    redireccion = RedireccionAlFondo(fraccion, "s")
    assert 0.0 <= redireccion.fraccion <= 1.0
