"""[arc-agi3-kaggle-agent/tests] BL.21794 -- la CLASIFICACION DE FRAMES se decide EN LA CAPTURA y
tiene que ser la MISMA que re-deriva el informe, mas las dos auditorias que el informe imprime
antes de cualquier veredicto.

POR QUE IMPORTA, con el numero al lado. De 100 frames de contexto del corpus de BL.21728, 55 son
informativos, 27 INERTES (la transicion no cambio una sola celda) y 18 una ANIMACION EN LOOP (ft09:
9 pasos que cambian exactamente 38 celdas con la ocupacion clavada en 0,4727 -- el juego animandose
solo). Casi la mitad de lo que un informe podria contar como evidencia no sostiene nada, y esa
contabilidad decide cuantos frames REALES respaldan cada veredicto del vocabulario de objetivos.
Hasta este BL se reconstruia en cada corrida del informe: el corpus no decia nada sobre sus propios
frames, asi que dos informes con codigo distinto podian describir la misma muestra de dos maneras y
nada lo detectaba.

DOS INVARIANTES:

  1. UNA SOLA DEFINICION. `clasificar_pasos` es la fuente unica y los tres contadores de
     `VistaDeLaManiobra` cuentan sobre ella. Antes cada uno tenia su predicado en linea y el
     tercero salia por resta.
  2. CAPTURA E INFORME NO PUEDEN DISCREPAR. La captura clasifica con `pasos_de_la_ventana` +
     `clasificar_pasos`, exactamente lo que corre `medir_evento`. Y cuando el corpus trae una clase
     que no coincide con la re-derivacion, el informe lo DECLARA en vez de callarlo.

Ademas se fija que las dos poblaciones del corpus (politica entregada y corridas de MEDICION con
cobertura de fondo) se cuenten por separado: sumarlas sin decirlo describiria al agente entregado
con partidas que no son las suyas.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from caracterizacion_de_niveles import pasos_de_la_ventana  # noqa: E402
from captura_de_niveles import (  # noqa: E402
    CLASE_DEL_EVENTO,
    CLASE_POSTERIOR_AL_EVENTO,
    CLASE_SIN_PREVIO,
    FrameCapturado,
    clases_de_los_frames,
)
from clasificacion_del_corpus import (  # noqa: E402
    auditoria_de_la_clasificacion,
    origen_de_la_muestra,
)
from cobertura_de_fondo import es_corrida_con_fondo, etiqueta_de_corrida  # noqa: E402
from maniobra_previa import VistaDeLaManiobra  # noqa: E402
from paso_de_la_maniobra import (  # noqa: E402
    CLASE_EN_ANIMACION,
    CLASE_INERTE,
    CLASE_INFORMATIVO,
    PasoPrevio,
    clasificar_pasos,
)

LADO = 8


def _tablero(pintadas: dict[tuple[int, int], int]) -> list[list[int]]:
    """Tablero de fondo 0 con las celdas `(x, y)` pintadas del color indicado."""
    grilla = [[0 for _ in range(LADO)] for _ in range(LADO)]
    for (x, y), color in pintadas.items():
        grilla[y][x] = color
    return grilla


# --- la clasificacion de frames, decidida en la captura ----------------------------------------


def _paso(celdas: int, ocupacion: float, firma: str = "recoloreo:1>2") -> PasoPrevio:
    return PasoPrevio(paso=0, celdas_cambiadas=celdas, ocupacion=ocupacion, firma=firma)


def test_la_clasificacion_es_fuente_unica_de_los_tres_contadores_de_la_vista():
    """`pasos_inertes`, `pasos_en_animacion` y `pasos_informativos` cuentan SOBRE `clasificar_pasos`.

    Antes cada contador tenia su propio predicado en linea y el tercero salia por RESTA. Con tres
    definiciones independientes, cambiar una sola (por ejemplo el criterio de loop) podia dejar la
    suma sin cerrar y nadie lo notaba: el informe seguia publicando tres numeros que ya no
    particionaban la serie."""
    # Cuatro pasos activos y DOS firmas que ciclan: es el minimo que `es_animacion_en_loop` admite
    # como loop (`REPETICIONES_MINIMAS_DE_FIRMA_EN_LOOP`), y es la forma exacta de ft09 en el corpus.
    pasos = (
        _paso(0, 0.5),  # inerte
        _paso(38, 0.4727, "recoloreo:8>9"),
        _paso(38, 0.4727, "recoloreo:9>8"),
        _paso(38, 0.4727, "recoloreo:8>9"),
        _paso(38, 0.4727, "recoloreo:9>8"),
        _paso(0, 0.4727),  # inerte
    )
    vista = VistaDeLaManiobra(frames_previos=len(pasos), pasos=pasos)
    clases = clasificar_pasos(pasos)
    assert len(clases) == len(pasos)
    assert vista.pasos_inertes == clases.count(CLASE_INERTE) == 2
    assert vista.pasos_en_animacion == clases.count(CLASE_EN_ANIMACION) == 4
    assert vista.pasos_informativos == clases.count(CLASE_INFORMATIVO) == 0
    assert vista.pasos_inertes + vista.pasos_en_animacion + vista.pasos_informativos == len(pasos)


def test_un_paso_inerte_sigue_siendo_inerte_dentro_de_un_loop():
    """La prioridad es la que ya tenian los contadores (`pasos_en_animacion` solo contaba los NO
    inertes). Fijarla evita que una serie de loop se lleve puestos los ceros y que la resta que
    calculaba `pasos_informativos` volviera negativa."""
    pasos = (
        _paso(0, 0.5),
        _paso(9, 0.5, "a"),
        _paso(9, 0.5, "b"),
        _paso(9, 0.5, "a"),
        _paso(9, 0.5, "b"),
    )
    clases = clasificar_pasos(pasos)
    assert clases[0] == CLASE_INERTE
    assert set(clases[1:]) == {CLASE_EN_ANIMACION}


def _frame(paso: int, grilla: list[list[int]]) -> FrameCapturado:
    return FrameCapturado(
        paso=paso,
        accion="ACTION6",
        x=None,
        y=None,
        acciones_disponibles=[6],
        grilla=grilla,
        niveles_completados=0,
        niveles_para_ganar=1,
        estado="NOT_FINISHED",
        reinicio_completo=False,
    )


def test_la_clase_persistida_en_la_captura_es_la_que_re_deriva_el_informe():
    """EL INVARIANTE 2. Misma ventana -> misma clasificacion, venga del corpus o del informe.

    Se construye una ventana con un paso INERTE (grilla identica) y dos que cambian, se clasifica
    como lo hace la captura y se compara contra `pasos_de_la_ventana` + `clasificar_pasos`, que es
    literalmente lo que corre `medir_evento`. Si algun dia divergen, el corpus estaria afirmando
    sobre sus frames algo distinto de lo que el analisis mide sobre los mismos frames."""
    quieto = _tablero({(1, 1): 5})
    movido = _tablero({(2, 1): 5})
    otro = _tablero({(3, 1): 5})
    frames = [
        _frame(10, quieto),
        _frame(11, quieto),  # inerte: no cambia una sola celda
        _frame(12, movido),
        _frame(13, otro),  # este es el evento
        _frame(14, otro),
    ]
    indice_del_evento = 3
    clasificados = clases_de_los_frames(frames, indice_del_evento)

    frames_json = [{"paso": f.paso, "grilla": f.grilla} for f in frames]
    esperadas = clasificar_pasos(pasos_de_la_ventana(frames_json, indice_del_evento))

    assert [f.clase_de_paso for f in clasificados] == [
        CLASE_SIN_PREVIO,
        *esperadas,
        CLASE_DEL_EVENTO,
        CLASE_POSTERIOR_AL_EVENTO,
    ]
    assert clasificados[1].clase_de_paso == CLASE_INERTE
    assert clasificados[2].clase_de_paso == CLASE_INFORMATIVO


def test_los_frames_que_no_son_maniobra_llevan_nombre_propio_y_no_una_clase_de_maniobra():
    """El frame del evento NO se clasifica como maniobra: meterlo en la serie fue el defecto 1 de
    BL.21728 (`recolectarTodo` afirmaba monotonia que solo existia gracias a ese frame). Y los
    posteriores describen el tablero del nivel SIGUIENTE. Nombrarlos -- en vez de dejar el campo
    ausente -- es lo que permite distinguir "no aplica" de "captura vieja sin clasificar"."""
    grilla = _tablero({(1, 1): 5})
    frames = [_frame(i, grilla) for i in range(4)]
    clasificados = clases_de_los_frames(frames, 2)
    assert clasificados[0].clase_de_paso == CLASE_SIN_PREVIO
    assert clasificados[2].clase_de_paso == CLASE_DEL_EVENTO
    assert clasificados[3].clase_de_paso == CLASE_POSTERIOR_AL_EVENTO
    assert clasificados[2].firma_del_paso == ""


def test_una_ventana_sin_frame_del_evento_no_se_clasifica_en_vez_de_romper():
    """`indice_del_evento <= 0` significa que no hay maniobra que clasificar. La captura devuelve
    los frames tal cual: es un subproducto y jamas puede costar una partida ya jugada."""
    grilla = _tablero({(1, 1): 5})
    frames = [_frame(0, grilla), _frame(1, grilla)]
    assert clases_de_los_frames(frames, 0) == frames


def test_la_clasificacion_viaja_al_json_de_la_ventana():
    """Lo que se persiste tiene que traer la clase por frame Y el resumen por ventana: el resumen
    es lo que se lee sin decodificar 21 grillas de 64x64, y es donde se ve de un vistazo una
    ventana sin un solo frame informativo."""
    from captura_de_niveles import VentanaDeNivel  # noqa: PLC0415

    quieto = _tablero({(1, 1): 5})
    movido = _tablero({(2, 1): 5})
    frames = clases_de_los_frames([_frame(0, quieto), _frame(1, quieto), _frame(2, movido)], 2)
    ventana = VentanaDeNivel(
        juego="ft09",
        corrida="harness-local:ft09:x",
        modelo="harness-local",
        paso_del_evento=2,
        nivel_previo=0,
        nivel_nuevo=1,
        frames=list(frames),
    )
    como_json = ventana.a_json()
    assert como_json["clasificacionDeFrames"] == {CLASE_DEL_EVENTO: 1, CLASE_INERTE: 1, CLASE_SIN_PREVIO: 1}
    assert [f["claseDePaso"] for f in como_json["frames"]] == [
        CLASE_SIN_PREVIO,
        CLASE_INERTE,
        CLASE_DEL_EVENTO,
    ]


# --- las dos auditorias del corpus -------------------------------------------------------------


def _ventana_json(corrida: str, juego: str, nivel: int, frames: list[dict]) -> dict:
    return {
        "juego": juego,
        "corrida": corrida,
        "nivelNuevo": nivel,
        "pasoDelEvento": frames[-1]["paso"],
        "frames": frames,
    }


def _frame_json(paso: int, grilla: list[list[int]], clase: str | None = None) -> dict:
    salida: dict = {"paso": paso, "grilla": grilla, "accion": "ACTION6"}
    if clase is not None:
        salida["claseDePaso"] = clase
    return salida


def test_el_informe_separa_las_dos_poblaciones_del_corpus():
    """Las corridas de fondo PUNTUAN PEOR a proposito: sumarlas a las de la politica entregada sin
    decirlo describiria al agente con partidas que no son las suyas. La marca sale del `runId`, que
    es lo unico que viaja con el frame -- un registro aparte se desincroniza."""
    quieto = _tablero({(1, 1): 5})
    normal = _ventana_json(
        "harness-local:vc33:20260819T160000Z",
        "vc33",
        1,
        [_frame_json(0, quieto), _frame_json(1, quieto)],
    )
    de_fondo = _ventana_json(
        "harness-local:sc25:20260819T161000Z-fondo30",
        "sc25",
        2,
        [_frame_json(0, quieto), _frame_json(1, quieto)],
    )
    origen = origen_de_la_muestra([normal, de_fondo])
    assert origen["ventanasDePoliticaEntregada"] == 1
    assert origen["ventanasConCoberturaDeFondo"] == 1
    assert origen["transicionesQueSoloExistenConFondo"] == ["sc25:nivel2"]
    assert origen["juegosConCoberturaDeFondo"] == ["sc25"]


def test_un_juego_llamado_como_la_etiqueta_no_se_confunde_con_una_corrida_de_medicion():
    """La marca se lee del LOTE (ultimo segmento del runId) y no de la cadena entera."""
    assert es_corrida_con_fondo("harness-local:fondo42:20260819T160000Z") is False
    assert es_corrida_con_fondo("harness-local:vc33:20260819T160000Z-fondo30") is True
    assert etiqueta_de_corrida(0.3) == "fondo30"
    assert es_corrida_con_fondo(f"harness-local:vc33:lote-{etiqueta_de_corrida(0.3)}") is True


def test_la_auditoria_declara_que_frames_traen_clase_del_corpus_y_cuantos_coinciden():
    """Una ventana clasificada en la captura tiene que coincidir con la re-derivacion del informe.

    Es el mismo principio que el censo del exportador: dos caminos independientes sobre los mismos
    documentos tienen que dar el mismo numero. Aca ademas se prueba la mitad que importa para no
    sobrevender -- una ventana SIN clase no se cuenta como acuerdo ni como desacuerdo."""
    quieto = _tablero({(1, 1): 5})
    movido = _tablero({(2, 1): 5})
    frames = [
        _frame_json(0, quieto, CLASE_SIN_PREVIO),
        _frame_json(1, quieto, CLASE_INERTE),
        _frame_json(2, movido, CLASE_INFORMATIVO),
        _frame_json(3, movido, CLASE_DEL_EVENTO),
    ]
    clasificada = _ventana_json("harness-local:ft09:lote", "ft09", 1, frames)
    clasificada["pasoDelEvento"] = 3
    sin_clase = _ventana_json(
        "harness-local:lp85:viejo", "lp85", 1, [_frame_json(0, quieto), _frame_json(1, movido)]
    )

    auditoria = auditoria_de_la_clasificacion([clasificada, sin_clase])
    assert auditoria["ventanasConClaseDeLaCaptura"] == 1
    assert auditoria["ventanasSinClasificar"] == 1
    assert auditoria["framesConClaseDeLaCaptura"] == 4
    # Solo los frames de MANIOBRA son comparables: `sinPrevio` y `elEvento` son posicionales.
    assert auditoria["framesDeManiobraComparables"] == 2
    assert auditoria["framesDeManiobraQueCoinciden"] == 2
    assert auditoria["acuerdo"] == 1.0
    assert auditoria["cantidadDeDiscrepancias"] == 0


def test_una_clase_del_corpus_que_no_coincide_se_declara_en_vez_de_pasar_desapercibida():
    """Si el corpus dijera `informativo` de un paso que no cambio una sola celda, el informe tiene
    que decirlo: seria la senal de que el corpus y el analisis dejaron de hablar de la misma
    maniobra. No tumba el informe (los veredictos los calcula la re-derivacion) pero no se calla."""
    quieto = _tablero({(1, 1): 5})
    frames = [
        _frame_json(0, quieto, CLASE_SIN_PREVIO),
        _frame_json(1, quieto, CLASE_INFORMATIVO),  # miente: es inerte
        _frame_json(2, quieto, CLASE_DEL_EVENTO),
    ]
    ventana = _ventana_json("harness-local:ft09:lote", "ft09", 1, frames)
    ventana["pasoDelEvento"] = 2
    auditoria = auditoria_de_la_clasificacion([ventana])
    assert auditoria["cantidadDeDiscrepancias"] == 1
    assert auditoria["discrepancias"][0]["enElCorpus"] == CLASE_INFORMATIVO
    assert auditoria["discrepancias"][0]["reDerivada"] == CLASE_INERTE
    assert auditoria["acuerdo"] == 0.0


