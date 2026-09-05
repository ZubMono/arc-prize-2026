"""[arc-agi3-kaggle-agent/tests] BL.21704 -- los contratos del detector de CAUSA A DISTANCIA
(boton que abre puerta) y de su confirmacion INTERVENCIONAL.

Los juegos son sinteticos y minimos a proposito: reproducen la FORMA de lo medido en la etapa 1
(co-activacion no local, ligada a una accion, con un objeto trasladandose como confound y un nulo
periodico como trampa) sin depender del corpus, que es un artefacto de runtime con TTL de 30 dias
y que por lo tanto NO puede ser la base de un test reproducible.

Cada bloque fija UNA de las defensas que la medicion mostro necesarias:
 1. la relacion no local SE DETECTA cuando existe;
 2. una puerta que se abre SOLA cada N pasos NO produce relacion (control negativo);
 3. un objeto que se traslada NO inventa una relacion entre su celda vieja y la nueva;
 4. el NULO EMPIRICO se corre de verdad y mata a un par que si sobrevivio a Benjamini-Hochberg
    -- medido, el nulo analitico deja pasar ~45 pares de puro ruido por corpus;
 5. la evidencia INTERVENCIONAL sube mas rapido que la observacional, y la observacional tiene
    techo por debajo del piso que exige el planner;
 6. el tope K = 8 relaciones por partida se respeta.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from math import gcd  # noqa: E402
from functools import reduce  # noqa: E402

from arc_agent.policy import ExplorationPolicy  # noqa: E402
from arc_agent.world_model.grid import BoundingBox  # noqa: E402
from arc_agent.prng import create_seeded_random  # noqa: E402
from arc_agent.types import GameAction  # noqa: E402
from arc_agent.world_model.estadistica_de_coocurrencia import (  # noqa: E402
    MAX_OFFSETS_EXHAUSTIVOS,
    desplazamientos_del_nulo,
)
from arc_agent.world_model.evidencia_relacional import (  # noqa: E402
    APORTE_INTERVENCIONAL,
    APORTE_OBSERVACIONAL,
    CONFIRMACIONES_REQUERIDAS,
    INTENTOS_DE_CONFIRMACION,
    MIN_PASOS_DE_CONTROL,
    PISO_DE_EVIDENCIA_PARA_SUBMETA,
    TASA_BASE_MAXIMA,
    RelacionNoLocal,
    SubMeta,
)
from arc_agent.world_model.object_mechanics import detectar_mecanica  # noqa: E402
from arc_agent.world_model.regiones_de_cambio import (  # noqa: E402
    MAX_PASOS_RETENIDOS,
    SEPARACION_CHEBYSHEV_MINIMA,
    HistorialDeCambios,
    _separar_por_localidad,
    separacion_chebyshev,
)
from arc_agent.world_model.relaciones_no_locales import (  # noqa: E402
    MAX_EXPLOTACIONES_DE_SUBMETA,
    PASOS_MINIMOS_PARA_MINAR,
    MAX_INTENTOS_POR_DISPARADOR,
    MIN_SOPORTE,
    PASOS_SIN_CAMBIO_PARA_SUBMETA,
    TOPE_DE_VOCABULARIO,
    AlmacenDeRelaciones,
)

from _helpers import make_frame  # noqa: E402

ALTO = 48
ANCHO = 48
FONDO = 0
COLOR_BOTON = 5
COLOR_PUERTA = 7

#: Celdas del boton (arriba a la izquierda) y de la puerta (abajo a la derecha). La separacion de
#: Chebyshev entre las dos cajas es 40, muy por encima del minimo de 8.
BOTON = ((2, 2), (2, 3), (3, 2), (3, 3))
PUERTA = ((44, 44), (44, 45), (45, 44), (45, 45))
#: Region de relleno: da marginales y pasos "de fondo" para que el nulo tenga con que comparar.
RELLENO = ((2, 44), (3, 44))

#: Pasos en los que se aprieta el boton. IRREGULARES a proposito: una cadencia periodica es
#: indistinguible de su propio desplazamiento circular y el nulo empirico la rechaza -- con razon.
#: Que el test positivo necesite un patron aperiodico no es una comodidad, es la propiedad que hace
#: que el bloque 2 (puerta periodica) sea un control negativo de verdad.
PASOS_DE_BOTON = (3, 7, 8, 14, 20, 27, 33, 41, 46, 52, 55, 61, 68, 74)
PASOS_TOTALES = 80


def _lienzo() -> list[list[int]]:
    return [[FONDO] * ANCHO for _ in range(ALTO)]


def _pintar(grilla: list[list[int]], celdas, color: int) -> None:
    for y, x in celdas:
        grilla[y][x] = color


def _partida(
    almacen: AlmacenDeRelaciones,
    pasos_de_boton=PASOS_DE_BOTON,
    periodo_de_puerta_sola: int | None = None,
    puerta_sigue_al_boton: bool = True,
) -> None:
    """Simula una partida: el boton se aprieta con ACTION5 en `pasos_de_boton`, el resto de los
    pasos son ACTION1 tocando solo el relleno. `periodo_de_puerta_sola` abre la puerta cada N pasos
    sin que nadie la toque -- el control negativo."""
    estado_boton = False
    estado_puerta = False
    estado_relleno = False
    previa = _lienzo()
    for paso in range(PASOS_TOTALES):
        aprieta = paso in pasos_de_boton
        if aprieta:
            estado_boton = not estado_boton
            if puerta_sigue_al_boton:
                estado_puerta = not estado_puerta
        else:
            estado_relleno = not estado_relleno
        if periodo_de_puerta_sola is not None and paso % periodo_de_puerta_sola == 0:
            estado_puerta = not estado_puerta

        actual = _lienzo()
        if estado_boton:
            _pintar(actual, BOTON, COLOR_BOTON)
        if estado_puerta:
            _pintar(actual, PUERTA, COLOR_PUERTA)
        if estado_relleno:
            _pintar(actual, RELLENO, COLOR_BOTON)
        almacen.observar("ACTION5" if aprieta else "ACTION1", previa, actual)
        previa = actual


def _relacion_entre(almacen: AlmacenDeRelaciones, celda_a, celda_b):
    """Relacion retenida que liga la region que contiene `celda_a` con la que contiene `celda_b`,
    en cualquiera de los dos sentidos."""
    for relacion in almacen.relaciones():
        celdas = (set(relacion.origen.celdas), set(relacion.destino.celdas))
        if (celda_a in celdas[0] and celda_b in celdas[1]) or (
            celda_a in celdas[1] and celda_b in celdas[0]
        ):
            return relacion
    return None


# ============================================================================================
# 1. La relacion no local SE DETECTA cuando existe
# ============================================================================================


def test_boton_y_puerta_separados_producen_una_relacion():
    almacen = AlmacenDeRelaciones()
    _partida(almacen)
    almacen.minar()

    relacion = _relacion_entre(almacen, BOTON[0], PUERTA[0])
    assert relacion is not None, (
        "no se detecto la relacion boton->puerta. Diagnostico por etapa: "
        f"{almacen.diagnostico()}"
    )
    assert relacion.soporte >= MIN_SOPORTE
    assert relacion.fuerza > 0.0, "la fuerza es log(observado/esperado): tiene que ser positiva"
    assert relacion.accion == "ACTION5", "la relacion tiene que quedar ligada al boton que la causa"
    assert relacion.pureza >= 0.8
    assert relacion.confirmacion == "observacional", (
        "recien minada, sin ninguna repeticion propia, la relacion NO puede figurar como "
        "confirmada intervencionalmente"
    )
    assert relacion.soporte > relacion.umbral_del_nulo, "tiene que superar al nulo empirico"


def test_el_boton_y_la_puerta_no_colapsan_en_una_sola_region():
    """El fenomeno que el detector busca hace que las dos celdas co-cambien EXACTAMENTE en los
    mismos pasos, o sea que comparten la firma bit a bit. Sin la separacion por localidad quedarian
    en UNA region y no habria ningun par que testear: el detector se comeria su propia senal."""
    almacen = AlmacenDeRelaciones()
    _partida(almacen)
    regiones = almacen._historial.regiones()  # noqa: SLF001 -- contrato interno, es lo que se fija

    con_boton = [r for r in regiones if BOTON[0] in r.celdas]
    con_puerta = [r for r in regiones if PUERTA[0] in r.celdas]
    assert len(con_boton) == 1 and len(con_puerta) == 1
    assert con_boton[0].id != con_puerta[0].id, "boton y puerta quedaron en la MISMA region"
    assert con_boton[0].firma == con_puerta[0].firma, (
        "el escenario perdio su gracia: las dos regiones tienen que compartir la firma exacta, "
        "que es justamente lo que las haria colapsar sin la separacion por localidad"
    )
    for region in regiones:
        # El invariante que sale de la separacion por localidad: NINGUNA region abarca un hueco no
        # local. Si lo abarcara, `_separar_por_localidad` la devolveria partida en dos.
        assert len(_separar_por_localidad(list(region.celdas))) == 1, (
            f"la region {region.id} abarca un hueco no local: {region.celdas}"
        )
    assert (
        separacion_chebyshev(con_boton[0].caja, con_puerta[0].caja)
        >= SEPARACION_CHEBYSHEV_MINIMA
    )


# ============================================================================================
# 2. Control negativo: la puerta se abre SOLA cada N pasos
# ============================================================================================


def test_puerta_que_se_abre_sola_no_produce_relacion():
    almacen = AlmacenDeRelaciones()
    _partida(almacen, periodo_de_puerta_sola=4, puerta_sigue_al_boton=False)
    almacen.minar()

    relacion = _relacion_entre(almacen, BOTON[0], PUERTA[0])
    assert relacion is None, (
        "se invento una relacion boton->puerta donde la puerta se abre sola: "
        f"{relacion.resumen() if relacion else None}"
    )


def test_puerta_periodica_no_pasa_ni_aunque_coincida_con_el_boton():
    """Version dura del control negativo: la puerta se abre sola con el MISMO periodo con el que se
    aprieta el boton. La co-ocurrencia es perfecta y el nulo analitico la aprueba; el desplazamiento
    circular la mata, porque una senal periodica desplazada un multiplo de su periodo se
    autoreproduce."""
    almacen = AlmacenDeRelaciones()
    _partida(
        almacen,
        pasos_de_boton=tuple(range(0, PASOS_TOTALES, 4)),
        periodo_de_puerta_sola=4,
        puerta_sigue_al_boton=False,
    )
    almacen.minar()

    diagnostico = almacen.diagnostico()
    assert diagnostico["trasBH"] >= 1, (
        "el escenario perdio su gracia: si el par ni siquiera llega a BH, el bloque no prueba "
        "nada sobre el nulo empirico"
    )
    assert diagnostico["trasNuloEmpirico"] == 0, (
        "el nulo empirico NO filtro un par periodico que si habia sobrevivido a Benjamini-"
        f"Hochberg: {diagnostico}"
    )
    assert _relacion_entre(almacen, BOTON[0], PUERTA[0]) is None


# ============================================================================================
# 3. Un objeto que se traslada no inventa una relacion entre su celda vieja y la nueva
# ============================================================================================

BLOQUE = tuple((y, x) for y in range(10, 13) for x in range(0, 3))
SALTO = 24


def _partida_de_traslacion(almacen: AlmacenDeRelaciones) -> list[list[int]]:
    """Un unico objeto rebota entre dos posiciones separadas por `SALTO` columnas. Las dos regiones
    cambiadas (la que abandona y la que ocupa) co-cambian SIEMPRE y estan lejos: es el par espurio
    perfecto, y lo unico que lo distingue de un boton con su puerta es que los detectores locales
    ya lo nombran `traslacion`."""
    previa = _lienzo()
    _pintar(previa, BLOQUE, COLOR_BOTON)
    ultima = previa
    for paso in range(PASOS_TOTALES):
        actual = _lienzo()
        desplazado = paso % 2 == 0
        _pintar(
            actual,
            tuple((y, x + SALTO) for y, x in BLOQUE) if desplazado else BLOQUE,
            COLOR_BOTON,
        )
        almacen.observar("ACTION1", previa, actual)
        ultima = actual
        previa = actual
    return ultima


def test_un_objeto_que_se_traslada_no_genera_relacion_espuria():
    almacen = AlmacenDeRelaciones()
    _partida_de_traslacion(almacen)
    almacen.minar()

    vieja = BLOQUE[0]
    nueva = (BLOQUE[0][0], BLOQUE[0][1] + SALTO)
    assert _relacion_entre(almacen, vieja, nueva) is None, (
        "la traslacion de un objeto se leyo como causa a distancia entre su celda vieja y la "
        f"nueva. Diagnostico: {almacen.diagnostico()}"
    )
    assert almacen.relaciones() == (), (
        "una partida cuyo unico evento es una traslacion no puede producir NINGUNA relacion no "
        f"local: {[r.resumen() for r in almacen.relaciones()]}"
    )


def test_el_escenario_de_traslacion_es_realmente_una_traslacion():
    """Guard del test de arriba: si `detectar_mecanica` no viera una traslacion, el bloque anterior
    pasaria por el motivo equivocado (no habria nada que excluir)."""
    pre = _lienzo()
    _pintar(pre, BLOQUE, COLOR_BOTON)
    post = _lienzo()
    _pintar(post, tuple((y, x + SALTO) for y, x in BLOQUE), COLOR_BOTON)
    mecanica = detectar_mecanica(pre, post)
    assert mecanica.traslacion_principal is not None, (
        f"el detector local no vio la traslacion (tipo={mecanica.tipo}): el control negativo de "
        "traslacion quedaria vacio"
    )
    assert mecanica.traslacion_principal.dx == SALTO


# ============================================================================================
# 4. El nulo empirico se corre de verdad
# ============================================================================================


def test_el_nulo_empirico_se_corre_y_deja_traza_en_cada_relacion():
    almacen = AlmacenDeRelaciones()
    _partida(almacen)
    relaciones = almacen.minar()
    assert relaciones, "sin relaciones el test no prueba nada sobre el nulo"
    for relacion in relaciones:
        assert relacion.soporte > relacion.umbral_del_nulo, (
            "una relacion retenida tiene que superar el percentil 95 del nulo empirico: "
            f"{relacion.resumen()}"
        )


def test_sin_ventana_suficiente_el_nulo_rechaza_en_vez_de_aprobar():
    """Con menos pasos que los que exige el nulo no se puede barajar. La decision correcta es NO
    aceptar nada: aprobar sin nulo es exactamente como se cuelan los ~45 falsos por corpus."""
    almacen = AlmacenDeRelaciones()
    previa = _lienzo()
    for paso in range(6):
        actual = _lienzo()
        if paso % 2 == 0:
            _pintar(actual, BOTON, COLOR_BOTON)
            _pintar(actual, PUERTA, COLOR_PUERTA)
        almacen.observar("ACTION5", previa, actual)
        previa = actual
    assert almacen.minar() == []


# ============================================================================================
# 5. La confirmacion intervencional sube la evidencia mas rapido que la observacional
# ============================================================================================


def _relacion_de_prueba(
    soporte: int,
    exitos: int = 0,
    fallos: int = 0,
    pasos_de_control: int = 4 * MIN_PASOS_DE_CONTROL,
    cambios_sin_accion: int = 0,
) -> RelacionNoLocal:
    almacen = AlmacenDeRelaciones()
    _partida(almacen)
    almacen.minar()
    base = almacen.relaciones()[0]
    return RelacionNoLocal(
        origen=base.origen,
        destino=base.destino,
        desfase=base.desfase,
        soporte=soporte,
        esperado=base.esperado,
        fuerza=base.fuerza,
        p_valor=base.p_valor,
        umbral_del_nulo=base.umbral_del_nulo,
        accion=base.accion,
        pureza=base.pureza,
        exitos=exitos,
        fallos=fallos,
        pasos_de_control=pasos_de_control,
        cambios_sin_accion=cambios_sin_accion,
    )


def test_una_confirmacion_intervencional_pesa_mas_que_muchas_observaciones():
    assert APORTE_INTERVENCIONAL > APORTE_OBSERVACIONAL
    solo_observado = _relacion_de_prueba(soporte=MIN_SOPORTE)
    una_observacion_mas = _relacion_de_prueba(soporte=MIN_SOPORTE + 1)
    una_intervencion = _relacion_de_prueba(soporte=MIN_SOPORTE, exitos=1)

    delta_observacional = una_observacion_mas.evidencia - solo_observado.evidencia
    delta_intervencional = una_intervencion.evidencia - solo_observado.evidencia
    assert delta_intervencional > delta_observacional > 0.0
    assert delta_intervencional > 5 * delta_observacional


def test_la_evidencia_observacional_tiene_techo_por_debajo_del_piso_del_planner():
    """Observar no desconfunde: por muchas co-activaciones que se acumulen, una relacion que nunca
    se probo NO puede dirigir el plan."""
    saturada = _relacion_de_prueba(soporte=10_000)
    assert saturada.evidencia < PISO_DE_EVIDENCIA_PARA_SUBMETA
    assert saturada.confirmacion == "observacional"

    probada = _relacion_de_prueba(soporte=MIN_SOPORTE, exitos=CONFIRMACIONES_REQUERIDAS)
    assert probada.confirmacion == "intervencional"
    assert probada.evidencia >= PISO_DE_EVIDENCIA_PARA_SUBMETA


def test_dos_fallos_refutan_la_relacion_sin_gastar_el_cuarto_intento():
    refutada = _relacion_de_prueba(soporte=MIN_SOPORTE, exitos=1, fallos=2)
    assert refutada.refutada
    assert refutada.intentos < INTENTOS_DE_CONFIRMACION


def test_tres_de_cuatro_repeticiones_confirman_y_habilitan_la_submeta():
    """Recorrido completo del mecanismo central: minar -> sugerir -> repetir -> veredicto."""
    almacen = AlmacenDeRelaciones()
    _partida(almacen)
    almacen.minar()
    assert almacen.relaciones()
    assert almacen.submetas() == (), "sin intervenciones todavia no puede haber sub-metas"

    pre = _lienzo()
    _pintar(pre, BOTON, COLOR_BOTON)
    for _ in range(CONFIRMACIONES_REQUERIDAS):
        sugerida = almacen.sugerir_intervencion(["ACTION1", "ACTION5", "ACTION6"])
        assert sugerida == "ACTION5"
        relacion = almacen.relacion_pendiente
        assert relacion is not None
        post = [list(fila) for fila in pre]
        for y, x in relacion.destino.celdas:
            post[y][x] = COLOR_PUERTA if post[y][x] == FONDO else FONDO
        almacen.observar("ACTION5", pre, post)
        pre = post

    confirmada = almacen.relaciones()[0]
    assert confirmada.exitos == CONFIRMACIONES_REQUERIDAS
    assert confirmada.confirmacion == "intervencional"
    submetas = almacen.submetas()
    assert submetas and submetas[0].accion == "ACTION5"
    assert submetas[0].confirmacion == "intervencional"


def test_una_relacion_falsa_muere_al_segundo_fallo_en_vivo():
    almacen = AlmacenDeRelaciones()
    _partida(almacen)
    almacen.minar()
    antes = len(almacen.relaciones())
    assert antes >= 1

    objetivo = almacen.relaciones()[0]
    for _ in range(2):
        almacen.registrar_intervencion(objetivo, exito=False)
    assert objetivo.clave not in {r.clave for r in almacen.relaciones()}

    # Y no vuelve a entrar por la puerta de atras en la proxima mineria.
    almacen.minar()
    assert objetivo.clave not in {r.clave for r in almacen.relaciones()}


def test_no_se_cuenta_evidencia_de_una_intervencion_que_no_se_ejecuto():
    almacen = AlmacenDeRelaciones()
    _partida(almacen)
    almacen.minar()
    sugerida = almacen.sugerir_intervencion(["ACTION5"])
    assert sugerida == "ACTION5"
    relacion = almacen.relacion_pendiente
    assert relacion is not None

    pre = _lienzo()
    post = _lienzo()
    _pintar(post, PUERTA, COLOR_PUERTA)
    almacen.observar("ACTION1", pre, post)  # otra accion: la intervencion no ocurrio
    assert relacion.intentos == 0, (
        "se acredito evidencia intervencional a una accion que la politica nunca ejecuto"
    )


def test_un_paso_masivo_no_regala_una_confirmacion():
    """Un RESET o una transicion de nivel cambia medio tablero, asi que el destino de CUALQUIER
    relacion pendiente cambia casi con seguridad. Juzgar la intervencion contra ese paso seria un
    exito regalado -- exactamente la evidencia falsa que la via intervencional existe para evitar."""
    almacen = AlmacenDeRelaciones()
    _partida(almacen)
    almacen.minar()
    assert almacen.sugerir_intervencion(["ACTION5"]) == "ACTION5"
    relacion = almacen.relacion_pendiente
    assert relacion is not None

    previa = _lienzo()
    masivo = [[COLOR_PUERTA] * ANCHO for _ in range(ALTO)]
    almacen.observar("ACTION5", previa, masivo)
    assert relacion.intentos == 0, "un paso masivo acredito una confirmacion intervencional"
    assert almacen.relacion_pendiente is None, "la intervencion tiene que descartarse, no quedar viva"


# ============================================================================================
# 5-bis. Una relacion de CLICK solo es repetible con su coordenada
# ============================================================================================

CLICK = (2, 2)


def _partida_de_click(almacen: AlmacenDeRelaciones, coordenada_fija: bool = True) -> None:
    """El boton se dispara con ACTION6 SOBRE una celda concreta. Si `coordenada_fija` es False, el
    mismo ACTION6 llega desde celdas distintas: no hay una intervencion unica que repetir."""
    estado_boton = estado_puerta = estado_relleno = False
    previa = _lienzo()
    for paso in range(PASOS_TOTALES):
        aprieta = paso in PASOS_DE_BOTON
        if aprieta:
            estado_boton = not estado_boton
            estado_puerta = not estado_puerta
        else:
            estado_relleno = not estado_relleno
        actual = _lienzo()
        if estado_boton:
            _pintar(actual, BOTON, COLOR_BOTON)
        if estado_puerta:
            _pintar(actual, PUERTA, COLOR_PUERTA)
        if estado_relleno:
            _pintar(actual, RELLENO, COLOR_BOTON)
        if aprieta:
            donde = CLICK if coordenada_fija else (CLICK[0], CLICK[1] + paso % 7)
            almacen.observar("ACTION6", previa, actual, coordenada=donde)
        else:
            almacen.observar("ACTION1", previa, actual)
        previa = actual


def test_una_relacion_de_click_guarda_la_coordenada_que_la_dispara():
    """Medido en vivo sobre lp85: las 8 relaciones retenidas eran de click y las 8 se refutaron en
    su PRIMERA repeticion, porque la intervencion clickeaba el centro de la region ORIGEN -- que en
    desfase 0 es un EFECTO del click, no el lugar donde se clickeo. Repetir "ACTION6" sin su
    coordenada no repite nada: es una refutacion automatica disfrazada de test."""
    almacen = AlmacenDeRelaciones()
    _partida_de_click(almacen)
    almacen.minar()
    relacion = _relacion_entre(almacen, BOTON[0], PUERTA[0])
    assert relacion is not None, f"diagnostico: {almacen.diagnostico()}"
    assert relacion.accion == "ACTION6"
    assert relacion.coordenada == CLICK, (
        "la relacion de click tiene que recordar DONDE se clickeo, no solo que fue un click"
    )
    assert almacen.submetas() == ()  # todavia sin confirmar


def test_un_click_sin_coordenada_dominante_no_se_retiene():
    """Si las co-activaciones vienen de celdas distintas no hay UNA intervencion que repetir, y una
    relacion que no se puede probar no entra al vocabulario."""
    almacen = AlmacenDeRelaciones()
    _partida_de_click(almacen, coordenada_fija=False)
    almacen.minar()
    assert _relacion_entre(almacen, BOTON[0], PUERTA[0]) is None, (
        "se retuvo una relacion de click sin coordenada repetible: "
        f"{almacen.diagnostico()}"
    )


def test_la_confirmacion_de_un_click_se_juzga_repitiendo_su_coordenada():
    almacen = AlmacenDeRelaciones()
    _partida_de_click(almacen)
    almacen.minar()
    pre = _lienzo()
    _pintar(pre, BOTON, COLOR_BOTON)
    for _ in range(CONFIRMACIONES_REQUERIDAS):
        assert almacen.sugerir_intervencion(["ACTION1", "ACTION6"]) == "ACTION6"
        relacion = almacen.relacion_pendiente
        assert relacion is not None and relacion.coordenada == CLICK
        post = [list(fila) for fila in pre]
        for y, x in relacion.destino.celdas:
            post[y][x] = COLOR_PUERTA if post[y][x] == FONDO else FONDO
        almacen.observar("ACTION6", pre, post, coordenada=relacion.coordenada)
        pre = post
    confirmada = almacen.relaciones()[0]
    assert confirmada.confirmacion == "intervencional"
    submetas = almacen.submetas()
    assert submetas and submetas[0].coordenada == CLICK, (
        "la sub-meta que llega al planner tiene que decir DONDE clickear, no solo que clickee"
    )


# ============================================================================================
# 6. El tope K = 8 por partida se respeta
# ============================================================================================


def test_el_tope_de_vocabulario_se_respeta():
    """Diez pares boton/puerta independientes, cada uno con su propio conjunto de pasos: hay mas
    relaciones validas que el tope, y el almacen tiene que quedarse con K = 8."""
    almacen = AlmacenDeRelaciones()
    pares = 10
    botones = [((2, 4 * k), (2, 4 * k + 1)) for k in range(pares)]
    puertas = [((44, 4 * k), (44, 4 * k + 1)) for k in range(pares)]
    # Conjuntos de pasos DISJUNTOS: cada par co-activa solo consigo mismo.
    agenda = {k: tuple(range(5 + k, PASOS_TOTALES, pares)) for k in range(pares)}

    estados = [False] * pares
    previa = _lienzo()
    for paso in range(PASOS_TOTALES):
        activo = next((k for k in range(pares) if paso in agenda[k]), None)
        if activo is not None:
            estados[activo] = not estados[activo]
        actual = _lienzo()
        for k in range(pares):
            if estados[k]:
                _pintar(actual, botones[k], COLOR_BOTON)
                _pintar(actual, puertas[k], COLOR_PUERTA)
        almacen.observar(f"ACTION{1 + (activo or 0) % 4}", previa, actual)
        previa = actual

    relaciones = almacen.minar()
    assert almacen.diagnostico()["trasPureza"] > TOPE_DE_VOCABULARIO, (
        "el escenario perdio su gracia: si no sobran candidatos, el tope no se esta probando. "
        f"Diagnostico: {almacen.diagnostico()}"
    )
    assert len(relaciones) == TOPE_DE_VOCABULARIO
    fuerzas = [r.fuerza for r in relaciones]
    assert fuerzas == sorted(fuerzas, reverse=True), "el tope tiene que quedarse con las MAS fuertes"


def test_una_relacion_probada_no_pierde_su_lugar_contra_una_solo_observada():
    """Defecto MEDIDO en vivo (lp85): el almacen gastaba sus 24 intervenciones, llevaba cinco
    relaciones a 3 de 3 exitos, y despues el tope K=8 las expulsaba en favor de candidatas
    meramente observacionales con mas fuerza bruta -- `submetas()` devolvia cero y el planner no
    veia jamas lo que el agente habia PROBADO. El tope no puede invertir la doctrina del BL."""
    almacen = AlmacenDeRelaciones()
    _partida_de_click(almacen)
    almacen.minar()
    relacion = _relacion_entre(almacen, BOTON[0], PUERTA[0])
    assert relacion is not None

    for _ in range(CONFIRMACIONES_REQUERIDAS):
        almacen.registrar_intervencion(relacion, exito=True)
    assert relacion.confirmacion == "intervencional"

    almacen.minar()  # nueva pasada: el tope vuelve a decidir quien entra
    vivas = {r.clave: r for r in almacen.relaciones()}
    assert relacion.clave in vivas, (
        "una relacion CONFIRMADA intervencionalmente fue expulsada por el tope de vocabulario"
    )
    assert vivas[relacion.clave].confirmacion == "intervencional"
    assert almacen.relaciones()[0].confirmacion == "intervencional", (
        "las probadas tienen que ir primero: son las unicas con evidencia causal"
    )
    assert any(sm.confirmacion == "intervencional" for sm in almacen.submetas())
    assert almacen.diagnostico()["conEvidenciaIntervencional"] >= 1


# ============================================================================================
# Invariantes de costo y de forma del reporte
# ============================================================================================


def test_los_pasos_masivos_no_se_registran():
    """Un RESET o una transicion de nivel hace co-ocurrir todo con todo. Fue el confound DOMINANTE
    del corpus (49.883 pares espurios en lp85 a nivel celda)."""
    historial = HistorialDeCambios()
    previa = _lienzo()
    entero = [[COLOR_BOTON] * ANCHO for _ in range(ALTO)]
    assert historial.observar("RESET", previa, entero) is False
    assert historial.pasos == 0
    assert historial.descartados_por_masivos == 1


def test_el_reporte_nunca_es_un_booleano():
    almacen = AlmacenDeRelaciones()
    _partida(almacen)
    almacen.minar()
    fila = almacen.relaciones()[0].resumen()
    for campo in ("fuerza", "soporte", "accion", "pureza", "confirmacion", "evidencia"):
        assert campo in fila, f"falta {campo} en el reporte de la relacion"
    assert almacen.resumen()["diagnostico"]["paresNoLocales"] >= 1


# ============================================================================================
# 7. BL.21704-v2 -- lo que la revision adversarial encontro roto. Cada test de aca abajo FALLA
#    contra la version anterior del detector: no son refinamientos, son defectos medidos.
# ============================================================================================


def _pasos_de_control(almacen: AlmacenDeRelaciones, relacion, cuantos: int, cambia: bool) -> None:
    """Pasos en que la accion de `relacion` NO se ejecuta. Si `cambia`, el destino cambia igual --
    o sea, cambia SOLO."""
    pre = _lienzo()
    for _ in range(cuantos):
        post = [list(fila) for fila in pre]
        if cambia:
            for y, x in relacion.destino.celdas:
                post[y][x] = COLOR_PUERTA if post[y][x] == FONDO else FONDO
        else:
            post[2][20] = COLOR_BOTON if post[2][20] == FONDO else FONDO
        almacen.observar("ACTION1", pre, post)
        pre = post


def test_una_puerta_que_cambia_sola_no_se_confirma_aunque_acierte_todas():
    """LA CONDICION DE CONTROL. `_cambio_el_destino` solo pregunta si el destino cambio; nunca
    preguntaba CONTRA QUE. Con eso, una puerta que parpadea en todos los pasos llegaba a 3 de 4 y
    emitia sub-meta -- el control negativo que el BL declara central, ausente justo en la etapa que
    otorga el permiso de dirigir el plan. El nulo relevante no es una moneda (p=0,5) sino la tasa
    base de cambio del destino, medida entre 0,06 y 0,24 en lp85 y jamas comparada."""
    almacen = AlmacenDeRelaciones()
    _partida(almacen)
    almacen.minar()
    relacion = almacen.relaciones()[0]

    _pasos_de_control(almacen, relacion, MIN_PASOS_DE_CONTROL + 2, cambia=True)

    assert relacion.tasa_base > TASA_BASE_MAXIMA, (
        f"el escenario perdio su gracia: tasa base {relacion.tasa_base}"
    )
    assert relacion.cambia_sola
    assert relacion.confirmacion == "observacional"
    assert relacion.clave not in {r.clave for r in almacen.relaciones()}, (
        "una relacion cuyo destino cambia solo tiene que salir del vocabulario"
    )
    assert almacen.submetas() == ()


def test_el_control_suficiente_es_requisito_y_no_adorno():
    """Sin pasos de control no hay con que comparar, y el lado correcto en el que fallar es el que
    NO otorga permiso para dirigir el plan."""
    sin_control = _relacion_de_prueba(
        soporte=MIN_SOPORTE, exitos=CONFIRMACIONES_REQUERIDAS, pasos_de_control=0
    )
    assert sin_control.confirmacion == "observacional"
    con_control = _relacion_de_prueba(soporte=MIN_SOPORTE, exitos=CONFIRMACIONES_REQUERIDAS)
    assert con_control.confirmacion == "intervencional"


def test_el_juicio_en_vivo_distingue_exito_de_fallo():
    """MUTATION TESTING: inyectando `return True` al principio de `_cambio_el_destino`, los 22
    tests del BL seguian en VERDE. Los de confirmacion fabricaban el post volteando exactamente
    `relacion.destino.celdas`, y el unico test de fallo llamaba `registrar_intervencion(exito=False)`
    directamente, salteando el juicio. El codigo que decide si una relacion se confirma o se refuta
    estaba cubierto solo por su rama positiva."""
    almacen = AlmacenDeRelaciones()
    _partida(almacen)
    almacen.minar()
    assert almacen.sugerir_intervencion(["ACTION1", "ACTION5"]) == "ACTION5"
    relacion = almacen.relacion_pendiente
    assert relacion is not None

    pre = _lienzo()
    post = [list(fila) for fila in pre]
    post[2][20] = COLOR_BOTON  # el tablero se mueve, pero NO en el destino de la relacion
    almacen.observar("ACTION5", pre, post)
    assert (relacion.exitos, relacion.fallos) == (0, 1), (
        "la via viva tiene que poder REFUTAR, no solo confirmar: "
        f"exitos={relacion.exitos} fallos={relacion.fallos}"
    )


def test_un_click_en_otra_celda_no_acredita_la_confirmacion():
    """El juez comparaba solo el NOMBRE de la accion: un ACTION6 en (47,47) se acreditaba como
    repeticion de una relacion disparada en (2,2). Que la politica hoy alimente la coordenada
    correcta no es garantia -- la clampea a la grilla, asi que un cambio de tamano bastaba para
    acreditar una repeticion que nunca ocurrio. El invariante vive donde se dictamina."""
    almacen = AlmacenDeRelaciones()
    _partida_de_click(almacen)
    almacen.minar()
    assert almacen.sugerir_intervencion(["ACTION1", "ACTION6"]) == "ACTION6"
    relacion = almacen.relacion_pendiente
    assert relacion is not None and relacion.coordenada == CLICK

    pre = _lienzo()
    post = [list(fila) for fila in pre]
    for y, x in relacion.destino.celdas:
        post[y][x] = COLOR_PUERTA
    almacen.observar("ACTION6", pre, post, coordenada=(ALTO - 1, ANCHO - 1))
    assert relacion.intentos == 0, (
        "se acredito una intervencion clickeando una celda que no es la de la relacion"
    )


# -- la franja contigua: el artefacto que producia TODOS los "exitos" del detector --------------

FILA_DE_FRANJA = 26
COLUMNAS_DE_FRANJA = tuple(range(10, 44, 3))


def _partida_de_franja(almacen: AlmacenDeRelaciones) -> None:
    """UN click repinta una FRANJA CONTIGUA: once celdas de la misma fila separadas de a 3. Cada
    click deja una celda distinta afuera, asi que las firmas de co-cambio no son identicas y la
    agrupacion las parte en once regiones -- que es exactamente lo que se midio en lp85."""
    estado = {x: False for x in COLUMNAS_DE_FRANJA}
    previa = _lienzo()
    for paso in range(PASOS_TOTALES):
        aprieta = paso in PASOS_DE_BOTON
        if aprieta:
            afuera = COLUMNAS_DE_FRANJA[paso % len(COLUMNAS_DE_FRANJA)]
            for x in COLUMNAS_DE_FRANJA:
                if x != afuera:
                    estado[x] = not estado[x]
        actual = _lienzo()
        for x, encendida in estado.items():
            if encendida:
                actual[FILA_DE_FRANJA][x] = COLOR_PUERTA
        if not aprieta:
            actual[2][20] = COLOR_BOTON if paso % 2 else FONDO
        almacen.observar(
            "ACTION6" if aprieta else "ACTION1",
            previa,
            actual,
            coordenada=CLICK if aprieta else None,
        )
        previa = actual


def test_una_franja_contigua_que_se_repinta_no_es_causa_a_distancia():
    """EL ARTEFACTO QUE EL DETECTOR CONFIRMABA. Volcando el almacen al terminar lp85 (200 acciones,
    harness real), las 8 relaciones retenidas eran [26,20]->[26,29], [26,17]->[26,26],
    [26,20]->[26,41], [26,17]->[26,38], [26,32]->[26,41], [26,29]->[26,38] -- todas en la fila 26 y
    todas disparadas por el MISMO click -- mas dos en la columna 23. Es UN repintado de franja
    partido en pedazos, con la separacion Chebyshev >= 8 entre extremos convirtiendolo en "no
    local"; y la confirmacion intervencional era trivialmente cierta, porque repetir el click
    vuelve a repintar la franja. Lo que separa un boton de una franja no es la distancia entre los
    extremos sino el HUECO."""
    sin_filtro = AlmacenDeRelaciones()
    original = AlmacenDeRelaciones._encadenado
    try:
        AlmacenDeRelaciones._encadenado = lambda self, candidato, componentes: False
        _partida_de_franja(sin_filtro)
        sin_filtro.minar()
    finally:
        AlmacenDeRelaciones._encadenado = original
    assert len(sin_filtro.relaciones()) >= 5, (
        "sin el filtro de cadena la franja tiene que producir el artefacto que se quiere matar; si "
        f"no, este test no prueba nada. Diagnostico: {sin_filtro.diagnostico()}"
    )

    almacen = AlmacenDeRelaciones()
    _partida_de_franja(almacen)
    almacen.minar()
    diagnostico = almacen.diagnostico()
    assert diagnostico["conSoporte"] > 0, (
        f"el escenario perdio su gracia: no hay candidatos que filtrar. {diagnostico}"
    )
    assert diagnostico["trasCadenaDeCambios"] < diagnostico["conSoporte"], (
        f"el filtro de cadena no descarto ni un candidato de la franja: {diagnostico}"
    )
    assert almacen.relaciones() == (), (
        f"una franja contigua se leyo como causa a distancia: {diagnostico}"
    )
    assert almacen.submetas() == ()


def test_el_boton_y_la_puerta_sobreviven_al_filtro_de_cadena():
    """Guard del test de arriba: el filtro de cadena tiene que matar la franja SIN matar el caso
    que el BL existe para detectar -- entre el boton y la puerta no cambia nada en el medio."""
    almacen = AlmacenDeRelaciones()
    _partida(almacen)
    almacen.minar()
    diagnostico = almacen.diagnostico()
    assert diagnostico["trasCadenaDeCambios"] > 0
    assert _relacion_entre(almacen, BOTON[0], PUERTA[0]) is not None


def _partida_de_traslacion_esporadica(almacen: AlmacenDeRelaciones) -> None:
    """El objeto se traslada solo en los pasos de `PASOS_DE_BOTON` -- no en todos. Es la variante
    que hace falta para que el par LLEGUE VIVO a la exclusion local: cuando la traslacion ocurre en
    todos los pasos, el par muere antes por el propio esperado del binomial (soporte 80 sobre un
    esperado de 80), y entonces el filtro local no esta probando nada."""
    desplazado = False
    relleno = False
    previa = _lienzo()
    _pintar(previa, BLOQUE, COLOR_BOTON)
    for paso in range(PASOS_TOTALES):
        if paso in PASOS_DE_BOTON:
            desplazado = not desplazado
        else:
            relleno = not relleno
        actual = _lienzo()
        _pintar(
            actual,
            tuple((y, x + SALTO) for y, x in BLOQUE) if desplazado else BLOQUE,
            COLOR_BOTON,
        )
        if relleno:
            _pintar(actual, RELLENO, COLOR_PUERTA)
        almacen.observar("ACTION1", previa, actual)
        previa = actual


def test_la_exclusion_por_detectores_locales_es_la_que_mata_la_traslacion():
    """La exclusion por detectores locales estaba declarada OBLIGATORIA y su ausencia no rompia
    NINGUN test: reemplazar el return de `_explicado_por_locales` por `return False` dejaba los 22
    en verde. Este test la hace portante: el par de la traslacion llega VIVO hasta ella (pasa
    soporte y pasa la cadena, porque el objeto salta un hueco vacio) y muere ahi."""
    vieja = BLOQUE[0]
    nueva = (BLOQUE[0][0], BLOQUE[0][1] + SALTO)

    sin_filtro = AlmacenDeRelaciones()
    original = AlmacenDeRelaciones._explicado_por_locales
    try:
        AlmacenDeRelaciones._explicado_por_locales = lambda self, candidato: False
        _partida_de_traslacion_esporadica(sin_filtro)
        sin_filtro.minar()
    finally:
        AlmacenDeRelaciones._explicado_por_locales = original
    assert _relacion_entre(sin_filtro, vieja, nueva) is not None, (
        "sin la exclusion local la traslacion tiene que producir la relacion espuria; si no, este "
        f"test no prueba nada. Diagnostico: {sin_filtro.diagnostico()}"
    )

    almacen = AlmacenDeRelaciones()
    _partida_de_traslacion_esporadica(almacen)
    almacen.minar()
    diagnostico = almacen.diagnostico()
    assert diagnostico["trasCadenaDeCambios"] > 0, (
        f"el par de la traslacion ya venia muerto: el filtro local no prueba nada. {diagnostico}"
    )
    assert diagnostico["trasExclusionLocal"] < diagnostico["trasCadenaDeCambios"], (
        f"la exclusion por detectores locales no descarto nada: {diagnostico}"
    )
    assert _relacion_entre(almacen, vieja, nueva) is None
    assert almacen.relaciones() == ()


# -- pureza de coordenada: el denominador equivocado borraba las relaciones de teclado -----------


def _partida_con_click_intruso(almacen: AlmacenDeRelaciones, intrusos: int) -> None:
    """La partida positiva de siempre, pero `intrusos` de las 14 pulsaciones del boton llegan como
    ACTION6 en una celda cualquiera."""
    estado_boton = estado_puerta = estado_relleno = False
    previa = _lienzo()
    for paso in range(PASOS_TOTALES):
        aprieta = paso in PASOS_DE_BOTON
        if aprieta:
            estado_boton = not estado_boton
            estado_puerta = not estado_puerta
        else:
            estado_relleno = not estado_relleno
        actual = _lienzo()
        if estado_boton:
            _pintar(actual, BOTON, COLOR_BOTON)
        if estado_puerta:
            _pintar(actual, PUERTA, COLOR_PUERTA)
        if estado_relleno:
            _pintar(actual, RELLENO, COLOR_BOTON)
        if aprieta and PASOS_DE_BOTON.index(paso) < intrusos:
            almacen.observar("ACTION6", previa, actual, coordenada=(1, 1))
        elif aprieta:
            almacen.observar("ACTION5", previa, actual)
        else:
            almacen.observar("ACTION1", previa, actual)
        previa = actual


def test_una_relacion_de_teclado_sobrevive_a_un_click_suelto():
    """La pureza de COORDENADA se dividia por el soporte total en vez de por los pasos de la accion
    dominante, y se aplicaba aunque la accion dominante no llevara coordenada. Resultado medido:
    con 1 de 14 pulsaciones cambiada por un ACTION6, la pureza de ACTION5 quedaba en 0,93 -- muy
    por encima del 0,8 -- y la relacion desaparecia igual (trasPureza 1 -> 0). En una politica
    exploratoria que clickea seguido ese es el caso COMUN, y explica que las 8 relaciones retenidas
    en lp85 fueran todas de click: no es que el mundo sea asi, es que el filtro borraba las de
    teclado. Perder sensibilidad en silencio no es conservadurismo."""
    almacen = AlmacenDeRelaciones()
    _partida_con_click_intruso(almacen, intrusos=1)
    almacen.minar()
    relacion = _relacion_entre(almacen, BOTON[0], PUERTA[0])
    assert relacion is not None, (
        f"un unico click intruso borro una relacion de teclado pura: {almacen.diagnostico()}"
    )
    assert relacion.accion == "ACTION5"
    assert relacion.coordenada is None, (
        "una relacion de teclado no puede quedarse con la coordenada de un click ajeno"
    )
    assert relacion.pureza >= 0.8


# -- el nulo empirico -------------------------------------------------------------------------


def test_el_nulo_empirico_recorre_todos_los_desplazamientos_y_no_una_sub_red():
    """El nulo "que MANDA" estaba sesgado por su propia grilla de offsets: con
    `paso = pasos // 21` los 20 desplazamientos caian todos en multiplos de ese paso. Contrastado
    sobre los candidatos reales de cuatro partidas de lp85, aceptaba entre 14% y 26% MAS pares que
    el nulo circular exhaustivo (86->64, 636->528, 1032->734, 547->415), siempre en la direccion
    permisiva -- y el exhaustivo es BARATO (rotar enteros)."""
    exhaustivo = desplazamientos_del_nulo(160)
    assert exhaustivo == list(range(1, 160)), (
        "con una ventana corta el nulo tiene que ser EXHAUSTIVO, no una muestra"
    )

    grande = desplazamientos_del_nulo(MAX_OFFSETS_EXHAUSTIVOS * 10)
    assert len(grande) == len(set(grande))
    assert reduce(gcd, grande) == 1, (
        f"los offsets del nulo comparten un divisor: son una sub-red, no la ventana. {grande[:8]}"
    )


# -- el cambio de tamano de grilla --------------------------------------------------------------


def test_un_cambio_de_tamano_de_grilla_no_mata_al_detector():
    """`observar` hacia `return False` ANTES de actualizar las dimensiones, asi que quedaban
    latcheadas en las del primer paso y TODOS los pasos posteriores a un cambio de tamano se
    descartaban: el almacen no volvia a minar, ni a confirmar, ni a refutar. Y el cambio de tamano
    es justo lo que pasa al SUBIR DE NIVEL, que es el objetivo del BL. Medido en vivo sobre lp85:
    160 pasos registrados de ~199 ofrecidos, sin ninguna traza en el diagnostico."""
    historial = HistorialDeCambios()
    chico_a = [[FONDO] * 16 for _ in range(16)]
    chico_b = [list(fila) for fila in chico_a]
    chico_b[1][1] = COLOR_BOTON
    for _ in range(3):
        assert historial.observar("ACTION1", chico_a, chico_b)

    grande_a = [[FONDO] * 32 for _ in range(32)]
    grande_b = [list(fila) for fila in grande_a]
    grande_b[2][2] = COLOR_BOTON
    assert historial.observar("ACTION1", grande_a, grande_b), (
        "el primer paso del tablero nuevo se descarto"
    )
    for _ in range(5):
        assert historial.observar("ACTION1", grande_a, grande_b), (
            "el detector quedo muerto despues del cambio de tamano"
        )
    assert historial.reinicios_por_forma == 1
    assert historial.pasos == 6, "el historial tiene que contar los pasos del tablero NUEVO"


def test_el_diagnostico_reporta_los_ceros_que_no_son_ausencia_de_senal():
    """Un cero por bug y un cero honesto se leian igual: `diagnostico()` no exponia ni las
    transiciones descartadas por forma, ni los reinicios, ni las excepciones que el fail-open del
    llamador se tragaba en silencio."""
    almacen = AlmacenDeRelaciones()
    almacen.anotar_excepcion()
    almacen.anotar_excepcion()
    almacen.anotar_transicion_no_ofrecida()
    diagnostico = almacen.diagnostico()
    assert diagnostico["excepcionesDelLlamador"] == 2
    assert diagnostico["transicionesNoOfrecidas"] == 1
    assert "descartadosPorForma" in diagnostico
    assert "reiniciosPorForma" in diagnostico

    # LA CUENTA TIENE QUE CERRAR. `pasos` es la foto de la ultima mineria y `pasosRegistrados` el
    # conteo vivo: medido en lp85, el primero decia 160 sobre 200 transiciones ofrecidas y los 39
    # restantes parecian perdidos cuando estaban registrados -- otra forma de cero enganoso.
    vivo = AlmacenDeRelaciones()
    previa = _lienzo()
    ofrecidas = PASOS_MINIMOS_PARA_MINAR + 13
    for paso in range(ofrecidas):
        actual = [fila[:] for fila in previa]
        actual[2][2] = COLOR_BOTON if actual[2][2] == FONDO else FONDO
        vivo.observar("ACTION1", previa, actual)
        previa = actual
    completo = vivo.diagnostico()
    assert completo["pasosRegistrados"] == ofrecidas, (
        f"la cuenta de pasos no cierra: {completo}"
    )
    assert completo["pasos"] <= completo["pasosRegistrados"]


# -- el presupuesto de intervenciones y el piso de sub-meta -------------------------------------


def test_un_solo_exito_intervencional_no_habilita_una_submeta():
    """Con soporte alto el aporte observacional satura en +2,0 y cancela el prior -2,0, asi que UN
    exito dejaba la evidencia en 0,77 -- por encima del piso 0,55. En la corrida de lp85 habia
    relaciones con exitos=1, fallos=0, confirmacion "observacional" y evidencia 0,73/0,77, y
    `submetas()` devolvia 8. La regla del BL es 3 de 4, no 1."""
    apenas_probada = _relacion_de_prueba(soporte=1000, exitos=1)
    assert apenas_probada.evidencia >= PISO_DE_EVIDENCIA_PARA_SUBMETA, (
        "el escenario perdio su gracia: si no cruza el piso, no prueba nada"
    )
    assert apenas_probada.confirmacion == "observacional"

    almacen = AlmacenDeRelaciones()
    _partida(almacen)
    almacen.minar()
    relacion = almacen.relaciones()[0]
    _pasos_de_control(almacen, relacion, MIN_PASOS_DE_CONTROL + 2, cambia=False)
    almacen.registrar_intervencion(relacion, exito=True)
    assert relacion.evidencia >= PISO_DE_EVIDENCIA_PARA_SUBMETA
    assert almacen.submetas() == (), (
        "una sola repeticion exitosa mando una sub-meta al planner"
    )


PUERTA_LEJANA = ((44, 2), (44, 3), (45, 2), (45, 3))


def _partida_de_dos_puertas(almacen: AlmacenDeRelaciones) -> None:
    """El MISMO click abre DOS puertas lejanas entre si. Tres relaciones comparten disparador."""
    estado = False
    relleno = False
    previa = _lienzo()
    for paso in range(PASOS_TOTALES):
        aprieta = paso in PASOS_DE_BOTON
        if aprieta:
            estado = not estado
        else:
            relleno = not relleno
        actual = _lienzo()
        if estado:
            _pintar(actual, BOTON, COLOR_BOTON)
            _pintar(actual, PUERTA, COLOR_PUERTA)
            _pintar(actual, PUERTA_LEJANA, COLOR_PUERTA)
        if relleno:
            _pintar(actual, RELLENO, COLOR_BOTON)
        almacen.observar(
            "ACTION6" if aprieta else "ACTION1",
            previa,
            actual,
            coordenada=CLICK if aprieta else None,
        )
        previa = actual


def test_una_repeticion_juzga_a_todas_las_relaciones_del_mismo_disparador():
    """En lp85 las 24 intervenciones fueron el MISMO ACTION6 en (48,25), una detras de otra, porque
    seis relaciones compartian ese click. Repetir el mismo click seis veces no son seis
    experimentos: es UNO repetido, y se comio el 12% del presupuesto de acciones del gate."""
    almacen = AlmacenDeRelaciones()
    _partida_de_dos_puertas(almacen)
    almacen.minar()
    comparten = [r for r in almacen.relaciones() if r.coordenada == CLICK]
    assert len(comparten) >= 2, (
        f"el escenario perdio su gracia: {[r.resumen() for r in almacen.relaciones()]}"
    )

    assert almacen.sugerir_intervencion(["ACTION1", "ACTION6"]) == "ACTION6"
    pre = _lienzo()
    post = [list(fila) for fila in pre]
    for relacion in comparten:
        for y, x in relacion.destino.celdas:
            post[y][x] = COLOR_PUERTA
    almacen.observar("ACTION6", pre, post, coordenada=CLICK)

    juzgadas = [r for r in comparten if r.intentos > 0]
    assert len(juzgadas) == len(comparten), (
        "una sola repeticion tiene que dar veredicto a TODAS las relaciones de ese disparador: "
        f"{[(r.exitos, r.fallos) for r in comparten]}"
    )
    assert almacen.intervenciones_gastadas == 1


def test_el_presupuesto_no_se_gasta_muchas_veces_en_el_mismo_disparador():
    almacen = AlmacenDeRelaciones()
    _partida_de_dos_puertas(almacen)
    almacen.minar()
    pre = _lienzo()
    post = [list(fila) for fila in pre]
    post[2][20] = COLOR_BOTON
    for _ in range(MAX_INTENTOS_POR_DISPARADOR):
        assert almacen.sugerir_intervencion(["ACTION1", "ACTION6"]) == "ACTION6"
        almacen.observar("ACTION1", pre, post)  # la politica no la ejecuto
    assert almacen.sugerir_intervencion(["ACTION1", "ACTION6"]) is None, (
        "el mismo disparador se llevo mas repeticiones que las que puede dar un veredicto"
    )
    assert almacen.intervenciones_gastadas == MAX_INTENTOS_POR_DISPARADOR


# -- EL CONSUMIDOR: sin esto el gate no media la hipotesis del BL --------------------------------


#: Sub-meta ya confirmada, con su coordenada DENTRO de la grilla 8x8 de `make_frame`.
_SUBMETA_DE_PRUEBA = SubMeta(
    accion="ACTION6",
    coordenada=(3, 4),
    caja_origen=BoundingBox(min_y=0, min_x=0, max_y=1, max_x=1),
    caja_destino=BoundingBox(min_y=6, min_x=6, max_y=7, max_x=7),
    desfase=0,
    fuerza=1.5,
    soporte=9,
    evidencia=0.9,
    confirmacion="intervencional",
)


#: Pasos que hay que dejar correr antes de que la politica llegue a mirar las sub-metas: el libro
#: de aperturas ocupa las primeras decisiones y una macro puede cubrir hasta ocho pasos.
PASOS_DE_CALENTAMIENTO = 80


class _AlmacenConSubmeta(AlmacenDeRelaciones):
    """Almacen con UNA sub-meta ya confirmada. El contrato que se prueba es el de la POLITICA: que
    haga algo con lo que `submetas()` devuelve."""

    def submetas(self):  # type: ignore[override]
        return (_SUBMETA_DE_PRUEBA,)


def test_el_camino_al_planner_no_puede_volver_a_ser_codigo_muerto():
    """`grep -rn 'submetas' arc_agent/` fuera del propio almacen daba CERO: nadie llamaba a
    `submetas()` ni a `resumen()`. El unico cambio de comportamiento del entregable era GASTAR
    hasta 24 acciones por partida confirmando relaciones y despues TIRAR el resultado, asi que el
    gate de merge no midio "sirve la causa a distancia" sino "sirve gastar acciones en
    intervenciones cuyo resultado se descarta". Un empate medido asi no es evidencia."""
    fuente = (Path(__file__).resolve().parents[1] / "arc_agent" / "policy.py").read_text()
    assert "submetas()" in fuente, (
        "la politica dejo de consumir las sub-metas: el detector volvio a ser codigo muerto"
    )


