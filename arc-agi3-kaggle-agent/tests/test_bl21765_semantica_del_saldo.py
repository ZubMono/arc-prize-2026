"""[arc-agi3-kaggle-agent/tests] BL.21765 -- LA SEMANTICA de los criterios de saldo de objetos:
que lo que miden signifique lo que su nombre promete.

SEPARADO DE `test_bl21765_vocabulario_sobre_firmas.py` A PROPOSITO (y por tamano). Aquel archivo
prueba el CABLEADO -- que la percepcion llegue a la vista de la maniobra y que los criterios la
toquen, que es el defecto de BL.21704. Este prueba que lo que tocan no se pueda satisfacer con un
artefacto de la captura, que es un defecto distinto y fue el que se colo: el criterio tocaba los
clusters (cableado OK) y aun asi el unico "superviviente" del vocabulario era un tablero que
oscila entre dos estados, muestreado un numero IMPAR de veces.

Todas las formas de abajo estan MEDIDAS en el corpus persistido, no inventadas: la oscilacion de
vc33 nivel 1, los pasos balanceados de vc33 nivel 2, la cadena de lp85 nivel 1, el loop de ft09.
Las ventanas sinteticas del otro archivo son monotonas puras (un objeto por paso, sin nada que se
vaya) -- el caso facil, que en el corpus real no ocurre NI UNA VEZ.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from maniobra_previa import (  # noqa: E402
    FIRMA_SIN_MEDIR,
    TIPOS_DE_CLUSTER,
    TIPOS_DE_NO_MIRE,
    PasoPrevio,
    VistaDeLaManiobra,
)
from vocabulario_de_objetivos import CANDIDATOS  # noqa: E402

#: Los dos criterios de saldo que BL.21765 agrega al vocabulario.
OBJETIVOS_POR_FIRMA = ("recolectarTodoPorObjetos", "pintarRegionPorObjetos")


def _paso(i: int, celdas: int, ocupacion: float, firma: str, clusters=()) -> PasoPrevio:
    return PasoPrevio(
        paso=i, celdas_cambiadas=celdas, ocupacion=ocupacion, firma=firma, clusters=clusters
    )


def _oscilacion(pasos: int, con_contraparte: str) -> tuple[PasoPrevio, ...]:
    """Serie que ALTERNA dos estados: un objeto que prende y apaga. Saldo real CERO.

    ES LA FORMA EXACTA DE vc33 NIVEL 1 (paso 62), copiada del volcado del corpus:
        A->B  celdas=266 ocup=0,3799 (aparicion 1, desconocida 1, recoloreo 1)
        B->A  celdas=265 ocup=0,3750 (desaparicion 1, recoloreo 1, traslacion 1)
    El objeto de 108 celdas prende y apaga; la region de 156 celdas sale `desconocida` en un sentido
    y `traslacion` en el otro. Con 9 pasos: 5 apariciones, 4 desapariciones, saldo bruto +1 -- que
    es como el criterio viejo lo dio por SOBREVIVIENTE."""
    serie = []
    for i in range(1, pasos + 1):
        if i % 2:
            serie.append(
                _paso(i, 266, 0.3799, "compuesta:A", (("aparicion", 1), (con_contraparte, 1), ("recoloreo", 1)))
            )
        else:
            serie.append(
                _paso(i, 265, 0.3750, "traslacion:0,4", (("desaparicion", 1), ("recoloreo", 1), ("traslacion", 1)))
            )
    return tuple(serie)


# --- 6. LA SEMANTICA DEL CRITERIO, no solo su cableado (BL.21765, hallazgo del verificador) ------
# El bloque 1 prueba que el criterio TOCA la percepcion. Esto prueba que lo que toca SIGNIFICA lo
# que el nombre del criterio promete. Las ventanas sinteticas de los bloques anteriores son
# monotonas puras (un objeto por paso, sin nada que se vaya): el caso facil, que en el corpus real
# no ocurre NI UNA VEZ.


def test_una_oscilacion_de_saldo_cero_no_sostiene_pintar():
    """EL DEFECTO QUE ESTE BLOQUE FIJA, medido sobre el corpus. La primera version del criterio
    comparaba TOTALES de la maniobra, y con eso `pintarRegionPorObjetos` "sobrevivio" en vc33 con
    5 apariciones contra 4 desapariciones: el MISMO objeto prendiendo y apagando 9 veces. El
    excedente de 1 no es una maniobra de llenado, es que 9 es IMPAR."""
    impar = VistaDeLaManiobra(frames_previos=10, pasos=_oscilacion(9, "desconocida"))
    assert impar.pasos_informativos == 9
    assert impar.animacion_en_loop is False  # 266 vs 265 celdas: la deteccion de loop no la ve
    assert impar.objetos_aparecidos_en_la_maniobra == 5
    assert impar.objetos_desaparecidos_en_la_maniobra == 4
    assert impar.saldo_neto_de_objetos_en_la_maniobra == 1  # el excedente que lo hizo sobrevivir
    # ...y sin embargo NINGUN paso, por si solo, hace crecer el tablero: los 5 que traen una
    # aparicion traen tambien su contraparte sin nombrar, en el MISMO paso.
    assert impar.pasos_que_hacen_aparecer_netamente_en_la_maniobra == 0
    assert CANDIDATOS["pintarRegionPorObjetos"].prueba(impar) is False
    # Y tampoco al reves: los 4 pasos que sacan un objeto no alcanzan, porque el saldo de toda la
    # maniobra no supera a los 5 clusters que el detector no supo nombrar.
    assert impar.pasos_que_hacen_desaparecer_netamente_en_la_maniobra == 4
    assert impar.clusters_sin_nombrar_en_la_maniobra == 5
    assert CANDIDATOS["recolectarTodoPorObjetos"].prueba(impar) is False


def test_el_veredicto_no_puede_depender_de_la_PARIDAD_de_los_frames_capturados():
    """Contrafactual corrido sobre el corpus real: con la version anterior, quitar UN frame previo
    dejaba el vocabulario en vacio y ponerlo lo hacia sobrevivir. Un veredicto que se da vuelta
    porque la ventana tiene 9 pasos en vez de 8 mide la CAPTURA, no el mundo."""
    for pasos in (8, 9, 10, 11):
        vista = VistaDeLaManiobra(frames_previos=10, pasos=_oscilacion(pasos, "desconocida"))
        assert CANDIDATOS["pintarRegionPorObjetos"].prueba(vista) is False, pasos
        assert CANDIDATOS["recolectarTodoPorObjetos"].prueba(vista) is False, pasos


def test_las_contrapartes_que_el_detector_no_supo_nombrar_no_regalan_saldo():
    """vc33 nivel 1 MEDIDO: los 5 pasos que traen una aparicion traen TAMBIEN un cluster
    `desconocida` de 156 celdas -- la misma region que en el sentido inverso sale `traslacion`. Por
    construccion (`_clasificar_cluster`) `desconocida` significa "no es un par unico desde->hasta"
    y puede contener una aparicion y una desaparicion a la vez. Contar solo lo que el detector supo
    nombrar convierte el saldo en una medida de su REGIMEN DE ETIQUETADO."""
    con_contraparte = tuple(
        _paso(i, 140 + i, 0.44 + i / 1000, "compuesta:X", (("aparicion", 1), ("desconocida", 1)))
        for i in range(1, 5)
    )
    vista = VistaDeLaManiobra(frames_previos=10, pasos=con_contraparte)
    assert vista.objetos_aparecidos_en_la_maniobra == 4
    assert vista.objetos_desaparecidos_en_la_maniobra == 0
    assert vista.clusters_sin_nombrar_en_la_maniobra == 4
    assert vista.saldo_neto_de_objetos_en_la_maniobra == 4  # el saldo BRUTO parece un llenado
    assert vista.pasos_que_hacen_aparecer_netamente_en_la_maniobra == 0  # y no lo es
    assert CANDIDATOS["pintarRegionPorObjetos"].prueba(vista) is False
    # LA MITAD INVERSA, para que el test no pase por una razon distinta de la que dice: los MISMOS
    # pasos sin el cluster sin nombrar SI sostienen el criterio. Lo unico que cambia es que el
    # detector supo que ahi no habia contraparte.
    sin_contraparte = tuple(dataclasses.replace(p, clusters=(("aparicion", 1),)) for p in con_contraparte)
    assert CANDIDATOS["pintarRegionPorObjetos"].prueba(
        VistaDeLaManiobra(frames_previos=10, pasos=sin_contraparte)
    ) is True


def test_los_pasos_perfectamente_balanceados_no_cuentan_como_pasos_que_mueven():
    """vc33 nivel 2 MEDIDO: los 9 pasos traen 1 aparicion Y 1 contraparte que se va. El instrumento
    viejo (presencia de clusters por paso) declaraba "sostenido en 9 pasos" sobre una serie de saldo
    cero. `MINIMO_DE_PASOS_QUE_MUEVEN` se introdujo para distinguir maniobra de escalon; sin el
    saldo por paso no distingue maniobra de CHURN."""
    # Celdas y ocupaciones EXACTAS del volcado de vc33 nivel 2 (paso 15), para que la serie no sea
    # ademas un loop: la deteccion de loop exige igualdad exacta y aca no la hay.
    celdas = (141, 173, 141, 142, 141, 173, 174, 141, 141)
    ocupaciones = (0.4453, 0.4492, 0.4463, 0.4434, 0.4404, 0.4443, 0.4482, 0.4453, 0.4424)
    balanceados = tuple(
        _paso(i, c, o, "compuesta:AB", (("aparicion", 1), ("desaparicion", 1), ("recoloreo", 1)))
        for i, (c, o) in enumerate(zip(celdas, ocupaciones), start=1)
    )
    vista = VistaDeLaManiobra(frames_previos=10, pasos=balanceados)
    assert vista.animacion_en_loop is False
    assert vista.pasos_informativos == 9
    assert vista.pasos_que_hacen_aparecer_en_la_maniobra == 9  # el instrumento viejo
    assert vista.pasos_que_hacen_desaparecer_en_la_maniobra == 9
    assert vista.pasos_que_hacen_aparecer_netamente_en_la_maniobra == 0  # el que decide
    assert vista.pasos_que_hacen_desaparecer_netamente_en_la_maniobra == 0
    assert CANDIDATOS["pintarRegionPorObjetos"].prueba(vista) is False
    assert CANDIDATOS["recolectarTodoPorObjetos"].prueba(vista) is False


def test_una_oscilacion_de_dos_estados_se_DECLARA_aunque_no_sea_animacion_en_loop():
    """vc33 nivel 1 MEDIDO: celdas cambiadas [266, 265, 265, 265, 266, 265, 265, 266, 265] y la
    ocupacion en sube-y-baja. `es_animacion_en_loop` compara EXACTO (a proposito), asi que una celda
    de diferencia alcanza para que los 9 pasos se cuenten como informativos y el informe diga
    "18 frames informativos, 0 de animacion". Literalmente cierto y engañoso: son un ciclo de dos
    estados. Se declara al lado, sin tocar la definicion de loop ni descontar frames."""
    vista = VistaDeLaManiobra(frames_previos=10, pasos=_oscilacion(9, "desaparicion"))
    assert vista.animacion_en_loop is False
    assert vista.pasos_informativos == 9
    assert vista.oscilacion_de_firmas is True
    assert vista.pasos_en_oscilacion == 9
    assert vista.a_json()["pasosEnOscilacion"] == 9
    # Una CADENA (cada paso continua el anterior) no es una oscilacion: lp85 nivel 1 medido.
    cadena = tuple(
        _paso(i, 293, 0.5171, f, (("recoloreo", 19),))
        for i, f in enumerate(
            ["recoloreo:1>2", "recoloreo:2>10", "recoloreo:10>9", "recoloreo:9>15"], start=1
        )
    )
    assert VistaDeLaManiobra(frames_previos=10, pasos=cadena).oscilacion_de_firmas is False


# --- 7. Los dos silencios del detector, y los dos silencios del informe --------------------------


def test_los_tipos_de_no_mire_son_los_del_detector_y_no_una_lista_paralela():
    """FUENTE UNICA. `maniobra_previa` replica la lista como literal para no atar un modulo stdlib
    puro al paquete de percepcion; este test es lo que hace que la replica sea una replica."""
    from arc_agent.world_model.object_mechanics import (  # noqa: PLC0415
        TIPOS_DE_MECANICA,
        TIPOS_DE_NO_MIRE as FUENTE_UNICA,
    )

    assert TIPOS_DE_NO_MIRE == FUENTE_UNICA
    # Y el espejo de los tipos de cluster, que hasta BL.21765 el comentario decia tener testeado.
    assert set(TIPOS_DE_CLUSTER) <= set(TIPOS_DE_MECANICA)
    assert set(TIPOS_DE_CLUSTER).isdisjoint(FUENTE_UNICA)


def test_un_paso_que_el_detector_NO_MIRO_no_es_un_paso_inerte():
    """`formaIncompatible` sale del detector con `celdas_cambiadas == 0` sin haber contado nada.
    Leerlo como "el agente actuo y el tablero no se movio" es EXACTAMENTE la regresion que BL.21741
    saco de `direction_beliefs`, reapareciendo en el consumidor nuevo."""
    incompatible = _paso(1, 0, 0.5, "formaIncompatible")
    assert incompatible.no_mirado is True
    assert incompatible.inerte is False
    assert _paso(2, 0, 0.5, "sinCambio").inerte is True
    sobre_el_tope = _paso(3, 5000, 0.5, "sobreElTope")
    assert sobre_el_tope.no_mirado is True
    assert sobre_el_tope.inerte is False


def test_una_maniobra_con_un_paso_sin_mirar_no_sostiene_un_saldo():
    """LA FIRMA ES LOAD-BEARING ACA, y este es el unico criterio de OBJETIVO que la consume: un paso
    gigante que la percepcion se nego a analizar aporta cero clusters, y cero clusters no puede
    leerse como "no paso nada". Sin este guard el veredicto se emite como si la maniobra estuviera
    completamente medida. En el corpus de hoy no dispara (el paso previo mas grande cambia 293
    celdas contra un tope de 4096); con la muestra que el BL recomienda capturar, si."""
    # Ocupacion creciente y celdas distintas: una maniobra de llenado de verdad, no un loop.
    sanos = tuple(
        _paso(i, 10 + i, 0.5 + i / 100, f"aparicion:0>{i}", (("aparicion", 1),))
        for i in range(1, 4)
    )
    assert CANDIDATOS["pintarRegionPorObjetos"].prueba(
        VistaDeLaManiobra(frames_previos=10, pasos=sanos)
    ) is True
    con_agujero = sanos + (_paso(4, 5000, 0.6, "sobreElTope"),)
    vista = VistaDeLaManiobra(frames_previos=10, pasos=con_agujero)
    assert vista.pasos_no_mirados_en_la_maniobra == 1
    assert vista.maniobra_completamente_mirada is False
    assert vista.a_json()["pasosNoMiradosEnLaManiobra"] == 1
    assert CANDIDATOS["pintarRegionPorObjetos"].prueba(vista) is False
    # Y la mitad inversa: si el detector SI miro y no supo nombrar, el paso NO es un agujero -- es
    # una medicion, y se cuenta como tal (contra los clusters sin nombrar).
    miro_y_no_supo = sanos + (_paso(4, 5000, 0.6, "compuesta:desconocida=1", (("desconocida", 1),)),)
    assert VistaDeLaManiobra(
        frames_previos=10, pasos=miro_y_no_supo
    ).maniobra_completamente_mirada is True


def test_sin_pasos_informativos_NO_es_lo_mismo_que_sin_firmas_medidas():
    """ft09 MEDIDO: sus 2 eventos salian marcados "SIN FIRMAS MEDIDAS" teniendo 9 de 9 pasos con
    firma realmente medida (`recoloreo:8>9` / `recoloreo:9>8`). Son un LOOP -- una razon distinta,
    con su propio contador. El docstring de la propiedad fija el contrato opuesto ("cuando es True,
    todo criterio de firma da False por AUSENCIA DE PERCEPCION"), y el informe de un BL cuya entrega
    ES la honestidad del informe no puede confundir las dos cosas."""
    firmas = ["recoloreo:8>9", "recoloreo:9>8"] * 4 + ["recoloreo:8>9"]
    loop = tuple(
        _paso(i, 38, 0.4727, f, (("recoloreo", 2),)) for i, f in enumerate(firmas, start=1)
    )
    vista = VistaDeLaManiobra(frames_previos=10, pasos=loop)
    assert vista.animacion_en_loop is True
    assert vista.sin_pasos_informativos is True
    assert vista.maniobra_sin_firmas_medidas is False  # la percepcion CORRIO, y midio
    # Y el caso que la propiedad si tiene que declarar: hay pasos, ninguno con firma medida.
    ciega = tuple(_paso(i, 12 + i, 0.5 + i / 100, FIRMA_SIN_MEDIR) for i in range(1, 4))
    ciega_vista = VistaDeLaManiobra(frames_previos=10, pasos=ciega)
    assert ciega_vista.sin_pasos_informativos is False
    assert ciega_vista.maniobra_sin_firmas_medidas is True


def test_colapsar_las_firmas_compuestas_no_cambia_un_veredicto_de_saldo():
    """LA MITAD NEGATIVA DE LA ATRIBUCION, fijada a proposito. Colapsar toda firma `compuesta:*` a
    "desconocida" es la percepcion EXACTA previa a BL.21741. Los criterios de saldo leen el DESGLOSE
    DE CLUSTERS, que es dato pre-BL.21741 (`Mecanica.clusters` ya traia `.tipo` por cluster), asi
    que el veredicto no se mueve. Lo que BL.21765 cerro fue la PLOMERIA -- que ese desglose llegara
    a `VistaDeLaManiobra` --, no el colapso de la firma.

    LA SERIE DE ABAJO NO PUEDE SER UN LOOP (celdas y ocupacion distintas paso a paso), y eso aisla
    el saldo de la unica via por la que la firma SI puede mover un veredicto -- ver el test
    siguiente, que fija esa otra mitad."""
    pasos = tuple(
        _paso(i, 10 + i, 0.5 + i / 100, f"compuesta:aparicion={i}", (("aparicion", 1),))
        for i in range(1, 4)
    )
    colapsados = tuple(dataclasses.replace(p, firma="desconocida") for p in pasos)
    for nombre in OBJETIVOS_POR_FIRMA:
        prueba = CANDIDATOS[nombre].prueba
        assert prueba(VistaDeLaManiobra(frames_previos=10, pasos=pasos)) == prueba(
            VistaDeLaManiobra(frames_previos=10, pasos=colapsados)
        )


def test_la_firma_compuesta_SI_puede_dar_vuelta_un_veredicto_por_la_deteccion_de_loop():
    """LA OTRA MITAD, y es la unica via medida por la que el arreglo de BL.21741 puede cambiar un
    veredicto de objetivo. Tres pasos que cambian EXACTAMENTE las mismas celdas con la ocupacion
    clavada son un loop candidato; lo unico que los salva de serlo son sus firmas distintas. Con la
    percepcion previa a BL.21741 esas tres mezclas valian todas "desconocida", la serie se
    declaraba animacion y sus frames desaparecian de la evidencia.

    En el corpus persistido esta via NO se activa (ninguna maniobra combina celdas constantes con
    firmas compuestas distintas), y por eso el vocabulario re-derivado da lo mismo con la percepcion
    vieja que con la nueva. Pero la dependencia existe y esta cableada, que es distinto de no
    existir."""
    mezclas = tuple(
        _paso(i, 293, 0.5171, f"compuesta:aparicion={i}", (("aparicion", 1),)) for i in range(1, 4)
    )
    con_firmas = VistaDeLaManiobra(frames_previos=10, pasos=mezclas)
    colapsada = VistaDeLaManiobra(
        frames_previos=10,
        pasos=tuple(dataclasses.replace(p, firma="desconocida") for p in mezclas),
    )
    assert con_firmas.animacion_en_loop is False
    assert colapsada.animacion_en_loop is True
    assert CANDIDATOS["pintarRegionPorObjetos"].prueba(con_firmas) is True
    assert CANDIDATOS["pintarRegionPorObjetos"].prueba(colapsada) is False

