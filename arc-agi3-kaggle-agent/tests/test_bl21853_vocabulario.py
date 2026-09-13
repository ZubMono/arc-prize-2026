"""[arc-agi3-kaggle-agent/tests/test_bl21853_vocabulario] BL.21853 -- el vocabulario de mecanicas
paso de SIETE simbolos a DIEZ y el detector aprendio a ver al objeto MULTICELDA que se va lejos.
Este archivo ata las dos mitades a la MEDICION que las decidio.

QUE ATA, Y POR QUE CADA ATADURA:
  1. `CONTEO_VISIBLE_MEDIDO` dice salir del corpus: se compara ELEMENTO POR ELEMENTO contra
     `mediciones/BL21853_vocabulario_de_mecanicas.json` (RFM-01: una lista que dice derivarse de
     una fuente y no se compara con ella es como entraron 6 ids inexistentes en BL.21783). La
     comparacion NO va envuelta en un `if el_archivo_existe` (RFM-02: ese `if` es exactamente lo
     que dejo el unico guard de BL.21783 en no-op); el archivo esta versionado y si falta, el test
     FALLA.
  2. El detector de objeto entero se ejercita con una grilla donde el objeto se va MAS LEJOS que su
     propio ancho -- el caso que el analisis por cluster no puede ver -- y ademas se verifica que
     NO invente traslaciones donde el tablero esta embaldosado con la misma forma (el falso
     positivo que el criterio flojo produce 418 veces sobre el corpus).
  3. Se verifica que la via nueva sea el ULTIMO respaldo: sobre un caso que el analisis por cluster
     ya resuelve, la respuesta tiene que ser IDENTICA a la de antes del BL.

LO QUE ESTE TEST NO PRUEBA: no prueba que el vocabulario mas grande compre score. Eso no esta
medido en ningun lado (ver el informe). Lo que si esta medido y vive en el JSON es el efecto sobre
el posterior de mapeo, que es un proxy, no el score.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arc_agent.direction_beliefs import _evento_sin_traslacion  # noqa: E402
from arc_agent.mechanics_posterior import (  # noqa: E402
    CONTEO_VISIBLE_MEDIDO,
    EVENTO_APARICION,
    EVENTO_DESAPARICION,
    EVENTO_DESCONOCIDA,
    EVENTO_OTRA,
    EVENTO_RECOLOREO,
    EVENTOS_NOMBRADOS,
    MECANICA_APARICION,
    MECANICA_DESAPARICION,
    MECANICA_DESCONOCIDA,
    MECANICA_OTRA,
    MECANICA_RECOLOREO,
    MECANICAS,
    MECANICAS_NOMBRADAS,
    REPARTO_VISIBLE,
    condicional_de_mecanicas,
    ARQUETIPO_MUEVE,
)
from arc_agent.world_model.object_geometry import (  # noqa: E402
    MAX_CELDAS_DE_OBJETO_ENTERO,
    objetos_que_tocan,
    traslacion_de_objeto_entero,
)
from arc_agent.world_model.object_mechanics import detectar_mecanica  # noqa: E402

INFORME = (
    Path(__file__).resolve().parents[1]
    / "mediciones"
    / "BL21853_vocabulario_de_mecanicas.json"
)


def _informe() -> dict:
    # SIN `if INFORME.exists()`: si el archivo no esta, esto revienta y el test se pone rojo, que
    # es lo correcto. Un guard que se autoexime por ausencia de su fuente no compara nada (RFM-02).
    return json.loads(INFORME.read_text(encoding="utf-8"))


# ── 1. el vocabulario y su reparto salen de la medicion ───────────────────────────────────────


def test_el_vocabulario_tiene_los_diez_simbolos_en_orden_fijo() -> None:
    assert MECANICAS == (
        "arriba",
        "abajo",
        "izquierda",
        "derecha",
        "inerte",
        MECANICA_RECOLOREO,
        MECANICA_APARICION,
        MECANICA_DESAPARICION,
        MECANICA_OTRA,
        MECANICA_DESCONOCIDA,
    )
    assert MECANICAS_NOMBRADAS == (
        MECANICA_RECOLOREO,
        MECANICA_APARICION,
        MECANICA_DESAPARICION,
    )
    # El evento y la mecanica comparten string: un solo alfabeto, no dos que puedan divergir.
    assert EVENTOS_NOMBRADOS == MECANICAS_NOMBRADAS


def test_el_conteo_visible_es_identico_al_del_informe_no_solo_del_mismo_tamano() -> None:
    """RFM-03: comparar el TOTAL no alcanza -- cuatro numeros inventados cierran la misma suma.
    Se comparan las CLAVES y cada VALOR contra la medicion versionada."""
    medido = _informe()["conteoVisibleMedido"]
    assert set(CONTEO_VISIBLE_MEDIDO) == set(medido)
    for simbolo, n in medido.items():
        assert CONTEO_VISIBLE_MEDIDO[simbolo] == n, simbolo


def test_el_reparto_visible_es_laplace_sobre_ese_conteo_y_suma_uno() -> None:
    total = sum(CONTEO_VISIBLE_MEDIDO.values()) + len(CONTEO_VISIBLE_MEDIDO)
    for simbolo, n in CONTEO_VISIBLE_MEDIDO.items():
        assert REPARTO_VISIBLE[simbolo] == (n + 1) / total
    assert abs(sum(REPARTO_VISIBLE.values()) - 1.0) < 1e-12
    # Ninguno puede quedar en cero: con prior cero un simbolo con poblacion real no puede
    # concentrar nunca, que es el defecto medido (134 botones direccionales contra 140).
    assert all(v > 0.0 for v in REPARTO_VISIBLE.values())


def test_la_condicional_reparte_la_masa_visible_sin_cambiar_el_total() -> None:
    """El simbolo nuevo no le roba masa a las direcciones: la canonica de ACTION1 conserva el
    numero exacto que pinnea el test de paridad de BL.21593."""
    cond = condicional_de_mecanicas(ARQUETIPO_MUEVE, "ACTION1")
    assert cond["arriba"] == 0.8421875
    assert abs(sum(cond.values()) - 1.0) < 1e-12
    visible = sum(cond[m] for m in REPARTO_VISIBLE)
    for simbolo in REPARTO_VISIBLE:
        assert abs(cond[simbolo] - visible * REPARTO_VISIBLE[simbolo]) < 1e-12


# ── 2. la percepcion emite los simbolos nuevos ────────────────────────────────────────────────


class _ClusterFalso:
    def __init__(self, tipo: str) -> None:
        self.tipo = tipo


class _MecanicaFalsa:
    def __init__(self, tipo: str, clusters: list[str], celdas: int = 4) -> None:
        self.tipo = tipo
        self.celdas_cambiadas = celdas
        self.clusters = [_ClusterFalso(t) for t in clusters]


def test_cada_mecanica_nombrada_emite_su_propio_evento_y_no_el_cajon_otra() -> None:
    assert _evento_sin_traslacion(_MecanicaFalsa("recoloreo", ["recoloreo"]), None).tipo == (
        EVENTO_RECOLOREO
    )
    assert _evento_sin_traslacion(_MecanicaFalsa("aparicion", ["aparicion"]), None).tipo == (
        EVENTO_APARICION
    )
    assert _evento_sin_traslacion(
        _MecanicaFalsa("desaparicion", ["desaparicion"]), None
    ).tipo == EVENTO_DESAPARICION


def test_la_mezcla_de_nombradas_es_otra_y_el_silencio_sigue_siendo_desconocida() -> None:
    """La distincion que este BL agrega: "mire y nombre cada parte, el conjunto es una mezcla" no
    es lo mismo que "no supe que paso". Con un solo cluster sin nombrar, vuelve a ser desconocida."""
    mezcla = _MecanicaFalsa("desconocida", ["aparicion", "desaparicion", "recoloreo"])
    assert _evento_sin_traslacion(mezcla, None).tipo == EVENTO_OTRA
    con_silencio = _MecanicaFalsa("desconocida", ["aparicion", "desconocida"])
    assert _evento_sin_traslacion(con_silencio, None).tipo == EVENTO_DESCONOCIDA
    sin_clusters = _MecanicaFalsa("desconocida", [])
    assert _evento_sin_traslacion(sin_clusters, None).tipo == EVENTO_DESCONOCIDA


# ── 3. el detector de objeto ENTERO ───────────────────────────────────────────────────────────


def _grilla(alto: int, ancho: int, fondo: int = 0) -> list[list[int]]:
    return [[fondo] * ancho for _ in range(alto)]


def _pintar(grid: list[list[int]], y0: int, x0: int, forma: list[str], color: int) -> None:
    for dy, fila in enumerate(forma):
        for dx, ch in enumerate(fila):
            if ch != ".":
                grid[y0 + dy][x0 + dx] = color


FORMA = ["####", "#..#", "####"]


def test_ve_al_objeto_que_se_va_MAS_LEJOS_que_su_propio_ancho() -> None:
    """El caso que el analisis por cluster NO puede ver: origen y destino quedan disjuntos, son dos
    clusters, y ninguno se explica solo. Es la clase de las 146 transiciones que este BL recupera."""
    pre = _grilla(20, 20)
    post = _grilla(20, 20)
    _pintar(pre, 2, 2, FORMA, 3)
    _pintar(post, 2, 12, FORMA, 3)
    mecanica = detectar_mecanica(pre, post)
    assert mecanica.tipo == "traslacion"
    t = mecanica.traslacion_principal
    assert t is not None
    assert (t.dy, t.dx) == (0, 10)


def test_no_inventa_traslaciones_en_un_tablero_embaldosado() -> None:
    """El falso positivo del criterio flojo: con la misma forma repetida por todo el tablero
    "alguna coincide desplazada" siempre es cierto. Aca cambia el COLOR de una baldosa, que no es
    una traslacion, y el detector no puede llamarla traslacion."""
    pre = _grilla(20, 20)
    for y in (2, 8, 14):
        for x in (2, 8, 14):
            _pintar(pre, y, x, FORMA, 3)
    post = [fila[:] for fila in pre]
    for dy, fila in enumerate(FORMA):
        for dx, ch in enumerate(fila):
            if ch != ".":
                post[8 + dy][8 + dx] = 5
    assert detectar_mecanica(pre, post).tipo != "traslacion"


def test_la_via_nueva_es_el_ULTIMO_respaldo_y_no_cambia_lo_que_ya_se_explicaba() -> None:
    """Un cursor 2x2 que avanza UNA celda lo resuelve el analisis por cluster desde BL.21561. La
    via de objeto entero no puede alterarlo: si lo alterara, el BL habria movido transiciones que
    ya estaban bien en vez de solo sacar frames de `desconocida`."""
    pre = _grilla(12, 12)
    post = _grilla(12, 12)
    _pintar(pre, 4, 4, ["##", "##"], 7)
    _pintar(post, 4, 5, ["##", "##"], 7)
    mecanica = detectar_mecanica(pre, post)
    assert mecanica.tipo == "traslacion"
    t = mecanica.traslacion_principal
    assert t is not None
    assert (t.dy, t.dx) == (0, 1)
    # La caja del objeto la despeja el analisis por cluster: 2x2, no la union de los dos clusters.
    assert (t.alto, t.ancho) == (2, 2)


def test_el_objeto_es_multicolor_y_de_una_sola_pieza() -> None:
    """Color-AGNOSTICO puertas adentro: un avatar de dos colores es UN objeto. Si `objetos_que_tocan`
    partiera por color, la forma con color de pre y post no matchearia y las 146 no se recuperarian."""
    grid = _grilla(10, 10)
    _pintar(grid, 3, 3, ["##"], 4)
    grid[3][5] = 6
    objetos = objetos_que_tocan(grid, 0, [(3, 3), (3, 4), (3, 5)], MAX_CELDAS_DE_OBJETO_ENTERO)
    assert len(objetos) == 1
    assert sorted(objetos[0]) == [(3, 3), (3, 4), (3, 5)]


def test_descarta_el_objeto_mas_grande_que_el_tope() -> None:
    """Sin este tope el "objeto" seria el tablero entero y la hipotesis no describiria nada."""
    grid = _grilla(40, 40)
    for y in range(40):
        for x in range(40):
            grid[y][x] = 3
    assert objetos_que_tocan(grid, 0, [(0, 0)], MAX_CELDAS_DE_OBJETO_ENTERO) == []


def test_la_componente_que_supera_el_tope_se_descarta_ENTERA_con_varias_semillas() -> None:
    """El agujero que la revision de BL.21853 midio: al pasarse el tope el recorrido CORTABA, y el
    resto de esa misma componente quedaba sin marcar. Una semilla posterior lo volvia a floodear y
    si el remanente entraba en el tope salia como "objeto" -- un PEDAZO del tablero presentado como
    objeto, y una salida que dependia de QUE celdas cambiaron y no solo de la grilla.

    Corredor 4-conexo de 304 celdas (mas que el tope de 256) en una grilla 64x64. Con UNA semilla
    en cualquier extremo la respuesta correcta es []; con las DOS tiene que seguir siendo []."""
    grid = _grilla(64, 64)
    camino: list[tuple[int, int]] = []
    for i in range(300):
        fila, col = divmod(i, 60)
        camino.append((fila * 2, col if fila % 2 == 0 else 59 - col))
    for fila in range(4):  # puentes que unen las filas: una sola componente 4-conexa
        camino.append((fila * 2 + 1, 59 if fila % 2 == 0 else 0))
    for y, x in camino:
        grid[y][x] = 3
    assert len(camino) > MAX_CELDAS_DE_OBJETO_ENTERO
    assert objetos_que_tocan(grid, 0, [camino[0]], MAX_CELDAS_DE_OBJETO_ENTERO) == []
    assert objetos_que_tocan(grid, 0, [camino[290]], MAX_CELDAS_DE_OBJETO_ENTERO) == []
    assert objetos_que_tocan(grid, 0, [camino[0], camino[290]], MAX_CELDAS_DE_OBJETO_ENTERO) == []


def test_una_componente_grande_no_tapa_a_un_objeto_chico_vecino() -> None:
    """El contrapeso del test de arriba: descartar la componente grande ENTERA no puede hacer que
    se pierda un objeto legitimo que toca otra semilla."""
    grid = _grilla(64, 64)
    for y in range(30):
        for x in range(30):
            grid[y][x] = 3  # 900 celdas: muy por encima del tope
    _pintar(grid, 40, 40, ["##", "##"], 7)
    objetos = objetos_que_tocan(grid, 0, [(0, 0), (40, 40)], MAX_CELDAS_DE_OBJETO_ENTERO)
    assert [sorted(o) for o in objetos] == [[(40, 40), (40, 41), (41, 40), (41, 41)]]


def test_devuelve_none_cuando_el_cambio_no_es_un_objeto_que_se_movio() -> None:
    pre = _grilla(12, 12)
    post = _grilla(12, 12)
    _pintar(pre, 3, 3, FORMA, 3)
    post = [fila[:] for fila in pre]
    post[3][3] = 5  # un recoloreo de una celda: no hay traslacion que explique nada
    cambios = [(3, 3)]
    assert traslacion_de_objeto_entero(pre, post, cambios, 0) is None