def test_la_politica_ejecuta_una_submeta_confirmada_cuando_el_tablero_se_estanco():
    politica = ExplorationPolicy(create_seeded_random("submeta"))
    frame = make_frame(available_actions=(1, 2, 3, 6), grid_value=0)
    # El libro de aperturas manda en los primeros pasos (resuelve el mapeo boton->direccion, y ese
    # orden esta medido): la explotacion de sub-metas entra despues, igual que la intervencion.
    for _ in range(PASOS_DE_CALENTAMIENTO):
        politica.decide(frame)
    assert politica.explotaciones_de_submeta == 0, "sin sub-metas no puede haber explotacion"
    assert politica._pasos_sin_cambio >= PASOS_SIN_CAMBIO_PARA_SUBMETA  # noqa: SLF001

    politica._relaciones = _AlmacenConSubmeta()  # noqa: SLF001 -- se inyecta el contrato a probar
    decision = politica.decide(frame)
    assert decision.action is GameAction.ACTION6
    assert (decision.x, decision.y) == _SUBMETA_DE_PRUEBA.coordenada
    assert politica.explotaciones_de_submeta == 1
    assert "SUB-META" in decision.reasoning


def test_la_explotacion_de_submetas_tiene_presupuesto():
    politica = ExplorationPolicy(create_seeded_random("submeta-presupuesto"))
    politica._relaciones = _AlmacenConSubmeta()  # noqa: SLF001
    frame = make_frame(available_actions=(1, 2, 3, 6), grid_value=0)
    for _ in range(PASOS_DE_CALENTAMIENTO + 4 * MAX_EXPLOTACIONES_DE_SUBMETA):
        politica.decide(frame)
    assert politica.explotaciones_de_submeta == MAX_EXPLOTACIONES_DE_SUBMETA


