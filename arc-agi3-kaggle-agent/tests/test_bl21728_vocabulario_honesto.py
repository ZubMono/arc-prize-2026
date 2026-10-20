"""[arc-agi3-kaggle-agent/tests] BL.21728 -- los cuatro contratos que impiden que el vocabulario de
objetivos vuelva a ser un artefacto de medicion.

Cada bloque de este archivo corresponde a UN defecto medido sobre el commit 6929a3df24, y cada test
esta escrito para PONERSE ROJO si alguien revierte el arreglo -- no para documentar que el arreglo
existe:

1. EL FRAME DEL EVENTO FUERA DE LAS SERIES. El caso de prueba es la forma EXACTA que produjo el
   artefacto (ocupacion plana N frames + caida unica en el evento). Y ademas, estructuralmente: un
   criterio de objetivo que lea el campo con el evento adentro revienta con AttributeError.
2. LA MUESTRA ES LA PERSISTIDA. Sin manifiesto, con el JSONL alterado o con el manifiesto
   declarando otra cosa, el informe no corre.
3. `muestraChica` GATEA sobre transiciones distintas y cambia veredictos.
4. FRAMES REALES: informativo != inerte != animacion en loop, y el texto los dice.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from caracterizacion_de_niveles import medir_evento  # noqa: E402
from caracterizar_completados import (  # noqa: E402
    CANDIDATOS,
    MINIMO_DE_TRANSICIONES,
    cargar_mediciones,
    imprimir_informe,
    resumen_de_candidatos,
    se_sostiene,
    sujeto_de,
    vocabulario_rederivado,
)
from corpus_persistido import (  # noqa: E402
    ARCHIVO_MANIFIESTO,
    ARCHIVO_VENTANAS,
    MAX_ANTIGUEDAD_DEL_EXPORT,
    CorpusInvalido,
    leer_corpus,
)
from maniobra_previa import (  # noqa: E402
    ANCHO_NOMINAL_DE_VENTANA,
    MINIMO_DE_CLICKS_PREVIOS,
    MINIMO_DE_PASOS_QUE_MUEVEN,
    PasoPrevio,
    VistaDeLaManiobra,
    es_animacion_en_loop,
    tendencia_creciente,
)
from medicion_de_evento import MedicionDeEvento  # noqa: E402

LADO = 12


def _tablero(coloreadas: dict[tuple[int, int], int], lado: int = LADO) -> list[list[int]]:
    grilla = [[0 for _ in range(lado)] for _ in range(lado)]
    for (y, x), color in coloreadas.items():
        grilla[y][x] = color
    return grilla


def _ventana(
    grillas: list[list[list[int]]],
    paso_del_evento: int,
    juego: str = "j1",
    nivel_nuevo: int = 1,
    clicks: dict[int, tuple[int, int]] | None = None,
) -> dict:
    clicks = clicks or {}
    frames = []
    for i, grilla in enumerate(grillas):
        click = clicks.get(i)
        frames.append(
            {
                "paso": i,
                "accion": "ACTION6" if click else "ACTION1",
                "x": click[0] if click else None,
                "y": click[1] if click else None,
                "accionesDisponibles": [1, 2, 3, 4, 6],
                "grilla": grilla,
                "nivelesCompletados": nivel_nuevo if i >= paso_del_evento else nivel_nuevo - 1,
                "nivelesParaGanar": 3,
                "estado": "NOT_FINISHED",
                "reinicioCompleto": False,
            }
        )
    return {
        "juego": juego,
        "corrida": f"harness-local:{juego}:t{nivel_nuevo}",
        "modelo": "harness-local",
        "pasoDelEvento": paso_del_evento,
        "nivelPrevio": nivel_nuevo - 1,
        "nivelNuevo": nivel_nuevo,
        "framesAntes": paso_del_evento,
        "framesDespues": len(grillas) - paso_del_evento - 1,
        "frames": frames,
    }


def _ventana_ft09(juego: str = "ft09", nivel_nuevo: int = 1) -> dict:
    """LA FORMA DEL ARTEFACTO, reproducida: la ocupacion queda CLAVADA los frames previos y cae de
    golpe SOLO en el frame del evento (ft09 medido: 0,4727 x10 -> 0,1553). Los pasos previos si
    cambian celdas -- el tablero se anima -- pero no mueven la ocupacion ni un punto."""
    coleccionables = {(2, 2): 7, (4, 4): 7, (6, 6): 7, (8, 8): 7}
    grillas = []
    for paso in range(6):
        # Un adorno que va y viene: cambia exactamente 2 celdas por paso y deja la ocupacion y los
        # colores presentes EXACTAMENTE iguales. Es la firma de la animacion en loop de ft09.
        adorno = {(0, 0 if paso % 2 == 0 else 1): 3}
        grillas.append(_tablero({**coleccionables, **adorno}))
    grillas.append(_tablero({(0, 0): 3}))  # el evento: el tablero se vacia de golpe
    return _ventana(grillas, paso_del_evento=6, juego=juego, nivel_nuevo=nivel_nuevo)


# --- 1. El frame del evento queda FUERA de las series ------------------------------------------


def test_la_serie_de_la_maniobra_no_contiene_el_frame_del_evento():
    medicion = medir_evento(_ventana_ft09())
    assert medicion is not None
    # La serie de la maniobra es la de la medicion completa MENOS el ultimo punto, siempre.
    assert list(medicion.maniobra.ocupacion) == medicion.fraccion_no_fondo[:-1]
    assert medicion.maniobra.frames_previos == medicion.paso_del_evento
    assert len(medicion.maniobra.pasos) == medicion.paso_del_evento - 1


def test_la_ocupacion_plana_con_caida_en_el_evento_no_es_vaciado_de_la_maniobra():
    medicion = medir_evento(_ventana_ft09())
    assert medicion is not None
    # CON el frame del evento la serie "baja monotonamente": ese es el artefacto que reporto
    # BL.21695 en 6 eventos.
    assert medicion.vaciado_monotono is True
    # SIN ese frame, la ocupacion nunca se movio.
    assert medicion.maniobra.vaciado_monotono_en_la_maniobra is False
    assert medicion.maniobra.pasos_que_bajan_la_ocupacion == 0
    assert se_sostiene("recolectarTodo", medicion) is False


def test_los_colores_agotados_de_la_maniobra_no_incluyen_los_que_borro_el_evento():
    medicion = medir_evento(_ventana_ft09())
    assert medicion is not None
    # El evento reescribio el tablero, asi que "agoto" el color 7 -- ese es el artefacto.
    assert 7 in medicion.colores_agotados
    # La maniobra no agoto nada: los cuatro coleccionables siguen ahi hasta el ultimo frame previo.
    assert medicion.maniobra.colores_agotados_en_la_maniobra == ()


@pytest.mark.parametrize(
    "nombre", [n for n, c in CANDIDATOS.items() if c.tipo == "objetivo"]
)
def test_un_criterio_de_objetivo_no_puede_leer_la_medicion_con_el_evento_adentro(nombre):
    """CONTRATO ESTRUCTURAL. Los criterios de objetivo reciben `VistaDeLaManiobra`, cuyos campos se
    llaman `..._en_la_maniobra` y NO existen en `MedicionDeEvento`. Si alguien reescribe un criterio
    contra `m.vaciado_monotono` (el que incluye el frame del evento), pasarle la vista revienta; y
    si ademas cambia el despacho para pasarle la medicion entera, revienta este test."""
    medicion = medir_evento(_ventana_ft09())
    assert medicion is not None
    assert isinstance(sujeto_de(nombre, medicion), VistaDeLaManiobra)
    with pytest.raises(AttributeError):
        CANDIDATOS[nombre].prueba(medicion)


def test_una_tendencia_necesita_mas_de_un_paso_que_se_mueva():
    """El caso g50t: un salto de +0,58pp en el primer paso y ocho pasos planos. Es monotona no
    decreciente, pero un escalon no es una tendencia."""
    escalon = [0.2659] + [0.2717] * 8
    assert len(escalon) >= 3
    assert tendencia_creciente(escalon) is False
    dos_pasos = [0.2659, 0.2717, 0.2717, 0.2800]
    assert tendencia_creciente(dos_pasos) is True
    assert MINIMO_DE_PASOS_QUE_MUEVEN == 2


def test_un_click_ganador_indistinguible_de_los_previos_no_sostiene_un_objetivo():
    """Un rasgo con varianza cero no explica el desenlace: si todos los clicks previos tambien
    cayeron sobre un objeto, el que gano no se distingue en nada de los que no ganaron.

    NUMEROS CORREGIDOS DEL CORPUS (este docstring publicaba "los 6 eventos de click", falso en dos
    sentidos): hay 10 eventos con click; en 6 el click cayo sobre una componente y de esos 5 tienen
    la linea base saturada con 9/9; los otros 4 son de lp85 nivel 1 y NO estan saturados (0/9, 5/9,
    5/9, 3/9) -- quedan fuera por otra razon, el click gano sobre el FONDO."""
    objeto = {(2, 2): 7, (2, 3): 7}
    grillas = [_tablero(objeto) for _ in range(4)] + [_tablero({(9, 9): 5})]
    # Cada paso previo clickea SOBRE el objeto, igual que el paso ganador.
    clicks = {1: (2, 2), 2: (3, 2), 3: (2, 2), 4: (3, 2)}
    medicion = medir_evento(_ventana(grillas, paso_del_evento=4, clicks=clicks))
    assert medicion is not None
    assert medicion.color_clickeado == 7
    assert medicion.maniobra.linea_base_de_click_saturada is True
    assert se_sostiene("resueltoTocandoUnObjeto", medicion) is False

    # Con un solo click previo al FONDO, el rasgo recupera varianza y el criterio se sostiene.
    clicks_con_fondo = {1: (11, 11), 2: (3, 2), 3: (2, 2), 4: (3, 2)}
    otra = medir_evento(_ventana(grillas, paso_del_evento=4, clicks=clicks_con_fondo))
    assert otra is not None
    assert otra.maniobra.linea_base_de_click_saturada is False
    assert se_sostiene("resueltoTocandoUnObjeto", otra) is True


def test_un_solo_click_previo_no_alcanza_para_declarar_varianza_cero():
    """CORRECCION DE BL.21728 (defecto medido). El predicado era `clicks_previos > 0 and ...`, o sea
    que con UNA sola observacion daba SATURADA siempre -- y le tocaba justo a vc33 nivel 1, la
    ventana que el propio informe marca TRUNCADA (framesAntes=2, linea base 1/1). El rigor era
    asimetrico: el modulo exige 2 pasos para una tendencia y 3 puntos para una monotonia, pero el
    unico criterio que MATA candidatos se conformaba con n=1.

    Este test se pone rojo si alguien vuelve a `> 0`: con un click previo la linea base deja de
    estar saturada y el candidato vuelve a poder sostenerse."""
    objeto = {(2, 2): 7, (2, 3): 7}
    grillas = [_tablero(objeto) for _ in range(2)] + [_tablero({(9, 9): 5})]
    # UN solo click previo, y sobre el objeto: n=1, sin varianza que medir.
    medicion = medir_evento(_ventana(grillas, paso_del_evento=2, clicks={1: (2, 2), 2: (3, 2)}))
    assert medicion is not None
    assert medicion.maniobra.clicks_previos == 1
    assert medicion.maniobra.clicks_previos_en_objeto == 1
    assert medicion.maniobra.linea_base_de_click_saturada is False
    assert se_sostiene("resueltoTocandoUnObjeto", medicion) is True

    # Con DOS clicks previos, los dos sobre objeto, la saturacion si es una medicion.
    grillas_largas = [_tablero(objeto) for _ in range(3)] + [_tablero({(9, 9): 5})]
    otra = medir_evento(
        _ventana(grillas_largas, paso_del_evento=3, clicks={1: (2, 2), 2: (3, 2), 3: (2, 2)})
    )
    assert otra is not None
    assert otra.maniobra.clicks_previos == MINIMO_DE_CLICKS_PREVIOS
    assert otra.maniobra.linea_base_de_click_saturada is True
    assert se_sostiene("resueltoTocandoUnObjeto", otra) is False


def test_la_linea_base_no_se_mide_dos_veces():
    """FUENTE UNICA (correccion de BL.21728): `clicks_previos` vivia a la vez en `MedicionDeEvento`
    y en `VistaDeLaManiobra`, llenados de los mismos locales, y salia duplicado en el JSON. Ahora la
    medicion DELEGA en la vista; si alguien reintroduce el campo propio, los dos valores pueden
    divergir y este test lo ve."""
    objeto = {(2, 2): 7, (2, 3): 7}
    grillas = [_tablero(objeto) for _ in range(3)] + [_tablero({(9, 9): 5})]
    medicion = medir_evento(
        _ventana(grillas, paso_del_evento=3, clicks={1: (2, 2), 2: (11, 11), 3: (2, 2)})
    )
    assert medicion is not None
    assert medicion.clicks_previos == medicion.maniobra.clicks_previos
    assert medicion.clicks_previos_en_objeto == medicion.maniobra.clicks_previos_en_objeto
    assert type(MedicionDeEvento.clicks_previos) is property


def test_los_insumos_del_criterio_de_destino_excluyen_el_frame_del_evento():
    """LA GARANTIA ESTRUCTURAL NO CUBRE EL CONTENIDO (defecto medido en la refutacion). Los campos
    `..._en_la_maniobra` revientan con AttributeError si un criterio lee el campo con el evento
    adentro -- pero `pasos_con_traslacion`, `colores_alcanzados` y `aproximacion_monotona` los
    calcula el LLAMADOR con un slice `frames[indice - N : indice]`, y ese slice era una convencion
    sin test: mutarlo a `indice + 1` dejaba los 23 tests en verde. Es justo el unico criterio de
    objetivo cuyos insumos no derivan de la serie de ocupacion.

    El caso esta construido para que el frame del EVENTO sea el unico que aporta la traslacion y el
    color alcanzado: si el tramo lo incluyera, `alcanzarDestino` pasaria a sostenerse."""
    movil = {(1, 1): 7}
    destino = {(1, 6): 4}
    grillas = []
    for paso in range(4):
        # El movil ni se mueve durante la maniobra: la traslacion ocurre SOLO en el evento.
        grillas.append(_tablero({**movil, **destino}))
    grillas.append(_tablero({(1, 5): 7, **destino}))  # el evento: se mueve y llega al destino
    medicion = medir_evento(_ventana(grillas, paso_del_evento=4))
    assert medicion is not None

    # CON el frame del evento la medicion completa SI ve la traslacion...
    assert medicion.pasos_con_traslacion > 0
    # ...y la vista de la maniobra NO, porque su tramo termina en `indice`.
    assert medicion.maniobra.pasos_con_traslacion_en_la_maniobra == 0
    assert se_sostiene("alcanzarDestino", medicion) is False


# --- 2. La muestra declarada ES la persistida ---------------------------------------------------


def _escribir_corpus(directorio: Path, ventanas: list[dict]) -> Path:
    directorio.mkdir(parents=True, exist_ok=True)
    lineas = "".join(json.dumps(v) + "\n" for v in ventanas)
    (directorio / ARCHIVO_VENTANAS).write_text(lineas, encoding="utf-8")
    transiciones = sorted({f"{v['juego']}:nivel{v['nivelNuevo']}" for v in ventanas})
    manifiesto = {
        "origen": "arcReplayFrames",
        "host": "cluster.test",
        "baseDeDatos": "corpus-de-prueba",
        "filtroRunId": "^harness-local:",
        "documentosLeidos": sum(len(v["frames"]) for v in ventanas),
        "documentosConNivel": len(ventanas),
        "corridas": sorted({v["corrida"] for v in ventanas}),
        "juegos": sorted({v["juego"] for v in ventanas}),
        "ventanas": len(ventanas),
        "transicionesDistintas": transiciones,
        # EL CENSO: lo unico que el JSONL no puede fabricar. Lo escribe el exportador contando las
        # subidas de nivel por un segundo camino y consultando la coleccion; aca se simula igual.
        "censo": {
            "eventosDeSubidaEnLosDocumentos": len(ventanas),
            "transicionesEnLosDocumentos": transiciones,
            "subidasSinPredecesor": 0,
            "documentosDeLaColeccion": sum(len(v["frames"]) for v in ventanas) * 3,
            "documentosConNivelFueraDelFiltro": 0,
        },
        "archivo": ARCHIVO_VENTANAS,
        "sha256": hashlib.sha256(lineas.encode("utf-8")).hexdigest(),
        # Fresco a proposito: un export viejo es, desde la correccion de BL.21728, corpus invalido.
        "exportadoEn": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    (directorio / ARCHIVO_MANIFIESTO).write_text(
        json.dumps(manifiesto, indent=2) + "\n", encoding="utf-8"
    )
    return directorio


def _corpus_de_prueba(tmp_path: Path) -> Path:
    return _escribir_corpus(
        tmp_path / "corpus",
        [_ventana_ft09(juego="ft09"), _ventana_ft09(juego="lp85")],
    )


def test_un_directorio_de_capturas_sueltas_no_pasa_por_corpus(tmp_path: Path):
    suelto = tmp_path / "ventanas"
    suelto.mkdir()
    (suelto / "ft09_120_s1.jsonl").write_text(json.dumps(_ventana_ft09()) + "\n", encoding="utf-8")
    with pytest.raises(CorpusInvalido) as error:
        leer_corpus(suelto)
    assert ARCHIVO_MANIFIESTO in str(error.value)


def test_un_jsonl_alterado_no_pasa_el_sha256(tmp_path: Path):
    corpus = _corpus_de_prueba(tmp_path)
    jsonl = corpus / ARCHIVO_VENTANAS
    # Se le agrega una ventana a mano, como haria un barrido que sigue corriendo.
    with jsonl.open("a", encoding="utf-8") as archivo:
        archivo.write(json.dumps(_ventana_ft09(juego="g50t")) + "\n")
    with pytest.raises(CorpusInvalido) as error:
        leer_corpus(corpus)
    assert "sha256" in str(error.value)


def test_un_manifiesto_que_declara_otra_muestra_no_pasa(tmp_path: Path):
    corpus = _corpus_de_prueba(tmp_path)
    ruta = corpus / ARCHIVO_MANIFIESTO
    manifiesto = json.loads(ruta.read_text(encoding="utf-8"))
    # El defecto exacto de BL.21695: el manifiesto omite un juego que SI esta en el corpus.
    manifiesto["juegos"] = ["ft09"]
    ruta.write_text(json.dumps(manifiesto, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(CorpusInvalido) as error:
        leer_corpus(corpus)
    assert "juegos" in str(error.value)


def _reescribir_manifiesto(corpus: Path, cambios: dict) -> None:
    ruta = corpus / ARCHIVO_MANIFIESTO
    manifiesto = json.loads(ruta.read_text(encoding="utf-8"))
    for clave, valor in cambios.items():
        if isinstance(valor, dict) and isinstance(manifiesto.get(clave), dict):
            manifiesto[clave].update(valor)
        else:
            manifiesto[clave] = valor
    ruta.write_text(json.dumps(manifiesto, indent=2) + "\n", encoding="utf-8")


def test_un_manifiesto_que_declara_otra_cantidad_de_ventanas_no_pasa(tmp_path: Path):
    """CORRECCION DE BL.21728: `test_un_manifiesto_que_declara_otra_muestra_no_pasa` decia cubrir
    esto y solo ejercitaba la comparacion de JUEGOS -- borrar esta verificacion dejaba la suite en
    verde. Es la que menos podia quedar sin pinchar: `ventanas` es el numero que el informe publica
    como tamano de la muestra."""
    corpus = _corpus_de_prueba(tmp_path)
    _reescribir_manifiesto(corpus, {"ventanas": 1})
    with pytest.raises(CorpusInvalido) as error:
        leer_corpus(corpus)
    assert "ventana" in str(error.value)


def test_un_manifiesto_que_declara_otras_transiciones_no_pasa(tmp_path: Path):
    """La otra verificacion que ningun test pinchaba. `transicionesDistintas` es el numero sobre el
    que gatea `muestraChica`, o sea el que decide si un candidato entra al vocabulario."""
    corpus = _corpus_de_prueba(tmp_path)
    _reescribir_manifiesto(corpus, {"transicionesDistintas": ["ft09:nivel1"]})
    with pytest.raises(CorpusInvalido) as error:
        leer_corpus(corpus)
    assert "transiciones" in str(error.value)


# --- 2.b El export contra la COLECCION: lo que el sha256 no puede dar ---------------------------
# EL DEFECTO (refutacion medida de este BL): la cadena de hash ata el informe al export y NUNCA el
# export a la coleccion. Un export a medias con su manifiesto recalculado -- que es lo que produce
# un barrido que sigue corriendo, un bug de reconstruccion o un filtro de runId que deja datos
# afuera -- pasa los tres chequeos y el informe vuelve a publicar una muestra que el corpus
# contradice, sin romper un solo hash.


def test_un_export_a_medias_no_pasa_aunque_su_manifiesto_cierre(tmp_path: Path):
    """LA REPRODUCCION EXACTA DEL DEFECTO ORIGINAL: se saca una ventana del JSONL y se recalcula
    TODO el manifiesto como lo haria el exportador (sha256 incluido). Antes de la correccion esto
    pasaba entero. El censo -- que cuenta las subidas de nivel sobre los DOCUMENTOS, no sobre el
    JSONL -- es lo que no se puede fabricar recalculando el hash."""
    corpus = _escribir_corpus(
        tmp_path / "corpus", [_ventana_ft09(juego="ft09"), _ventana_ft09(juego="g50t")]
    )
    completo = json.loads((corpus / ARCHIVO_MANIFIESTO).read_text(encoding="utf-8"))

    # El export "a medias": g50t desaparece del JSONL y el manifiesto se recalcula sobre lo que
    # quedo, tal cual lo escribiria el exportador.
    incompleto = _escribir_corpus(tmp_path / "corpus", [_ventana_ft09(juego="ft09")])
    _reescribir_manifiesto(incompleto, {"censo": completo["censo"]})

    with pytest.raises(CorpusInvalido) as error:
        leer_corpus(incompleto)
    mensaje = str(error.value)
    assert "censo" in mensaje
    assert "1 ventana" in mensaje and "2 subida" in mensaje


def test_un_manifiesto_sin_censo_no_pasa(tmp_path: Path):
    """Fail-closed y no fail-open: un export anterior a la correccion no trae con que verificar que
    describa la coleccion, y aceptarlo seria volver a confiar solo en el hash."""
    corpus = _corpus_de_prueba(tmp_path)
    ruta = corpus / ARCHIVO_MANIFIESTO
    manifiesto = json.loads(ruta.read_text(encoding="utf-8"))
    del manifiesto["censo"]
    ruta.write_text(json.dumps(manifiesto, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(CorpusInvalido) as error:
        leer_corpus(corpus)
    assert "censo" in str(error.value)


def test_las_transiciones_del_censo_tienen_que_ser_las_del_jsonl(tmp_path: Path):
    corpus = _corpus_de_prueba(tmp_path)
    _reescribir_manifiesto(
        corpus, {"censo": {"transicionesEnLosDocumentos": ["ft09:nivel1", "zz99:nivel4"]}}
    )
    with pytest.raises(CorpusInvalido) as error:
        leer_corpus(corpus)
    assert "censo" in str(error.value)


def test_una_subida_de_nivel_fuera_del_filtro_de_runid_invalida_el_corpus(tmp_path: Path):
    """El filtro `^harness-local:` deja afuera el 95% de la coleccion. Hoy ninguno de esos
    documentos tiene levelsCompleted>0 -- verificado, 165 de 165 adentro -- pero NADA lo
    re-verificaba: si una corrida online registrara una subida de nivel, el export la omitia en
    silencio y el informe seguia diciendo "es lo persistido"."""
    corpus = _corpus_de_prueba(tmp_path)
    _reescribir_manifiesto(corpus, {"censo": {"documentosConNivelFueraDelFiltro": 3}})
    with pytest.raises(CorpusInvalido) as error:
        leer_corpus(corpus)
    assert "FUERA del filtro" in str(error.value)


def test_un_export_viejo_no_pasa_y_se_puede_permitir_a_proposito(tmp_path: Path):
    """LA FORMA EXACTA DEL DEFECTO: el informe corrio a las 18:36:50 sobre un directorio que el
    barrido siguio llenando hasta las 18:41. El export era internamente consistente -- solo que
    describia un pasado -- asi que ningun hash podia verlo."""
    corpus = _corpus_de_prueba(tmp_path)
    viejo = datetime.now(timezone.utc) - MAX_ANTIGUEDAD_DEL_EXPORT - timedelta(minutes=5)
    _reescribir_manifiesto(
        corpus, {"exportadoEn": viejo.isoformat().replace("+00:00", "Z")}
    )
    with pytest.raises(CorpusInvalido) as error:
        leer_corpus(corpus)
    assert "re-export" in str(error.value).lower() or "Re-export" in str(error.value)

    # Y la salida explicita para reproducir una medicion vieja a proposito.
    ventanas, _ = leer_corpus(corpus, permitir_export_viejo=True)
    assert len(ventanas) == 2


def test_el_informe_declara_exactamente_la_muestra_persistida(tmp_path: Path, capsys):
    corpus = _corpus_de_prueba(tmp_path)
    mediciones, procedencia, ventanas = cargar_mediciones(corpus)
    informe = imprimir_informe(mediciones, procedencia, ventanas)
    capsys.readouterr()
    manifiesto = json.loads((corpus / ARCHIVO_MANIFIESTO).read_text(encoding="utf-8"))
    assert informe["eventosMedibles"] == manifiesto["ventanas"]
    assert informe["transicionesDistintas"] == manifiesto["transicionesDistintas"]
    assert sorted(informe["eventosPorJuego"]) == manifiesto["juegos"]
    assert informe["procedencia"]["sha256"] == manifiesto["sha256"]


# --- 3. `muestraChica` gatea de verdad ----------------------------------------------------------


def _mediciones_de(*ventanas: dict) -> list[MedicionDeEvento]:
    medidas = [medir_evento(v) for v in ventanas]
    assert all(m is not None for m in medidas)
    return [m for m in medidas if m is not None]


def _ventana_que_pinta(juego: str, nivel_nuevo: int = 1) -> dict:
    """Una maniobra que llena el tablero de a poco, con VARIOS pasos que suben la ocupacion."""
    grillas = []
    for pintadas in range(1, 6):
        grillas.append(_tablero({(1, x): 5 for x in range(pintadas)}))
    grillas.append(_tablero({(9, 9): 3}))
    return _ventana(grillas, paso_del_evento=5, juego=juego, nivel_nuevo=nivel_nuevo)


def test_muestra_chica_se_calcula_sobre_transiciones_y_no_sobre_juegos():
    """DOS niveles del MISMO juego son DOS transiciones distintas. La regla vieja (`len(juegos) <
    2`) marcaba esto como muestra chica; la nueva no, porque son dos mundos observados."""
    resumen = resumen_de_candidatos(
        _mediciones_de(_ventana_que_pinta("g50t", 1), _ventana_que_pinta("g50t", 2))
    )
    datos = resumen["pintarRegion"]
    assert datos["eventos"] == 2
    assert datos["juegos"] == ["g50t"]
    assert datos["transicionesDistintas"] == 2
    assert datos["muestraChica"] is False
    assert datos["sobrevive"] is True


def test_varias_semillas_del_mismo_nivel_siguen_siendo_UNA_transicion_y_no_alcanzan():
    """Tres corridas que superan el MISMO nivel del MISMO juego son tres eventos y una sola
    observacion: el gate tiene que rechazarlas."""
    resumen = resumen_de_candidatos(
        _mediciones_de(*[_ventana_que_pinta("g50t", 1) for _ in range(3)])
    )
    datos = resumen["pintarRegion"]
    assert datos["eventos"] == 3
    assert datos["transicionesDistintas"] == 1
    assert datos["muestraChica"] is True
    assert datos["sobrevive"] is False
    assert any("muestra chica" in motivo for motivo in datos["porQueNoSobrevive"])


def test_muestra_chica_cambia_el_veredicto_y_saca_al_candidato_del_vocabulario():
    """EL TEST QUE SE PONE ROJO SI `muestraChica` VUELVE A SER DECORATIVO: el MISMO candidato, con
    la misma evidencia por evento, entra o no entra al vocabulario segun el contador."""
    una = resumen_de_candidatos(_mediciones_de(_ventana_que_pinta("g50t", 1)))
    dos = resumen_de_candidatos(
        _mediciones_de(_ventana_que_pinta("g50t", 1), _ventana_que_pinta("m0r0", 1))
    )
    assert una["pintarRegion"]["transicionesDistintas"] < MINIMO_DE_TRANSICIONES
    assert dos["pintarRegion"]["transicionesDistintas"] >= MINIMO_DE_TRANSICIONES
    assert "pintarRegion" in vocabulario_rederivado(una)["seCayeron"]
    assert "pintarRegion" in vocabulario_rederivado(dos)["sobreviven"]


def test_la_masa_de_un_objetivo_rechazado_vuelve_a_desconocido():
    """Un evento sostenido SOLO por un candidato que no sobrevive no esta explicado: contarlo como
    conocido inflaria la cobertura por la puerta de atras."""
    resumen = resumen_de_candidatos(_mediciones_de(_ventana_que_pinta("g50t", 1)))
    assert resumen["pintarRegion"]["sobrevive"] is False
    assert resumen["objetivoDesconocido"]["eventos"] == 1


# --- 4. Frames reales: informativo != inerte != animacion en loop -------------------------------


def _pasos(celdas: list[int], ocupaciones: list[float]) -> list[PasoPrevio]:
    return [
        PasoPrevio(paso=i, celdas_cambiadas=c, ocupacion=o)
        for i, (c, o) in enumerate(zip(celdas, ocupaciones), start=1)
    ]


def test_un_paso_inerte_no_cuenta_como_frame_informativo():
    """lp85 medido: 5 de 9 pasos previos cambian CERO celdas. El agente actuo y el tablero no se
    movio: eso no sostiene ningun veredicto."""
    vista = VistaDeLaManiobra(
        frames_previos=5, pasos=tuple(_pasos([0, 0, 0, 12], [0.5, 0.5, 0.5, 0.6]))
    )
    assert vista.pasos_inertes == 3
    assert vista.animacion_en_loop is False
    assert vista.pasos_en_animacion == 0
    assert vista.pasos_informativos == 1


def test_una_animacion_en_loop_no_cuenta_como_frames_informativos():
    """ft09 medido: 9 pasos previos que cambian EXACTAMENTE 38 celdas con la ocupacion clavada en
    0,4727. Es el tablero animandose solo, no una maniobra."""
    vista = VistaDeLaManiobra(
        frames_previos=10, pasos=tuple(_pasos([38] * 9, [0.4727] * 9))
    )
    assert es_animacion_en_loop(vista.pasos) is True
    assert vista.animacion_en_loop is True
    assert vista.pasos_en_animacion == 9
    assert vista.pasos_informativos == 0


def test_una_serie_mixta_no_se_declara_animacion_en_loop():
    """El sesgo va a NO declarar loop: una serie con un paso distinto es una maniobra con
    repeticion, y llamarla loop descartaria evidencia real."""
    vista = VistaDeLaManiobra(
        frames_previos=5, pasos=tuple(_pasos([38, 38, 40, 38], [0.47, 0.47, 0.48, 0.48]))
    )
    assert vista.animacion_en_loop is False
    assert vista.pasos_informativos == 4


def test_un_paso_que_cambia_celdas_fuera_de_un_loop_es_informativo():
    vista = VistaDeLaManiobra(
        frames_previos=5, pasos=tuple(_pasos([12, 30, 8, 41], [0.50, 0.52, 0.53, 0.55]))
    )
    assert vista.pasos_inertes == 0
    assert vista.pasos_en_animacion == 0
    assert vista.pasos_informativos == 4


def test_una_ventana_truncada_queda_marcada():
    """vc33 nivel 1 tiene framesAntes=2 y votaba igual que una ventana completa de 10."""
    corta = VistaDeLaManiobra(frames_previos=2, pasos=tuple(_pasos([266], [0.38])))
    completa = VistaDeLaManiobra(frames_previos=10, pasos=tuple(_pasos([266] * 9, [0.38] * 9)))
    assert corta.ventana_truncada is True
    assert completa.ventana_truncada is False


def test_el_informe_de_texto_dice_los_frames_reales_de_cada_veredicto(tmp_path: Path, capsys):
    corpus = _corpus_de_prueba(tmp_path)
    mediciones, procedencia, ventanas = cargar_mediciones(corpus)
    imprimir_informe(mediciones, procedencia, ventanas)
    texto = capsys.readouterr().out
    assert "framesAntes=" in texto
    assert "informativo(s)" in texto
    assert "inerte(s)" in texto
    assert "animacion" in texto
    assert "frames reales:" in texto
    assert "VOCABULARIO DE OBJETIVOS RE-DERIVADO" in texto
    # La procedencia va impresa: un numero sin procedencia es lo que permitio el defecto 2.
    assert procedencia.sha256[:12] in texto

    # La regla que define la muestra tambien: "277 documentos" de una coleccion de 5.817 sin decir
    # por que regla es el mismo numero sin procedencia que este BL vino a erradicar.
    assert "seleccion: runId ~" in texto
    assert "censo directo sobre los documentos" in texto


# --- 4.b UN VEREDICTO NECESITA FRAMES REALES *POR EVENTO*, no en la suma -------------------------
# EL DEFECTO (refutacion medida): `sinFramesReales` exigia que la SUMA de frames informativos de
# TODOS los sostenidos fuera 0, y `transicionesDistintas` contaba transiciones sin mirar si cada una
# tenia evidencia propia. Con `MINIMO_DE_TRANSICIONES = 2`, la configuracion "2 transiciones, una de
# ellas vacia" NO es un caso raro: es el borde por el que todo candidato entra al vocabulario.


def _medicion_sintetica(juego: str, celdas_por_paso: list[int]) -> MedicionDeEvento:
    """Una medicion armada a mano cuyo unico rasgo relevante son los frames de la maniobra."""
    vista = VistaDeLaManiobra(
        frames_previos=10,
        pasos=tuple(_pasos(celdas_por_paso, [0.5] * len(celdas_por_paso))),
        ocupacion=tuple([0.5] * len(celdas_por_paso)),
        llenado_monotono_en_la_maniobra=True,
    )
    return MedicionDeEvento(
        juego=juego,
        corrida=f"harness-local:{juego}",
        paso_del_evento=20,
        nivel_previo=0,
        nivel_nuevo=1,
        frames_antes=10,
        frames_despues=0,
        celdas_cambiadas=10,
        fraccion_cambiada=0.01,
        pantalla_nueva=False,
        firma_del_evento="compuesta:aparicion=1",
        maniobra=vista,
    )


def test_una_transicion_sin_un_solo_frame_informativo_no_completa_la_muestra():
    """La mitad de la evidencia no puede ser una maniobra con CERO frames reales -- que es
    justamente la categoria que este BL creo para decir "esto no sostiene ningun veredicto"."""
    con_evidencia = _medicion_sintetica("jA", [5, 7, 9])
    vacia = _medicion_sintetica("jB", [0, 0, 0])
    assert con_evidencia.maniobra.pasos_informativos == 3
    assert vacia.maniobra.pasos_informativos == 0

    resumen = resumen_de_candidatos([con_evidencia, vacia])
    datos = resumen["pintarRegion"]
    assert datos["eventos"] == 2  # los dos lo sostienen...
    assert datos["eventosSinFramesReales"] == 1
    # ...pero la muestra REAL es una sola transicion, asi que no alcanza el minimo.
    assert datos["transicionesDistintas"] == 1
    assert datos["muestraChica"] is True
    assert datos["sobrevive"] is False
    assert "pintarRegion" not in vocabulario_rederivado(resumen)["sobreviven"]


def test_con_evidencia_propia_en_las_dos_transiciones_el_candidato_si_entra():
    """El riesgo simetrico: el gate no puede volverse un tapon. Dos transiciones con frames reales
    propios sobreviven, que es lo que el BL quiere que pase."""
    resumen = resumen_de_candidatos(
        [_medicion_sintetica("jA", [5, 7, 9]), _medicion_sintetica("jB", [4, 6])]
    )
    datos = resumen["pintarRegion"]
    assert datos["eventosSinFramesReales"] == 0
    assert datos["transicionesDistintas"] == 2
    assert datos["sobrevive"] is True
    assert datos["generalizaEntreJuegos"] is True


def test_todos_los_sostenidos_sin_frames_reales_siguen_gateando_por_sinFramesReales():
    resumen = resumen_de_candidatos(
        [_medicion_sintetica("jA", [0, 0]), _medicion_sintetica("jB", [0, 0, 0])]
    )
    datos = resumen["pintarRegion"]
    assert datos["sinFramesReales"] is True
    assert datos["transicionesDistintas"] == 0
    assert datos["sobrevive"] is False


# --- 5. El ancho de ventana es UNO, aunque este escrito en tres lugares --------------------------


def test_el_ancho_nominal_de_ventana_es_el_mismo_en_los_tres_modulos():
    """`ventana_truncada` -- el aviso que pidio el defecto 4 -- se calcula contra la copia de
    `maniobra_previa`, mientras que quien decide cuantos frames hay REALMENTE es
    `replayWindowExport.ts` (el exportador) y quien captura es `captura_de_niveles`. Si alguien sube
    la ventana a 15 y el export sigue recortando en 10, `ventana_truncada` daria False para TODO,
    apagando el aviso justo cuando mas haria falta. Los comentarios justifican no importar entre
    capas (aislamiento MIT-0 del runner, no atar el modulo al capturador) -- pero entonces hace
    falta este test, que es lo que faltaba."""
    from captura_de_niveles import VENTANA_POR_DEFECTO

    assert ANCHO_NOMINAL_DE_VENTANA == VENTANA_POR_DEFECTO

    ts = (
        Path(__file__).resolve().parents[2]
        / "arc-agi-runner"
        / "src"
        / "replayWindowExport.ts"
    )
    if not ts.exists():  # el agente extraido del monorepo no lo tiene, y eso es correcto
        pytest.skip(f"{ts} no esta -- se corre desde el monorepo")
    declarado = re.search(r"VENTANA_POR_DEFECTO\s*=\s*(\d+)", ts.read_text(encoding="utf-8"))
    assert declarado is not None, "replayWindowExport.ts dejo de declarar VENTANA_POR_DEFECTO"
    assert int(declarado.group(1)) == ANCHO_NOMINAL_DE_VENTANA


# --- 6. SIN MEDIR no es REFUTADO ----------------------------------------------------------------
# EL DEFECTO (refutacion medida): el cierre del BL presentaba "`recolectarTodo` y `alcanzarDestino`
# caen a 0/14" como dos refutaciones del mismo arreglo. Solo la primera lo es. `alcanzarDestino`
# nunca tuvo un evento a favor NI en contra: su insumo `aproximacion_monotona_en_la_maniobra` esta
# VACIO en los 14 eventos del corpus, o sea que el criterio no pudo evaluarse. Un 0/14 sin varianza
# no es un descarte, y la diferencia decide el proximo paso: recapturar contra descartar.


def test_un_candidato_cuyos_insumos_no_varian_queda_SIN_MEDIR_y_no_refutado():
    mediciones = [_medicion_sintetica("jA", [5, 7]), _medicion_sintetica("jB", [4, 6])]
    resumen = resumen_de_candidatos(mediciones)
    # `alcanzarDestino` no se sostiene en ninguno, y sus insumos son constantes en la muestra.
    datos = resumen["alcanzarDestino"]
    assert datos["eventos"] == 0
    assert "aproximacion_monotona_en_la_maniobra" in datos["insumosSinVarianza"]
    assert datos["sinVarianzaEnLosInsumos"] is True
    assert any("SIN MEDIR" in m for m in datos["porQueNoSobrevive"])

    vocabulario = vocabulario_rederivado(resumen)
    assert "alcanzarDestino" in vocabulario["sinMedir"]
    assert "alcanzarDestino" not in vocabulario["refutados"]
    # `seCayeron` sigue siendo la union, para no romper a quien ya lo lee.
    assert "alcanzarDestino" in vocabulario["seCayeron"]


def test_un_candidato_con_insumos_que_varian_y_no_se_sostiene_SI_esta_refutado():
    """El riesgo simetrico: si el insumo VARIA y aun asi nunca da True, el 0/N si es un descarte y
    llamarlo "sin medir" seria la sobreafirmacion opuesta."""
    con_llenado = _medicion_sintetica("jA", [5, 7])
    sin_llenado = _medicion_sintetica("jB", [4, 6])
    object.__setattr__(sin_llenado.maniobra, "llenado_monotono_en_la_maniobra", False)
    resumen = resumen_de_candidatos([con_llenado, sin_llenado])
    datos = resumen["pintarRegion"]
    assert datos["varianzaDeLosInsumos"]["llenado_monotono_en_la_maniobra"] == 2
    assert datos["insumosSinVarianza"] == []
    assert datos["sinVarianzaEnLosInsumos"] is False
    assert "pintarRegion" in vocabulario_rederivado(resumen)["refutados"]


def test_cada_candidato_declara_los_insumos_que_su_criterio_lee():
    """Los insumos no son documentacion: son lo que hace posible distinguir "sin medir" de
    "refutado". Un candidato sin insumos declarados vuelve a mezclar las dos cosas en silencio."""
    for nombre, candidato in CANDIDATOS.items():
        assert candidato.insumos, f"{nombre} no declara sus insumos"
        sujeto = VistaDeLaManiobra if candidato.tipo == "objetivo" else MedicionDeEvento
        for campo in candidato.insumos:
            assert hasattr(sujeto, campo) or campo in getattr(
                sujeto, "__annotations__", {}
            ), f"{nombre}: el insumo {campo} no existe en {sujeto.__name__}"


# --- 7. EL SILENCIO COMPUESTO SE DISTINGUE DE UNA MEZCLA QUE SI NOMBRA --------------------------
# EL DEFECTO (refutacion de BL.21741, aguas abajo de este informe): `eventoSinMecanicaDeObjeto`
# excluye TODO `compuesta:` en bloque, asi que `compuesta:desconocida=1` -- nada nombrado -- y
# `compuesta:aparicion=10+,desaparicion=4-9,desconocida=4-9,recoloreo=1` -- cuatro tipos nombrados --
# se leian igual. Esa es exactamente la distincion que BL.21741 dice haber comprado.


def test_el_informe_distingue_el_silencio_compuesto_de_una_mezcla_que_nombra_tipos():
    from arc_agent.world_model.mechanics_signature import es_firma_de_silencio

    assert es_firma_de_silencio("compuesta:desconocida=1") is True
    assert es_firma_de_silencio("compuesta:aparicion=1,desconocida=2-3") is False

    callado = _medicion_sintetica("jA", [5, 7])
    callado.firma_del_evento = "compuesta:desconocida=1"
    hablado = _medicion_sintetica("jB", [4, 6])
    hablado.firma_del_evento = "compuesta:aparicion=10+,desconocida=4-9,recoloreo=1"

    resumen = resumen_de_candidatos([callado, hablado])
    # El descriptor viejo no puede separarlos: los dos son "no es UNA mecanica unica".
    assert resumen["eventoSinMecanicaDeObjeto"]["eventos"] == 2
    # El nuevo si, y es lo unico que responde "el detector nombro algo o no".
    assert resumen["eventoSinNingunaMecanicaNombrada"]["eventos"] == 1
    assert se_sostiene("eventoSinNingunaMecanicaNombrada", callado) is True
    assert se_sostiene("eventoSinNingunaMecanicaNombrada", hablado) is False
