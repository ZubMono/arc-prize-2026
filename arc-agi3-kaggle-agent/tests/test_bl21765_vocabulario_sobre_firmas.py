"""[arc-agi3-kaggle-agent/tests] BL.21765 -- el vocabulario de objetivos se re-deriva con la
percepcion objeto-centrica CABLEADA hasta la vista de la maniobra, y ninguna de las cosas que mide
puede sostenerse sobre un artefacto de la captura.

EL AGUJERO QUE FIJA ESTE ARCHIVO, medido antes de tocar nada. BL.21741 arreglo la percepcion y
BL.21728 re-derivo el vocabulario y le dio VACIO; las dos cosas se midieron el mismo dia y no se
cruzaron, porque los criterios de tipo objetivo reciben `VistaDeLaManiobra` y esa vista NO TENIA
UN SOLO CAMPO DE PERCEPCION OBJETO-CENTRICA. Traza de entonces (los cuatro criterios de objetivo,
con los atributos que leen):
    alcanzarDestino         -> pasos_con_traslacion / colores_alcanzados / aproximacion_monotona
    recolectarTodo          -> colores_agotados_en_la_maniobra
    pintarRegion            -> llenado_monotono_en_la_maniobra
    resueltoTocandoUnObjeto -> hubo_click / color_bajo_el_click / linea_base_saturada
Ninguno toca una firma NI un cluster. Es el mismo modo de falla que BL.21704: medir un gate contra
codigo que nadie llama.

LA ATRIBUCION, CON EL NUMERO AL LADO, PORQUE ES FACIL AFIRMAR DE MAS. Lo que faltaba era PLOMERIA:
`Mecanica.clusters` con su `.tipo` existe desde ANTES de BL.21741, y lo que ese BL agrego fue el
helper `conteo_de_tipos_de_cluster` y la firma COMPUESTA sobre el mismo dato. Medido con mutacion
sobre el corpus persistido: colapsar toda firma `compuesta:*` a "desconocida" -- la percepcion
EXACTA previa a BL.21741 -- no cambia ningun veredicto. Por eso este archivo no afirma que los
criterios "dependan de la firma": afirma, y prueba, las tres cosas que si son ciertas --
    1) la firma y el desglose de clusters LLEGAN a cada paso de la maniobra (antes no llegaban),
    2) los criterios de objetivo leen ese desglose y lo leen POR PASO, no como total, y
    3) la firma es load-bearing en los dos lugares donde de verdad lo es: la deteccion de loop y
       el guard de "el detector no miro este paso".
`test_colapsar_las_firmas_compuestas_no_cambia_un_veredicto_de_saldo` fija justamente la mitad
NEGATIVA, para que nadie vuelva a escribir que la firma compuesta desbloqueo el vocabulario.

Cada bloque de abajo se pone ROJO si se revierte una parte del arreglo, y NINGUNO afloja las cuatro
defensas de BL.21728 (frame del evento fuera, muestra persistida, `muestraChica` que gatea, frames
reales declarados): los criterios nuevos siguen siendo de tipo objetivo, asi que el test
parametrizado de aquel BL tambien los obliga a reventar si leen la medicion completa.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from arc_agent.world_model.object_mechanics import detectar_mecanica  # noqa: E402
from arc_agent.world_model.mechanics_signature import firma_de_mecanica  # noqa: E402
from caracterizacion_de_niveles import FRAMES_DE_APROXIMACION, medir_evento  # noqa: E402
from maniobra_previa import (  # noqa: E402
    FIRMA_SIN_MEDIR,
    REPETICIONES_MINIMAS_DE_FIRMA_EN_LOOP,
    PasoPrevio,
    VistaDeLaManiobra,
    es_animacion_en_loop,
)
from medicion_de_evento import MedicionDeEvento  # noqa: E402
from vocabulario_de_objetivos import (  # noqa: E402
    CANDIDATOS,
    cobertura_de_transiciones,
    resumen_de_candidatos,
    se_sostiene,
    vocabulario_rederivado,
)

LADO = 12
#: Criterios de objetivo que BL.21765 agrega y que SOLO pueden dar True leyendo firmas.
OBJETIVOS_POR_FIRMA = ("recolectarTodoPorObjetos", "pintarRegionPorObjetos")


def _tablero(coloreadas: dict[tuple[int, int], int]) -> list[list[int]]:
    grilla = [[0 for _ in range(LADO)] for _ in range(LADO)]
    for (y, x), color in coloreadas.items():
        grilla[y][x] = color
    return grilla


def _ventana(grillas: list[list[list[int]]], juego: str, nivel_nuevo: int = 1) -> dict:
    paso_del_evento = len(grillas) - 1
    return {
        "juego": juego,
        "corrida": f"harness-local:{juego}:t{nivel_nuevo}",
        "modelo": "harness-local",
        "pasoDelEvento": paso_del_evento,
        "nivelPrevio": nivel_nuevo - 1,
        "nivelNuevo": nivel_nuevo,
        "framesAntes": paso_del_evento,
        "framesDespues": 0,
        "frames": [
            {
                "paso": i,
                "accion": "ACTION1",
                "x": None,
                "y": None,
                "accionesDisponibles": [1, 2, 3, 4, 6],
                "grilla": grilla,
                "nivelesCompletados": nivel_nuevo if i >= paso_del_evento else nivel_nuevo - 1,
                "nivelesParaGanar": 3,
                "estado": "NOT_FINISHED",
                "reinicioCompleto": False,
            }
            for i, grilla in enumerate(grillas)
        ],
    }


def _ventana_que_hace_aparecer(juego: str, nivel_nuevo: int = 1) -> dict:
    """La maniobra AGREGA un objeto por paso: tres apariciones y ninguna desaparicion. La ocupacion
    sube, asi que la serie no puede confundirse con un loop."""
    presentes: dict[tuple[int, int], int] = {(2, 2): 7}
    grillas = [_tablero(presentes)]
    for celda in ((4, 4), (6, 6), (8, 8)):
        presentes = {**presentes, celda: 7}
        grillas.append(_tablero(presentes))
    grillas.append(_tablero({(0, 0): 3, (0, 1): 3}))  # el evento rehace el tablero
    return _ventana(grillas, juego, nivel_nuevo)


def _ventana_que_hace_desaparecer(juego: str, nivel_nuevo: int = 1) -> dict:
    """Espejo: la maniobra SACA un objeto por paso."""
    presentes = {(2, 2): 7, (4, 4): 7, (6, 6): 7, (8, 8): 7}
    grillas = [_tablero(presentes)]
    for celda in ((8, 8), (6, 6), (4, 4)):
        presentes = {k: v for k, v in presentes.items() if k != celda}
        grillas.append(_tablero(presentes))
    grillas.append(_tablero({(0, 0): 3, (0, 1): 3}))
    return _ventana(grillas, juego, nivel_nuevo)


def _medir(ventana: dict) -> MedicionDeEvento:
    medicion = medir_evento(ventana)
    assert medicion is not None
    return medicion


# --- 1. LAS FIRMAS ESTAN CABLEADAS EN EL CAMINO QUE DECIDE --------------------------------------


def test_cada_paso_de_la_maniobra_lleva_la_firma_de_bl21741_de_esa_transicion():
    """La firma de cada paso previo es EXACTAMENTE `firma_de_mecanica(detectar_mecanica(pre, post))`
    de esa transicion -- no una etiqueta paralela ni un recalculo distinto."""
    ventana = _ventana_que_hace_aparecer("g50t")
    medicion = _medir(ventana)
    frames = ventana["frames"]
    assert len(medicion.maniobra.pasos) == medicion.paso_del_evento - 1
    for i, paso in enumerate(medicion.maniobra.pasos, start=1):
        esperada = firma_de_mecanica(
            detectar_mecanica(frames[i - 1]["grilla"], frames[i]["grilla"])
        )
        assert paso.firma == esperada
        assert paso.firma != FIRMA_SIN_MEDIR
    assert medicion.maniobra.firmas_en_la_maniobra == tuple(
        p.firma for p in medicion.maniobra.pasos
    )


def test_las_firmas_previas_salen_de_los_pasos_de_la_maniobra_y_no_de_una_segunda_deteccion():
    """FUENTE UNICA. `firmas_previas` era una segunda pasada de `detectar_mecanica` sobre las mismas
    transiciones; ahora es la cola de las firmas de la maniobra. Si alguien vuelve a bifurcarlas,
    este test se pone rojo cuando las dos se desincronicen."""
    medicion = _medir(_ventana_que_hace_aparecer("g50t"))
    esperadas = [p.firma for p in medicion.maniobra.pasos][-FRAMES_DE_APROXIMACION:]
    assert medicion.firmas_previas == esperadas


@pytest.mark.parametrize("nombre", OBJETIVOS_POR_FIRMA)
def test_un_criterio_de_saldo_deja_de_sostenerse_si_se_le_quitan_los_CLUSTERS(nombre):
    """EL TEST ANTI-CODIGO-MUERTO (el defecto de BL.21704: un gate que medía codigo que nadie
    llamaba). Se mide un evento que SI sostiene el criterio y despues se le vacian los clusters de
    los pasos: si el veredicto no cambia, el criterio no estaba leyendo la percepcion.

    EL NOMBRE DICE CLUSTERS Y NO FIRMAS A PROPOSITO. La version anterior de este test vaciaba las
    dos cosas a la vez y su docstring concluia "el criterio no estaba leyendo las firmas", que es
    justo lo que NO prueba: medido por separado, lo que hace flipear el veredicto es vaciar los
    clusters, no arrasar las firmas. Afirmar de mas en el test que se presenta como la garantia
    anti-codigo-muerto es el mismo modo de falla un nivel mas abajo."""
    ventana = (
        _ventana_que_hace_desaparecer("g50t")
        if nombre == "recolectarTodoPorObjetos"
        else _ventana_que_hace_aparecer("g50t")
    )
    medicion = _medir(ventana)
    assert se_sostiene(nombre, medicion) is True

    ciega = VistaDeLaManiobra(
        frames_previos=medicion.maniobra.frames_previos,
        pasos=tuple(
            PasoPrevio(paso=p.paso, celdas_cambiadas=p.celdas_cambiadas, ocupacion=p.ocupacion)
            for p in medicion.maniobra.pasos
        ),
        ocupacion=medicion.maniobra.ocupacion,
    )
    assert ciega.maniobra_sin_firmas_medidas is True
    assert CANDIDATOS[nombre].prueba(ciega) is False


def test_una_transicion_mezclada_llega_a_la_maniobra_con_firma_COMPUESTA():
    """El colapso que arreglo BL.21741: una transicion con clusters de tipos distintos valia
    "desconocida". Si vuelve a colapsar, la firma del paso deja de empezar con `compuesta:`."""
    antes = _tablero({(2, 2): 7, (2, 3): 7, (8, 8): 5})
    # Un cluster DESAPARECE y otro se RECOLOREA en el mismo paso: dos tipos, o sea mezcla. Las
    # formas son distintas (2 celdas y 1) para que no pueda leerse como una traslacion.
    despues = _tablero({(8, 8): 3})
    firma = firma_de_mecanica(detectar_mecanica(antes, despues))
    assert firma.startswith("compuesta:")
    medicion = _medir(_ventana([antes, despues, despues, _tablero({(0, 0): 3})], "sc25"))
    assert firma in medicion.maniobra.firmas_en_la_maniobra


# --- 2. Los criterios por firma NO ven el frame del evento ---------------------------------------


@pytest.mark.parametrize("nombre", OBJETIVOS_POR_FIRMA)
def test_los_criterios_por_firma_son_de_tipo_objetivo(nombre):
    """De ahi cuelga toda la defensa 1 de BL.21728: `sujeto_de` les pasa la vista de la maniobra y
    el test parametrizado de aquel BL les exige reventar con la medicion completa."""
    assert CANDIDATOS[nombre].tipo == "objetivo"
    assert CANDIDATOS[nombre].se_evalua_sobre == "maniobra"


def test_las_apariciones_que_trae_el_frame_del_evento_no_sostienen_pintar():
    """La forma del artefacto original, escrita sobre el eje de las mecanicas: la maniobra no mueve
    nada y es el EVENTO el que llena el tablero de objetos nuevos."""
    quieto = _tablero({(2, 2): 7})
    estallido = _tablero({(2, 2): 7, **{(4, x): 5 for x in range(0, 10, 2)}})
    medicion = _medir(_ventana([quieto, quieto, quieto, quieto, estallido], "m0r0"))
    assert medicion.colores_aparecidos == [5]
    assert medicion.maniobra.objetos_aparecidos_en_la_maniobra == 0
    assert se_sostiene("pintarRegionPorObjetos", medicion) is False


def test_un_solo_paso_que_borra_muchos_objetos_es_un_escalon_y_no_una_recoleccion():
    """Mismo argumento que `MINIMO_DE_PASOS_QUE_MUEVEN`: la desaparicion tiene que sostenerse en
    varios pasos, no en uno solo que borra tres cosas de golpe."""
    lleno = _tablero({(2, 2): 7, (4, 4): 7, (6, 6): 7, (8, 8): 7})
    vacio = _tablero({(2, 2): 7})
    medicion = _medir(_ventana([lleno, lleno, vacio, vacio, _tablero({(0, 0): 3})], "sc25"))
    assert medicion.maniobra.objetos_desaparecidos_en_la_maniobra == 3
    assert medicion.maniobra.pasos_que_hacen_desaparecer_en_la_maniobra == 1
    assert se_sostiene("recolectarTodoPorObjetos", medicion) is False


# --- 3. Los frames que no valen tampoco aportan CLUSTERS -----------------------------------------


def _paso(i: int, celdas: int, ocupacion: float, firma: str, clusters=()) -> PasoPrevio:
    return PasoPrevio(
        paso=i, celdas_cambiadas=celdas, ocupacion=ocupacion, firma=firma, clusters=clusters
    )


def test_una_animacion_en_loop_no_aporta_clusters_a_la_maniobra():
    """ft09 medido: 9 pasos de exactamente 38 celdas con la ocupacion clavada, alternando
    `recoloreo:8>9` y `recoloreo:9>8`. Sigue siendo un loop, y sus clusters no cuentan."""
    firmas = ["recoloreo:8>9", "recoloreo:9>8"] * 4 + ["recoloreo:8>9"]
    pasos = tuple(
        _paso(i, 38, 0.4727, f, (("recoloreo", 2),)) for i, f in enumerate(firmas, start=1)
    )
    vista = VistaDeLaManiobra(frames_previos=10, pasos=pasos)
    assert vista.animacion_en_loop is True
    assert vista.pasos_informativos == 0
    assert vista.clusters_en_la_maniobra == {}
    assert vista.firma_dominante_en_la_maniobra is None


def test_un_paso_inerte_no_aporta_clusters():
    pasos = (
        _paso(1, 0, 0.5, "sinCambio"),
        _paso(2, 12, 0.6, "aparicion:0>7", (("aparicion", 1),)),
        _paso(3, 0, 0.6, "sinCambio"),
    )
    vista = VistaDeLaManiobra(frames_previos=4, pasos=pasos)
    assert vista.pasos_inertes == 2
    assert vista.clusters_en_la_maniobra == {"aparicion": 1}
    assert vista.pasos_que_hacen_aparecer_en_la_maniobra == 1


def test_una_cadena_de_mecanicas_distintas_ya_no_se_confunde_con_una_animacion_en_loop():
    """lp85 nivel 1 medido: 4 pasos que tocan EXACTAMENTE 293 celdas con la ocupacion clavada -- el
    unico instrumento anterior a BL.21741 los declaraba animacion y BORRABA sus frames de la
    evidencia. Sus firmas son una CADENA (`1>2`, `2>10`, `10>9`, `9>15`): cada paso continua el
    anterior, no vuelve a ningun estado. Un loop cicla; una cadena, no."""
    cadena = ["recoloreo:1>2", "recoloreo:2>10", "recoloreo:10>9", "recoloreo:9>15"]
    pasos = tuple(
        _paso(i, 293, 0.5171, f, (("recoloreo", 19),)) for i, f in enumerate(cadena, start=1)
    )
    vista = VistaDeLaManiobra(frames_previos=10, pasos=pasos)
    assert es_animacion_en_loop(pasos) is False
    assert vista.pasos_informativos == 4
    assert vista.clusters_en_la_maniobra == {"recoloreo": 76}
    # Y NO al reves: este criterio solo puede QUITAR la etiqueta de loop, nunca ponerla. Sin firmas
    # medidas la clasificacion es la misma que antes de BL.21765.
    sin_firmas = tuple(_paso(i, 293, 0.5171, FIRMA_SIN_MEDIR) for i in range(1, 5))
    assert es_animacion_en_loop(sin_firmas) is True
    assert REPETICIONES_MINIMAS_DE_FIRMA_EN_LOOP == 2


# --- 4. Sobrevivir al gate de muestra NO es generalizar entre juegos -----------------------------


def _mediciones(*ventanas: dict) -> list[MedicionDeEvento]:
    return [_medir(v) for v in ventanas]


def test_dos_niveles_del_mismo_juego_sobreviven_pero_no_generalizan():
    """El gate de BL.21728 (transiciones distintas) NO se toca -- se le agrega al lado el numero que
    dice si la evidencia viene de un solo mundo. Es la pregunta que decide si el vocabulario sirve:
    los juegos de evaluacion son OTROS."""
    resumen = resumen_de_candidatos(
        _mediciones(
            _ventana_que_hace_aparecer("vc33", 1), _ventana_que_hace_aparecer("vc33", 2)
        )
    )
    datos = resumen["pintarRegionPorObjetos"]
    assert datos["transicionesDistintas"] == 2
    assert datos["juegosDistintos"] == 1
    assert datos["sostenidoPorUnSoloJuego"] is True
    assert datos["sobrevive"] is True
    assert datos["generalizaEntreJuegos"] is False
    vocabulario = vocabulario_rederivado(resumen)
    assert "pintarRegionPorObjetos" in vocabulario["sobreviven"]
    assert vocabulario["sobrevivenYGeneralizanEntreJuegos"] == []


def test_dos_juegos_distintos_si_generalizan():
    resumen = resumen_de_candidatos(
        _mediciones(
            _ventana_que_hace_aparecer("vc33", 1), _ventana_que_hace_aparecer("m0r0", 1)
        )
    )
    datos = resumen["pintarRegionPorObjetos"]
    assert datos["juegosDistintos"] == 2
    assert datos["sostenidoPorUnSoloJuego"] is False
    assert datos["generalizaEntreJuegos"] is True
    assert (
        "pintarRegionPorObjetos"
        in vocabulario_rederivado(resumen)["sobrevivenYGeneralizanEntreJuegos"]
    )


# --- 5. Las dos preguntas de BL.21765, contestadas con numeros ----------------------------------


def test_la_cobertura_cuenta_transiciones_y_no_eventos():
    mediciones = _mediciones(
        _ventana_que_hace_aparecer("vc33", 1),
        _ventana_que_hace_aparecer("vc33", 2),
        _ventana_que_hace_desaparecer("g50t", 1),
    )
    resumen = resumen_de_candidatos(mediciones)
    cobertura = cobertura_de_transiciones(mediciones, resumen)
    assert cobertura["transicionesDistintas"] == 3
    # `recolectarTodoPorObjetos` se sostiene en g50t pero con UNA sola transicion: no sobrevive, asi
    # que no cubre nada. Contar su transicion como cubierta seria inflar por la puerta de atras.
    assert resumen["recolectarTodoPorObjetos"]["sobrevive"] is False
    assert cobertura["porTransicion"]["g50t:nivel1"]["tiposQueLaCubren"] == []
    assert cobertura["transicionesCubiertas"] == 2
    assert cobertura["transicionesQueComparten"] == 2
    assert "pintarRegionPorObjetos" in cobertura["tiposQueCubrenMasDeUnaTransicion"]
    assert cobertura["transicionesPorTipo"]["pintarRegionPorObjetos"] == [
        "vc33:nivel1",
        "vc33:nivel2",
    ]


def test_un_tipo_que_cubre_una_sola_transicion_no_cuenta_como_compartido():
    """Un vocabulario con una entrada por transicion es una lista de nombres propios. Para que
    `transicionesQueComparten` sea > 0 hace falta que UN tipo cubra DOS transiciones."""
    mediciones = _mediciones(
        _ventana_que_hace_aparecer("vc33", 1), _ventana_que_hace_desaparecer("g50t", 1)
    )
    cobertura = cobertura_de_transiciones(mediciones, resumen_de_candidatos(mediciones))
    assert cobertura["transicionesDistintas"] == 2
    assert cobertura["transicionesCubiertas"] == 0
    assert cobertura["transicionesQueComparten"] == 0
    assert cobertura["tiposQueCubrenMasDeUnaTransicion"] == []



def test_la_firma_dominante_de_la_maniobra_viaja_a_la_cobertura():
    """Es la lectura directa de la percepcion de BL.21741 sobre los frames previos: permite ver si
    dos transiciones se resolvieron repitiendo la misma mecanica AUNQUE ningun candidato las
    cubra -- que es el caso del corpus real."""
    mediciones = _mediciones(_ventana_que_hace_aparecer("vc33", 1))
    cobertura = cobertura_de_transiciones(mediciones, resumen_de_candidatos(mediciones))
    dominantes = cobertura["porTransicion"]["vc33:nivel1"]["firmaDominanteDeLaManiobra"]
    assert dominantes == [mediciones[0].maniobra.firma_dominante_en_la_maniobra]
    assert dominantes != ["sinPasosInformativos"]