def test_el_fail_open_de_la_politica_deja_de_ser_mudo():
    """Si `observar` lanzara en todos los pasos, el diagnostico devolvia el dict en ceros -- el
    MISMO reporte que "no hay senal"."""

    class _AlmacenRoto(AlmacenDeRelaciones):
        def observar(self, *args, **kwargs):  # type: ignore[override]
            raise RuntimeError("almacen roto a proposito")

    politica = ExplorationPolicy(create_seeded_random("fail-open"))
    politica._relaciones = _AlmacenRoto()  # noqa: SLF001
    frame = make_frame(available_actions=(1, 2, 3, 6), grid_value=0)
    for _ in range(4):
        politica.decide(frame)
    assert politica.relaciones_no_locales.diagnostico()["excepcionesDelLlamador"] > 0, (
        "el fail-open se trago las excepciones sin dejar rastro"
    )


def test_la_ventana_deslizante_no_se_confunde_con_un_tablero_nuevo():
    """El reinicio por cambio de tablero se detecta con el CONTADOR del historial, no con una caida
    de `pasos`: la ventana deslizante de `MAX_PASOS_RETENIDOS` tambien hace caer `pasos`
    (1.200 -> 800), y confundirlos tiraria el vocabulario entero cada 1.200 pasos -- justo en las
    partidas largas del entregable, que son las que fundan la curva de score de BL.21701."""
    almacen = AlmacenDeRelaciones()
    previa = [[FONDO] * 16 for _ in range(16)]
    for paso in range(MAX_PASOS_RETENIDOS + 60):
        actual = [fila[:] for fila in previa]
        actual[1][1] = COLOR_BOTON if actual[1][1] == FONDO else FONDO
        if paso % 3:
            actual[12][12] = COLOR_PUERTA if actual[12][12] == FONDO else FONDO
        almacen.observar("ACTION1", previa, actual)
        previa = actual
    diagnostico = almacen.diagnostico()
    assert diagnostico["reiniciosPorForma"] == 0, (
        f"la poda de la ventana se leyo como un tablero nuevo: {diagnostico}"
    )
    assert diagnostico["descartadosPorForma"] == 0


