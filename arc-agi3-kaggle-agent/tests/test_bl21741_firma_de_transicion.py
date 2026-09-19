"""[arc-agi3-kaggle-agent/tests] BL.21741 -- los contratos que impiden que la percepcion
objeto-centrica vuelva a ser CIEGA a la transicion de nivel.

EL DEFECTO MEDIDO. Sobre el corpus persistido de subidas de nivel (14 eventos, 8 transiciones
distintas, 6 juegos), `firma_de_mecanica` valia "desconocida" en 14 de 14 y las 8 transiciones
distintas eran indistinguibles entre si -- el detector se callaba justo en el instante que decide el
score. Dos causas, y cada bloque de este archivo fija UNA:

1. EL SILENCIO NO DECIA POR QUE. `_mecanica_vacia("desconocida")` se devolvia tanto cuando el
   analisis miro y no supo nombrar como cuando NO MIRO (tope de celdas superado, o grillas de forma
   distinta). Aguas abajo, el silencio se leia como quietud.
2. LA MEZCLA NO TENIA NOMBRE. La firma global colapsaba a "desconocida" en cuanto los clusters no
   eran todos del mismo tipo, y una subida de nivel es SIEMPRE una mezcla.

Y el bloque 3 fija el TOPE, que hasta este BL no lo fijaba ningun test -- que es exactamente como
2048 (la mitad exacta de una grilla 64x64) pudo quedarse ahi sin un experimento detras.

Las grillas son sinteticas y minimas a proposito: reproducen la FORMA de lo medido (mezclas de
apariciones, desapariciones, recoloreos y clusters innombrables) sin depender del corpus, que es un
artefacto de runtime y no viaja al repo. El experimento sobre el corpus real vive en
`scripts/medir_tope_de_mecanica.py --experimento`.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arc_agent.world_model.object_mechanics import (  # noqa: E402
    MAX_CELDAS_CAMBIADAS,
    MAX_TAMANO_OBJETO,
    TIPOS_DE_MECANICA,
    TIPOS_DE_NO_MIRE,
    Grid,
    detectar_mecanica,
)
from arc_agent.world_model.mechanics_signature import (  # noqa: E402
    CORTES_DE_CUBO,
    _cubo,
    conteo_de_tipos_de_cluster,
    es_firma_de_silencio,
    firma_compuesta,
    firma_de_mecanica,
)

FONDO = 0
#: Separacion entre clusters. `agrupar_en_clusters` es 8-conexo: con menos de 2 celdas de aire,
#: dos clusters que se tocan por la esquina son UNO.
AIRE = 3


def _lienzo(alto: int = 48, ancho: int = 48) -> tuple[Grid, Grid]:
    pre = [[FONDO] * ancho for _ in range(alto)]
    post = [[FONDO] * ancho for _ in range(alto)]
    return pre, post


def _color(k: int, salto: int = 0) -> int:
    """Un color distinto por cluster, nunca el fondo. NO es cosmetica: con todos los clusters del
    mismo color, `detectar_mecanica` encuentra una TRASLACION rigida que explica la union de los
    cambios (el respaldo de fusion de `detectar_mecanica`) y el caso deja de ser la mezcla que el
    test quiere medir."""
    return 1 + (k + salto) % 8


def _aparicion(pre: Grid, post: Grid, y: int, x: int, k: int) -> None:
    post[y][x] = _color(k)


def _desaparicion(pre: Grid, post: Grid, y: int, x: int, k: int) -> None:
    pre[y][x] = _color(k)


def _recoloreo(pre: Grid, post: Grid, y: int, x: int, k: int) -> None:
    pre[y][x] = _color(k)
    post[y][x] = _color(k, salto=3)


def _innombrable(pre: Grid, post: Grid, y: int, x: int, k: int) -> None:
    """Un cluster conexo cuyas celdas NO comparten un unico par (desde -> hasta): el caso que
    `_clasificar_cluster` llama "desconocida" -- y que llama asi DESPUES de mirarlo."""
    pre[y][x], post[y][x] = FONDO, _color(k)
    pre[y][x + 1], post[y][x + 1] = _color(k, salto=2), _color(k, salto=5)


def _mezcla(**cantidades: int) -> tuple[Grid, Grid]:
    """Lienzo con `cantidades` clusters de cada tipo, uno por fila, separados y deterministas."""
    constructores = {
        "aparicion": _aparicion,
        "desaparicion": _desaparicion,
        "recoloreo": _recoloreo,
        "desconocida": _innombrable,
    }
    pre, post = _lienzo()
    y = 1
    k = 0
    for tipo in sorted(cantidades):
        for _ in range(cantidades[tipo]):
            constructores[tipo](pre, post, y, 1 + (k % 5) * AIRE, k)
            y += AIRE
            k += 1
    return pre, post


# --- 1. EL SILENCIO TIENE QUE DECIR POR QUE ------------------------------------------------------


def test_sobre_el_tope_tiene_tipo_propio_y_no_desconocida() -> None:
    lado = 128  # 16.384 celdas: supera cualquier tope razonable sin depender del valor vigente
    pre = [[FONDO] * lado for _ in range(lado)]
    post = [[1] * lado for _ in range(lado)]
    mecanica = detectar_mecanica(pre, post)
    assert mecanica.tipo == "sobreElTope"
    assert firma_de_mecanica(mecanica) == "sobreElTope"
    assert mecanica.celdas_cambiadas == lado * lado
    # `clusters` vacio CON tipo propio: el que lee sabe que el vacio es "no mire", no "no habia".
    assert mecanica.clusters == []


def test_forma_incompatible_tiene_tipo_propio_y_no_lanza() -> None:
    mecanica = detectar_mecanica([[1, 2]], [[1], [2]])
    assert mecanica.tipo == "formaIncompatible"
    assert firma_de_mecanica(mecanica) == "formaIncompatible"


def test_desconocida_significa_que_miro_y_no_supo_nombrar() -> None:
    pre, post = _mezcla(desconocida=2, aparicion=1)
    mecanica = detectar_mecanica(pre, post)
    assert mecanica.tipo == "desconocida"
    # LA PRUEBA de que miro: hay clusters analizados. Antes de BL.21741 este caso y el del tope
    # devolvian los dos `clusters == []` con el mismo tipo.
    assert len(mecanica.clusters) == 3


def test_los_tres_silencios_son_distinguibles_entre_si() -> None:
    lado = 128
    sobre_el_tope = detectar_mecanica(
        [[FONDO] * lado for _ in range(lado)], [[1] * lado for _ in range(lado)]
    )
    forma = detectar_mecanica([[1, 2]], [[1], [2]])
    pre, post = _mezcla(desconocida=2, aparicion=1)
    miro = detectar_mecanica(pre, post)
    firmas = {
        firma_de_mecanica(sobre_el_tope),
        firma_de_mecanica(forma),
        firma_de_mecanica(miro),
    }
    assert len(firmas) == 3
    assert {"sobreElTope", "formaIncompatible"}.issubset(firmas)


def test_los_dos_silencios_nuevos_estan_en_el_vocabulario() -> None:
    assert "sobreElTope" in TIPOS_DE_MECANICA
    assert "formaIncompatible" in TIPOS_DE_MECANICA


def test_sin_cambios_sigue_siendo_sin_cambio() -> None:
    pre, post = _lienzo(6, 6)
    mecanica = detectar_mecanica(pre, post)
    assert mecanica.tipo == "sinCambio"
    assert firma_de_mecanica(mecanica) == "sinCambio"


# --- 2. LA MEZCLA TIENE NOMBRE: FIRMA COMPUESTA --------------------------------------------------


def test_la_mezcla_deja_de_llamarse_desconocida() -> None:
    pre, post = _mezcla(recoloreo=1, desaparicion=2)
    mecanica = detectar_mecanica(pre, post)
    assert mecanica.tipo == "desconocida"
    assert firma_de_mecanica(mecanica) == "compuesta:desaparicion=2-3,recoloreo=1"


def test_dos_mezclas_distintas_no_comparten_firma() -> None:
    una = detectar_mecanica(*_mezcla(recoloreo=1, desaparicion=6))
    otra = detectar_mecanica(*_mezcla(recoloreo=6, desaparicion=1))
    assert firma_de_mecanica(una) != firma_de_mecanica(otra)


def test_el_cubo_absorbe_la_variacion_de_conteo_de_la_misma_transicion() -> None:
    """LA PROPIEDAD QUE HACE QUE GENERALICE. Medido: ft09:nivel1 da 3 clusters `desconocida` en un
    evento y 2 en el otro -- la MISMA transicion. Con el conteo exacto la firma se parte en dos y
    memoriza el evento; con cubos por orden de magnitud, las dos capturas dicen lo mismo."""
    dos = detectar_mecanica(*_mezcla(desaparicion=5, desconocida=2))
    tres = detectar_mecanica(*_mezcla(desaparicion=5, desconocida=3))
    assert firma_de_mecanica(dos) == firma_de_mecanica(tres)


def test_un_salto_de_orden_de_magnitud_si_cambia_la_firma() -> None:
    """EL RIESGO SIMETRICO. Un cubo que absorbe todo tampoco distingue nada: 3 y 4 desapariciones
    caen en cubos distintos y la firma lo dice."""
    tres = detectar_mecanica(*_mezcla(aparicion=1, desaparicion=3))
    cuatro = detectar_mecanica(*_mezcla(aparicion=1, desaparicion=4))
    assert firma_de_mecanica(tres) != firma_de_mecanica(cuatro)


def test_la_firma_homogenea_no_cambio() -> None:
    """NO HAY REGRESION: una transicion de UN solo tipo sigue diciendo el par de colores, que es
    mas informativo que el desglose."""
    pre, post = _lienzo()
    for y in (2, 8):
        pre[y][2], post[y][2] = 5, 6
    mecanica = detectar_mecanica(pre, post)
    assert mecanica.tipo == "recoloreo"
    assert firma_de_mecanica(mecanica) == "recoloreo:5>6"


def test_la_firma_compuesta_es_determinista_y_no_depende_del_orden() -> None:
    izquierda = detectar_mecanica(*_mezcla(aparicion=2, desaparicion=2, recoloreo=2))
    derecha = detectar_mecanica(*_mezcla(recoloreo=2, desaparicion=2, aparicion=2))
    firma = firma_de_mecanica(izquierda)
    assert firma == firma_de_mecanica(derecha)
    assert firma == firma_de_mecanica(izquierda)
    # Tipos ordenados alfabeticamente: la firma es una etiqueta canonica, no un orden de recorrido.
    assert firma == "compuesta:aparicion=2-3,desaparicion=2-3,recoloreo=2-3"


def test_firma_compuesta_sin_clusters_admite_el_silencio() -> None:
    """Sin desglose no hay firma compuesta que dar. Inventar una seria peor que admitirlo."""
    lado = 128
    sobre_el_tope = detectar_mecanica(
        [[FONDO] * lado for _ in range(lado)], [[1] * lado for _ in range(lado)]
    )
    assert firma_compuesta(sobre_el_tope) == "desconocida"


def test_conteo_de_tipos_de_cluster_es_la_fuente_unica_del_desglose() -> None:
    mecanica = detectar_mecanica(*_mezcla(aparicion=3, desaparicion=1, desconocida=2))
    conteo = conteo_de_tipos_de_cluster(mecanica)
    assert conteo == {"aparicion": 3, "desaparicion": 1, "desconocida": 2}
    assert list(conteo) == sorted(conteo)
    assert sum(conteo.values()) == len(mecanica.clusters)


def test_cubos_por_orden_de_magnitud() -> None:
    assert CORTES_DE_CUBO == (1, 2, 4, 10)
    assert _cubo(1) == "1"
    assert _cubo(2) == "2-3"
    assert _cubo(3) == "2-3"
    assert _cubo(4) == "4-9"
    assert _cubo(9) == "4-9"
    assert _cubo(10) == "10+"
    assert _cubo(137) == "10+"


# --- 3. EL TOPE, FIJADO POR UN TEST Y DECIDIDO POR UN EXPERIMENTO --------------------------------


def test_el_tope_cubre_la_grilla_entera_de_arc_agi_3() -> None:
    """4096 = 64 * 64, la grilla ENTERA: con este corte el detector siempre MIRA.

    LA TABLA DEL EXPERIMENTO NO SE COPIA ACA (correccion de BL.21741). Este docstring llego a
    tener una version equivocada de esos numeros -- decia "1024 -> 3 firmas / 5 transiciones
    colapsadas" y "3072 -> 6 firmas", cuando la corrida daba 6 calladas y 7 firmas, y dos frases
    despues afirmaba que 3072 "EMPATA en firmas distintas", imposible si fueran 6 contra 7. Una
    tabla escrita a mano al lado de un `assert` de igualdad no la verifica nadie. La tabla vive
    medida en `mediciones/BL21741_tope_de_mecanica.json` y la compara con el comentario del modulo
    `test_la_tabla_del_tope_escrita_en_el_codigo_es_la_medida`.

    Este test existe porque hasta BL.21741 NINGUNO fijaba el tope -- por eso 2048 pudo quedarse
    ahi sin justificacion."""
    assert MAX_CELDAS_CAMBIADAS == 4096
    assert MAX_CELDAS_CAMBIADAS == 64 * 64


def test_la_tabla_del_tope_escrita_en_el_codigo_es_la_medida() -> None:
    """LA TABLA DEL COMENTARIO CONTRA LA MEDICION PUBLICADA, parseada -- no leida a ojo.

    POR QUE (defecto medido en la refutacion de BL.21741). Toda la justificacion de mover el tope
    de 2048 a 4096 vive en un comentario de `object_mechanics.py`, y el unico test que acompanaba
    al numero era `assert MAX_CELDAS_CAMBIADAS == 4096`, que no verifica NADA del experimento. Con
    eso, el comentario del modulo y el docstring del test publicaban tablas distintas entre si y
    las dos distintas de la corrida real, sin que nada se pusiera rojo. Ademas la columna de
    "transiciones calladas" estaba medida con un contador ciego a `compuesta:desconocida=N`, o sea
    que el "0 calladas con 4096" -- el unico argumento que separaba 4096 de 3072 -- era un
    artefacto del prefijo.

    Este test cierra el circuito: parsea las filas del comentario y las compara con el artefacto
    que produjo el script. Cambiar el motor sin re-medir, o re-medir sin actualizar el comentario,
    se pone rojo."""
    fuente = (
        Path(__file__).resolve().parents[1] / "arc_agent" / "world_model" / "object_mechanics.py"
    ).read_text(encoding="utf-8")
    filas = re.findall(
        r"^#\s+tope (\d+) -> (\d+) firmas distintas \| (\d+) (?:transiciones )?calladas?",
        fuente,
        re.MULTILINE,
    )
    assert len(filas) >= 4, "el comentario del tope perdio su tabla de discriminacion"

    medicion = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "mediciones"
            / "BL21741_tope_de_mecanica.json"
        ).read_text(encoding="utf-8")
    )
    por_tope = medicion["discriminacionPorTope"]
    for tope, firmas, calladas in filas:
        medido = por_tope[tope]
        assert int(firmas) == medido["firmasDistintasEntreTransiciones"], (
            f"tope {tope}: el comentario dice {firmas} firmas distintas y la medicion "
            f"{medido['firmasDistintasEntreTransiciones']}"
        )
        assert int(calladas) == len(medido["transicionesEnSilencio"]), (
            f"tope {tope}: el comentario dice {calladas} calladas y la medicion "
            f"{len(medido['transicionesEnSilencio'])} ({medido['transicionesEnSilencio']})"
        )

    # Y el corte elegido tiene que ser el que la propia tabla justifica: nadie mas puede empatarle
    # en firmas distintas y callar menos.
    vigente = por_tope[str(MAX_CELDAS_CAMBIADAS)]
    for tope, datos in por_tope.items():
        if int(tope) == MAX_CELDAS_CAMBIADAS:
            continue
        mejor = datos["firmasDistintasEntreTransiciones"] > vigente[
            "firmasDistintasEntreTransiciones"
        ] or (
            datos["firmasDistintasEntreTransiciones"]
            == vigente["firmasDistintasEntreTransiciones"]
            and len(datos["transicionesEnSilencio"]) < len(vigente["transicionesEnSilencio"])
        )
        assert not mejor, f"el tope {tope} domina al vigente y el codigo no lo refleja"


def test_la_medicion_publicada_sale_del_corpus_persistido() -> None:
    """El artefacto que sostiene la tabla declara su procedencia: sin eso seria un JSON suelto."""
    medicion = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "mediciones"
            / "BL21741_tope_de_mecanica.json"
        ).read_text(encoding="utf-8")
    )
    procedencia = medicion["procedencia"]
    assert procedencia["origen"] == "arcReplayFrames"
    assert len(procedencia["sha256"]) == 64
    assert procedencia["ventanas"] == 14
    assert len(procedencia["transicionesDistintas"]) == 8
    assert medicion["firma"].startswith("vigente")


def test_justo_en_el_tope_todavia_se_mira_y_una_celda_mas_no() -> None:
    """El corte es `>`, no `>=`: el limite es analizable. Fijarlo importa porque el tope define
    donde el detector se declara incompetente."""
    ancho = MAX_CELDAS_CAMBIADAS + 1
    pre = [[FONDO] * ancho]
    en_el_tope = [[FONDO] * ancho]
    for x in range(MAX_CELDAS_CAMBIADAS):
        en_el_tope[0][x] = 1
    assert detectar_mecanica(pre, en_el_tope).tipo != "sobreElTope"

    una_mas = [[1] * ancho]
    assert detectar_mecanica(pre, una_mas).tipo == "sobreElTope"


def test_subir_el_tope_no_inventa_traslaciones() -> None:
    """EL RIESGO DE REGRESION DEL PUNTO 3, acotado por construccion y medido.

    Subir el tope hace que frames que antes no se analizaban ahora SI se analicen, y el unico
    resultado que podria hacer dano es que uno de ellos se lea como `traslacion`: `direction_beliefs
    .direccion_de_traslacion` alimenta el mapeo accion -> direccion SOLO con ese tipo, asi que una
    traslacion espuria en el frame de cambio de nivel ensuciaria el mapeo del mando.

    No puede pasar, y no por suerte: `_traslacion_de_cluster` exige que TODOS los cambios del
    cluster caigan en `R U (R+d)` con `|R| <= MAX_TAMANO_OBJETO`, o sea que un cluster de mas de
    2 * MAX_TAMANO_OBJETO celdas NUNCA es traslacion. Medido ademas sobre los 272 pares
    consecutivos del corpus: subir el tope de 2048 a 4096 cambia la firma en 6 pares (los 6 frames
    de subida de nivel) y en 0 de ellos el tipo pasa a `traslacion`."""
    lado = 64
    bloque = 40
    pre = [[FONDO] * lado for _ in range(lado)]
    post = [[FONDO] * lado for _ in range(lado)]
    for y in range(2, 2 + bloque):
        for x in range(2, 2 + bloque):
            pre[y][x] = 1
            post[y][x + 20] = 1  # el MISMO bloque, corrido 20 columnas: traslacion rigida perfecta

    mecanica = detectar_mecanica(pre, post)
    assert mecanica.celdas_cambiadas > 2 * MAX_TAMANO_OBJETO
    assert mecanica.tipo != "traslacion"
    assert all(c.tipo != "traslacion" for c in mecanica.clusters)


# --- 4. EL SILENCIO NOMBRADO TIENE QUE SER LEIDO AGUAS ABAJO --------------------------------------
#
# Nombrar `formaIncompatible` en `detectar_mecanica` no arregla nada por si solo: los dos
# consumidores que deciden si una accion es INERTE preguntaban `celdas_cambiadas == 0`, y ese cero
# es el que trae `formaIncompatible` SIN HABER CONTADO NADA. O sea que el paso en que ni siquiera
# se pudieron comparar las dos grillas se contaba como evidencia de que el boton no hace nada --
# la inferencia opuesta a la correcta, y exactamente la forma que toma "el silencio se lee como
# quietud" una capa mas abajo. En el corpus persistido las 272 grillas son 64x64 y el caso no
# ocurre nunca, asi que estos contratos son lo unico que lo sostiene.


def test_forma_incompatible_no_es_evidencia_de_boton_inerte() -> None:
    from arc_agent.direction_beliefs import _evento_sin_traslacion
    from arc_agent.mechanics_posterior import EVENTO_DESCONOCIDA, EVENTO_SIN_CAMBIO

    mecanica = detectar_mecanica([[1, 2]], [[1], [2]])
    assert mecanica.celdas_cambiadas == 0  # el cero que confundia a los consumidores
    evento = _evento_sin_traslacion(mecanica, None)
    assert evento.tipo == EVENTO_DESCONOCIDA
    assert evento.tipo != EVENTO_SIN_CAMBIO


def test_sin_cambio_real_sigue_siendo_evidencia_de_boton_inerte() -> None:
    """El riesgo simetrico del contrato de arriba: la guarda no puede tragarse el `sinCambio`
    legitimo, que es la evidencia con la que el posterior descarta botones."""
    from arc_agent.direction_beliefs import _evento_sin_traslacion
    from arc_agent.mechanics_posterior import EVENTO_SIN_CAMBIO

    pre, post = _lienzo(6, 6)
    mecanica = detectar_mecanica(pre, post)
    assert mecanica.tipo == "sinCambio"
    assert _evento_sin_traslacion(mecanica, None).tipo == EVENTO_SIN_CAMBIO


def test_incognita_no_cuenta_forma_incompatible_como_inerte() -> None:
    from arc_agent.direction_beliefs import FIRMA_DESCONOCIDA, FIRMA_INERTE, IncognitaDeMecanica

    incognita = IncognitaDeMecanica()
    firma = incognita.observar(detectar_mecanica([[1, 2]], [[1], [2]]))
    assert firma == FIRMA_DESCONOCIDA
    assert incognita.conteos[FIRMA_INERTE] == 0


def test_incognita_sigue_leyendo_sobre_el_tope_como_cambio_de_escena() -> None:
    """`sobreElTope` tambien es "no mire", pero NO se trata igual: conto las celdas antes de
    rendirse y ese conteo es exacto, asi que la firma que solo mira el tamano del cambio conserva
    dato bueno. Mandarlo a `desconocido` seria perder informacion por prolijidad."""
    from arc_agent.direction_beliefs import FIRMA_CAMBIO_DE_ESCENA, IncognitaDeMecanica

    lado = 128
    mecanica = detectar_mecanica(
        [[FONDO] * lado for _ in range(lado)], [[1] * lado for _ in range(lado)]
    )
    assert mecanica.tipo == "sobreElTope"
    assert IncognitaDeMecanica().observar(mecanica) == FIRMA_CAMBIO_DE_ESCENA


def test_sobre_el_tope_no_se_lee_como_detector_que_miro_y_no_supo() -> None:
    """CORRECCION DE BL.21741 (defecto medido en la refutacion). `_evento_sin_traslacion` tenia
    guarda propia para `formaIncompatible` y `sobreElTope` caia por todas las ramas hasta el
    `desconocida` del final -- el mismo cubo que alimenta `L_DETECTOR_DESCONOCIDA`, calibrada para
    "el detector MIRO y no supo". No es lo que paso: no miro los clusters, pero conto las celdas y
    ese conteo es exacto y enorme.

    Va a `otra` (mecanica visible no direccional), que es la MISMA lectura que ya hacia
    `IncognitaDeMecanica` mandandolo a `cambioDeEscena`. Con el tope en el area de la grilla la rama
    es inalcanzable en ARC-AGI-3 -- por eso el defecto era invisible -- y sigue siendo alcanzable
    para grillas de otro tamano, que es lo que este test cubre."""
    from arc_agent.direction_beliefs import _evento_sin_traslacion
    from arc_agent.mechanics_posterior import EVENTO_DESCONOCIDA, EVENTO_OTRA, EVENTO_SIN_CAMBIO

    lado = 128
    mecanica = detectar_mecanica(
        [[FONDO] * lado for _ in range(lado)], [[1] * lado for _ in range(lado)]
    )
    assert mecanica.tipo == "sobreElTope"
    assert mecanica.celdas_cambiadas == lado * lado  # conto, y el conteo es exacto

    evento = _evento_sin_traslacion(mecanica, None)
    assert evento.tipo == EVENTO_OTRA
    assert evento.tipo != EVENTO_DESCONOCIDA
    assert evento.tipo != EVENTO_SIN_CAMBIO


def test_los_dos_silencios_de_no_mire_se_distinguen_entre_si_aguas_abajo() -> None:
    """El riesgo simetrico: la guarda nueva no puede tragarse `formaIncompatible`, que SI es
    `desconocida` porque ahi no hubo medicion ninguna. Los dos tipos de "no mire" tienen que llegar
    al posterior por caminos DISTINTOS, o la separacion de `TIPOS_DE_NO_MIRE` no compra nada."""
    from arc_agent.direction_beliefs import _evento_sin_traslacion
    from arc_agent.mechanics_posterior import EVENTO_DESCONOCIDA, EVENTO_OTRA

    lado = 128
    sobre_el_tope = detectar_mecanica(
        [[FONDO] * lado for _ in range(lado)], [[1] * lado for _ in range(lado)]
    )
    forma_incompatible = detectar_mecanica([[1, 2]], [[1], [2]])
    assert {sobre_el_tope.tipo, forma_incompatible.tipo} == set(TIPOS_DE_NO_MIRE)
    assert _evento_sin_traslacion(sobre_el_tope, None).tipo == EVENTO_OTRA
    assert _evento_sin_traslacion(forma_incompatible, None).tipo == EVENTO_DESCONOCIDA


def test_una_mecanica_desconocida_de_verdad_sigue_yendo_a_desconocida() -> None:
    """Y el otro riesgo simetrico: "mire los clusters y no supe nombrarlos" no puede convertirse en
    `otra` de arrastre. Es el unico caso que `L_DETECTOR_DESCONOCIDA` describe bien."""
    from arc_agent.direction_beliefs import _evento_sin_traslacion
    from arc_agent.mechanics_posterior import EVENTO_DESCONOCIDA

    pre, post = _lienzo(8, 8)
    # UN cluster con dos pares de color distintos: el detector mira y no sabe nombrarlo.
    pre[2][2], pre[2][3] = 3, 3
    post[2][2], post[2][3] = 7, 9
    mecanica = detectar_mecanica(pre, post)
    assert mecanica.tipo == "desconocida"
    assert _evento_sin_traslacion(mecanica, None).tipo == EVENTO_DESCONOCIDA


def test_tipo_sin_medicion_es_fuente_unica_y_es_subconjunto_de_no_mire() -> None:
    from arc_agent.world_model import TIPO_SIN_MEDICION, TIPOS_DE_NO_MIRE

    assert TIPO_SIN_MEDICION in TIPOS_DE_NO_MIRE
    assert set(TIPOS_DE_NO_MIRE) <= set(TIPOS_DE_MECANICA)
    # El invariante que justifica la separacion: el que NO tiene medicion sale con cero celdas, y
    # el otro sale con el conteo exacto.
    assert detectar_mecanica([[1, 2]], [[1], [2]]).celdas_cambiadas == 0