def test_no_se_gasta_una_intervencion_sin_condicion_de_control():
    """Medido en lp85 con el harness real: las 8 relaciones minadas terminaron REFUTADAS por su
    tasa base, y antes de eso se comieron 5 acciones del presupuesto intentando confirmarlas.
    Repetir una accion cuyo destino cambia solo -- o cuya tasa base ni siquiera esta estimada -- no
    es un experimento: es una accion tirada."""
    almacen = AlmacenDeRelaciones()
    _partida(almacen)
    almacen.minar()
    relacion = almacen.relaciones()[0]
    assert relacion.control_suficiente and not relacion.cambia_sola
    assert almacen.sugerir_intervencion(["ACTION1", "ACTION5"]) == "ACTION5", (
        "con control suficiente y tasa base baja, la intervencion SI tiene que gastarse"
    )

    # Sin tasa base estimada todavia: no hay con que comparar el resultado de la repeticion.
    sin_control = AlmacenDeRelaciones()
    _partida(sin_control)
    sin_control.minar()
    otra = sin_control.relaciones()[0]
    otra.pasos_de_control = 0
    otra.cambios_sin_accion = 0
    assert sin_control.sugerir_intervencion(["ACTION1", "ACTION5"]) is None, (
        "se gasto una accion en una relacion sin tasa base estimada"
    )

    # Y con el destino cambiando SOLO, la relacion ni siquiera sigue viva.
    que_cambia_sola = AlmacenDeRelaciones()
    _partida(que_cambia_sola)
    que_cambia_sola.minar()
    objetivo = que_cambia_sola.relaciones()[0]
    _pasos_de_control(que_cambia_sola, objetivo, 4 * MIN_PASOS_DE_CONTROL, cambia=True)
    assert objetivo.cambia_sola
    assert que_cambia_sola.sugerir_intervencion(["ACTION1", "ACTION5"]) is None, (
        "se gasto una accion en repetir algo cuyo efecto ocurre igual sin la accion"
    )
