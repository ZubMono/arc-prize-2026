"""[arc-agi3-kaggle-agent/tests/test_bl21744_alcanzabilidad_de_niveles] GUARD: ningun mundo del
banco parametrico puede quedar SIN nivel 1 alcanzable.

POR QUE EXISTE. Durante meses el banco tuvo el objetivo clavado a 54 celdas exactas del avatar en
linea recta vertical, y como el avatar solo se traslada de a `magnitud` celdas, 19 de los 25 mundos
no podian llegar al nivel 1 hicieran lo que hicieran. Nadie lo vio porque el banco se usaba para
comparar A contra B: los dos lados daban 0 en los mismos mundos y el empate se leia como "la
palanca no paga" en vez de "el banco no puede medir esto". El defecto era INVISIBLE a toda
medicion comparativa, y por eso hace falta un test que mire la GEOMETRIA y no el resultado.

El test recorre los 25 mundos con BFS sobre la reticula real de cada uno. No verifica a ojo ni
consulta una lista de mundos buenos: reconstruye la alcanzabilidad desde las paredes, la magnitud y
las firmas medidas de cada boton. Si manana se agrega un mundo 26 con una magnitud que no cierra,
este test lo dice.

EL ORACULO NO PUEDE HACER TRAMPA (correccion de BL.21744, 2026-08-19). La primera version de este
guard resolvia la ruta de click con `_click_en(entorno, entorno._ox, entorno._oy)`: leia las
coordenadas PRIVADAS del objetivo y acertaba en UNA accion. Un oraculo asi no verifica
alcanzabilidad -- verifica que el motor cobre el nivel cuando le dan la respuesta --, y su veredicto
seguiria en verde aunque el objetivo dejara de dibujarse en el frame, o sea aunque ninguna politica
del mundo pudiera encontrarlo. Ahora los tres oraculos corren detras de `_SoloElFrame`, un
envoltorio que expone `reset`/`step` y hace explotar cualquier lectura de atributo privado: la
posicion del avatar y la del objetivo se LEEN DEL FRAME, igual que las lee una politica. Lo que el
oraculo si tiene permitido saber es el MAPEO DE ACCIONES (que boton mueve y con que magnitud): eso
es exactamente lo que una politica aprende y lo que el banco mide en `juegosConMapeoResuelto`; lo
que no puede saber es donde esta escondido el objetivo.

Y CUESTA LO QUE DICE COSTAR. El guard no solo exige que el oraculo llegue: cuenta las PULSACIONES
que gasto y las compara contra `PASOS_RESERVADOS_PARA_LLEGAR`. Antes la rama de click no verificaba
costo alguno (solo distancia >= 8 del avatar), que es la nocion DEBIL de alcanzabilidad que este
mismo proyecto rechaza en `test_estar_en_la_reticula_no_es_lo_mismo_que_poder_llegar...`.

QUE MIDE LA POLITICA DE HOY, y esto es un dato del AGENTE y no del banco (medido 2026-08-19,
`ExplorationPolicy`, semilla "lazo", 40 pasos, los 25 mundos): 10 niveles, TODOS en mundos de
movimiento o repintado, y `clicksProductivos` = 0 en 25 de 25. Los 11 mundos de RUTA_CLICK dan cero
porque la politica gasta sus clicks FUERA del tablero: 36 de 40 en (63, 0), la celda del HUD que
cambia en todos los pasos, y el resto en la fila 60 (la pared de abajo). El objetivo es una celda de
color unico dibujada en el frame y el oraculo la encuentra y la clickea en una accion, asi que la
via existe y esta verificada aca abajo: el cero es una carencia MEDIDA de la politica -- no clickea
nunca dentro del tablero -- y no un mundo mudo. `test_los_mundos_de_click_discriminan_entre_dos_politicas`
fija esa diferencia para que no se lea como ruido."""
from __future__ import annotations

from collections import deque

import pytest

from arc_agent.types import ActionDecision, GameAction

from tests.support.geometria_de_mundos import (
    ALTO_TABLERO,
    ANCHO,
    CELDAS_POR_FIRMA,
    COLOR_OBJETIVO,
    INICIO_DEL_AVATAR,
    MAGNITUD_MAXIMA_MEDIDA,
    MAGNITUD_MINIMA_MEDIDA,
    PASOS_RESERVADOS_PARA_LLEGAR,
    PROFUNDIDAD_DEL_OBJETIVO,
    RUTA_CLICK,
    RUTA_MOVIMIENTO,
    RUTA_REPINTADO,
    alcanzables_desde,
    celdas_de_repintado,
    costo_esperado_por_movimiento,
    es_piso,
    orden_de_repintado,
    posicion_del_objetivo,
    profundidad_maxima,
    ruta_de_nivel,
    trasladores,
)
from tests.support import mundos_medidos
from tests.support.oraculo_observable import (
    SoloElFrame,
    alcanza_el_nivel,
    buscar_color,
    tope_de_pulsaciones,
)
from tests.support.lazo_cerrado import PASOS_POR_PARTIDA, jugar
from tests.support.mundos_medidos import MUNDOS, MUNDOS_POR_NOMBRE, EntornoMedido

#: Los seis mundos que una POLITICA podia llevar al nivel 1 con la geometria vieja (medido con BFS
#: sobre la tabla de mundos de entonces). Son seis y no ocho porque tr87 y bp35 tenian la celda en
#: su reticula pero solo por las flechas de RUIDO, que no se pueden dirigir -- ver
#: `test_estar_en_la_reticula_no_es_lo_mismo_que_poder_llegar_y_el_guard_exige_lo_segundo`. Se
#: dejan escritos para que el test pueda demostrar que el arreglo no fue "empujar el problema a
#: otro lado": si el conjunto alcanzable volviera a ser este, el arreglo se habria perdido.
ALCANZABLES_ANTES_DE_BL21744 = frozenset({"ar25", "ka59", "dc22", "cn04", "g50t", "sk48"})


@pytest.mark.parametrize("mundo", MUNDOS, ids=lambda m: m.nombre)
def test_todo_mundo_tiene_una_ruta_de_nivel_declarada(mundo) -> None:
    assert ruta_de_nivel(mundo) in (RUTA_MOVIMIENTO, RUTA_CLICK, RUTA_REPINTADO)


@pytest.mark.parametrize("mundo", MUNDOS, ids=lambda m: m.nombre)
def test_bfs_el_nivel_1_es_alcanzable_en_los_25_mundos(mundo) -> None:
    """EL GUARD. BFS dentro del test, sobre la geometria real, mundo por mundo."""
    objetivo = posicion_del_objetivo(mundo)
    assert es_piso(objetivo), f"{mundo.nombre}: el objetivo cayo sobre pared o fuera del tablero"
    assert objetivo != INICIO_DEL_AVATAR, f"{mundo.nombre}: objetivo regalado encima del avatar"
    ruta = ruta_de_nivel(mundo)

    if ruta == RUTA_MOVIMIENTO:
        profundidades = alcanzables_desde(mundo)
        assert objetivo in profundidades, (
            f"{mundo.nombre}: el objetivo {objetivo} NO esta en la reticula del mundo "
            f"(magnitud {mundo.magnitud}); con esa geometria `niveles` no puede subir nunca"
        )
        movimientos = profundidades[objetivo]
        assert 1 <= movimientos <= profundidad_maxima(mundo)
        costo = costo_esperado_por_movimiento(mundo) * movimientos
        assert costo <= PASOS_RESERVADOS_PARA_LLEGAR, (
            f"{mundo.nombre}: llegar cuesta {costo:.0f} pulsaciones esperadas, mas que las "
            f"{PASOS_RESERVADOS_PARA_LLEGAR} reservadas dentro de los {PASOS_POR_PARTIDA} de la "
            "partida: alcanzable en el papel, inalcanzable en la practica"
        )
    elif ruta == RUTA_CLICK:
        assert 6 in mundo.acciones, f"{mundo.nombre}: ruta de click sin ACTION6 disponible"
        distancia = abs(objetivo[0] - INICIO_DEL_AVATAR[0]) + abs(objetivo[1] - INICIO_DEL_AVATAR[1])
        assert distancia >= PROFUNDIDAD_DEL_OBJETIVO, f"{mundo.nombre}: objetivo pegado al avatar"
        # Y ESTA DIBUJADO. Sin esto la ruta de click es alcanzable solo para quien conozca la
        # celda de antemano -- que es la trampa que hacia el oraculo viejo leyendo `entorno._ox`.
        frame = EntornoMedido(mundo, seed="dibujado").reset()
        visible = buscar_color(frame, COLOR_OBJETIVO)
        assert visible == objetivo or mundo.menu, (
            f"{mundo.nombre}: el objetivo esta en {objetivo} pero el frame muestra {visible}. Una "
            "celda que no se dibuja no la puede encontrar ninguna politica: buscarla a ciegas "
            f"cuesta hasta {ANCHO * ALTO_TABLERO} clicks contra {PASOS_POR_PARTIDA} de partida"
        )
    else:
        celdas = celdas_de_repintado(mundo)
        assert celdas > 0, f"{mundo.nombre}: sin mecanica de repintado, no tiene via de nivel"
        indice = orden_de_repintado().index(objetivo)
        pulsaciones = indice // celdas + 1
        assert pulsaciones <= PASOS_RESERVADOS_PARA_LLEGAR, (
            f"{mundo.nombre}: el barrido tarda {pulsaciones} pulsaciones en cubrir el objetivo"
        )


@pytest.mark.parametrize("mundo", MUNDOS, ids=lambda m: m.nombre)
def test_el_motor_sube_de_nivel_de_verdad_por_la_ruta_que_declara(mundo) -> None:
    """El BFS dice que hay camino; esto verifica que el MOTOR lo cobra. Un oraculo que conoce el
    mundo lo recorre en linea directa -- es la cota superior de lo que una politica podria lograr,
    y si ni el oraculo sube de nivel, ninguna politica va a poder."""
    aciertos, panel = _semillas_que_suben_de_nivel(mundo)
    minimo = _semillas_minimas(mundo)
    assert aciertos >= minimo, (
        f"{mundo.nombre}: ruta {ruta_de_nivel(mundo)} declarada, pero el motor solo conto un nivel "
        f"en {aciertos} de {panel} semillas (minimo exigido {minimo})"
    )
    # Y ADEMAS LE CUESTA LO QUE DICE COSTAR. Llegar "en algun momento" es la nocion DEBIL de
    # alcanzabilidad que este proyecto rechaza: el nivel 1 tiene que entrar en el presupuesto que
    # el banco reserva para llegar, dentro de la partida de PASOS_POR_PARTIDA acciones.
    gastadas = _pulsaciones_del_oraculo(mundo)
    assert gastadas <= tope_de_pulsaciones(mundo), (
        f"{mundo.nombre}: el oraculo gasto {gastadas} pulsaciones y el tope de su ruta es "
        f"{tope_de_pulsaciones(mundo)}: alcanzable en el papel, inalcanzable en la practica"
    )


def test_el_arreglo_amplio_el_conjunto_alcanzable_y_no_lo_movio_de_lugar() -> None:
    """Los 25, y en particular TODOS los que antes eran inganables."""
    alcanzables = {
        m.nombre for m in MUNDOS if _semillas_que_suben_de_nivel(m)[0] >= _semillas_minimas(m)
    }
    assert len(alcanzables) == len(MUNDOS) == 25, sorted(
        {m.nombre for m in MUNDOS} - alcanzables
    )
    assert alcanzables > ALCANZABLES_ANTES_DE_BL21744


def test_el_unico_mundo_que_paga_el_nivel_en_varianza_es_el_de_ruido_puro() -> None:
    """Frontera explicita: tr87 es el unico mundo cuya UNICA mecanica medida es ruido sub-objeto
    ("mutuamente contradictorias... nunca es un mapeo"). Ahi ninguna politica puede dirigir el
    movimiento, asi que el nivel llega o no llega por azar y el banco NO puede atribuirle merito a
    una politica. Queda escrito para que nadie lea su varianza como senal -- y para que el dia que
    aparezca un segundo mundo asi, el test obligue a decidirlo a conciencia."""
    de_azar = {m.nombre for m in MUNDOS if _es_estocastico(m)}
    assert de_azar == {"tr87"}, sorted(de_azar)


def test_el_objetivo_clavado_de_antes_estaba_fuera_de_la_reticula_de_la_mayoria() -> None:
    """LA DEMOSTRACION DEL DEFECTO, dentro del test y no en un comentario.

    Hasta BL.21744 el objetivo de los 25 mundos estaba clavado en `(ALTO_TABLERO - 4, 3)` = (57, 3),
    a 54 celdas exactas del avatar en vertical. Este test recorre esa MISMA celda con el mismo BFS y
    muestra que para la enorme mayoria de los mundos no pertenece a su reticula: no estaba lejos,
    estaba FUERA. Si alguien vuelve a clavar el objetivo en una constante, este numero lo delata."""
    clavado = (ALTO_TABLERO - 4, 3)
    fuera = [m.nombre for m in MUNDOS if clavado not in alcanzables_desde(m)]
    assert len(fuera) >= 16, sorted(fuera)
    # Y la geometria de hoy no deja ni uno solo afuera.
    assert [m.nombre for m in MUNDOS if posicion_del_objetivo(m) not in _alcanzable_o_clickeable(m)] == []


def test_estar_en_la_reticula_no_es_lo_mismo_que_poder_llegar_y_el_guard_exige_lo_segundo() -> None:
    """LA AMBIGUEDAD QUE HAY QUE DEJAR CERRADA, porque de ella dependen dos numeros distintos.

    "Cuantos mundos podian alcanzar el nivel 1 con la geometria vieja" admite DOS respuestas y las
    dos son correctas segun que se pregunte:

      - ALCANZABLE TOPOLOGICAMENTE (la celda pertenece a la reticula del mundo): tambien entran
        tr87 y bp35, cuyos unicos trasladores son las flechas de RUIDO. Un BFS a secas los cuenta.
      - ALCANZABLE POR UNA POLITICA (existe una secuencia de botones que una politica puede ELEGIR
        para llegar): tr87 y bp35 quedan afuera, porque el ruido dispara con probabilidad 0,07 y
        ademas sortea la direccion: la politica no manda.

    Con la tabla de mundos previa a BL.21744 eso daba 8 y 6 respectivamente -- y el "6" del
    diagnostico original era el numero que importa, porque un gate mide POLITICAS. Este test fija
    la distincion sobre la tabla de HOY para que no se vuelva a confundir un numero con el otro, y
    verifica que la separacion entre los dos conjuntos es de orden de magnitud, no de matiz."""
    clavado = (ALTO_TABLERO - 4, 3)
    en_la_reticula = {m.nombre for m in MUNDOS if clavado in alcanzables_desde(m)}
    dirigibles = {m.nombre for m in MUNDOS if clavado in _alcanzables_dirigibles(m)}

    solo_por_azar = en_la_reticula - dirigibles
    assert solo_por_azar == {"tr87", "bp35"}, sorted(solo_por_azar)
    assert dirigibles < en_la_reticula

    # Y "solo por azar" no es una distincion de laboratorio: para esos dos, llegar cuesta mas de
    # QUINCE VECES el presupuesto entero de la partida aun regalandoles que los pasos en la
    # direccion equivocada no retrocedan.
    for nombre in sorted(solo_por_azar):
        mundo = next(m for m in MUNDOS if m.nombre == nombre)
        movimientos = alcanzables_desde(mundo)[clavado]
        esperado = movimientos * costo_esperado_por_movimiento(mundo)
        assert esperado > 15 * PASOS_POR_PARTIDA, (
            f"{nombre}: {esperado:.0f} pulsaciones esperadas contra {PASOS_POR_PARTIDA} de "
            "presupuesto -- si esto deja de ser cierto, la clasificacion hay que rehacerla"
        )

    # El guard de arriba exige la nocion FUERTE: que el oraculo LLEGUE, no que exista un camino.
    assert not _es_estocastico(next(m for m in MUNDOS if m.nombre == "bp35"))


def _alcanzables_dirigibles(mundo) -> dict:
    """BFS igual al de `alcanzables_desde` pero SOLO con los trasladores que una politica puede
    elegir: sin las flechas de RUIDO, cuya direccion la sortea el mundo y no el agente."""
    movimientos = [t for t in trasladores(mundo) if not t[2]]
    profundidades = {INICIO_DEL_AVATAR: 0}
    if not movimientos:
        return profundidades
    cola = deque([INICIO_DEL_AVATAR])
    while cola:
        y, x = cola.popleft()
        for (dy, dx), magnitud, _azar in movimientos:
            destino = (y + dy * magnitud, x + dx * magnitud)
            if destino in profundidades or not es_piso(destino):
                continue
            profundidades[destino] = profundidades[(y, x)] + 1
            cola.append(destino)
    return profundidades


def _alcanzable_o_clickeable(mundo) -> set:
    if ruta_de_nivel(mundo) == RUTA_MOVIMIENTO:
        return set(alcanzables_desde(mundo))
    return {c for c in orden_de_repintado()}


def test_la_geometria_del_tablero_no_cambio_de_tamano() -> None:
    """El tamano 64x64 no es cosmetico: por debajo de 1024 celdas la sintesis del modelo de mundo
    corre una busqueda estructural que en juego real NUNCA corre."""
    assert (ALTO_TABLERO, ANCHO) == (61, 64)
    assert set(CELDAS_POR_FIRMA.values()) == {34, 185, 12}


# ── oraculos: recorren el mundo MIRANDO EL FRAME, como una politica ───────────────────────────


#: Panel de semillas del oraculo. Fijas: el guard tiene que dar SIEMPRE el mismo veredicto.
SEMILLAS_DEL_ORACULO = ("bl21744", "s1", "s2", "s3", "s4", "s5", "s6")




def _es_estocastico(mundo) -> bool:
    """El nivel de este mundo depende del AZAR: su ruta es el movimiento y ningun boton lo traslada
    de forma dirigible. bp35 tiene las mismas flechas de ruido pero sube de nivel por CLICK, que si
    es dirigible, asi que no entra aca."""
    if ruta_de_nivel(mundo) != RUTA_MOVIMIENTO:
        return False
    movimientos = trasladores(mundo)
    return bool(movimientos) and all(azar for _d, _m, azar in movimientos)


def _semillas_minimas(mundo) -> int:
    """Cuantas semillas del panel tienen que subir de nivel para dar el mundo por alcanzable.

    TODAS cuando el mundo es dirigible: si el oraculo conoce el camino y no llega, la geometria
    esta rota. MAYORIA cuando la unica mecanica medida es ruido no dirigible (tr87): ahi el nivel
    llega por azar y exigir 7 de 7 seria exigirle determinismo a un mundo que la sonda midio
    explicitamente como no determinista."""
    if _es_estocastico(mundo):
        return len(SEMILLAS_DEL_ORACULO) // 2 + 1
    return len(SEMILLAS_DEL_ORACULO)


def _semillas_que_suben_de_nivel(mundo) -> tuple[int, int]:
    aciertos = sum(1 for semilla in SEMILLAS_DEL_ORACULO if _oraculo_alcanza(mundo, semilla)[0])
    return aciertos, len(SEMILLAS_DEL_ORACULO)


def _oraculo_alcanza(mundo, semilla: str) -> tuple[bool, int]:
    """`(llego, pulsaciones)`. El oraculo vive en `tests/support/oraculo_observable.py` y corre
    detras de `SoloElFrame`: lee el frame, nunca el estado privado del entorno."""
    return alcanza_el_nivel(mundo, semilla, lambda m, s: EntornoMedido(m, seed=s))


def _pulsaciones_del_oraculo(mundo) -> int:
    """Lo que le costo al oraculo llegar en la PEOR de las semillas del panel. Es la magnitud que
    la primera version del guard no cobraba en la ruta de click."""
    return max(_oraculo_alcanza(mundo, s)[1] for s in SEMILLAS_DEL_ORACULO)


def _decision(boton: str, x: int | None = None, y: int | None = None) -> ActionDecision:
    return ActionDecision(action=GameAction[boton], x=x, y=y)


# ── lo que la refutacion del 2026-08-19 dejo verificado ───────────────────────────────────────


@pytest.mark.parametrize("mundo", MUNDOS, ids=lambda m: m.nombre)
def test_el_oraculo_no_puede_leer_el_estado_privado_del_entorno(mundo) -> None:
    """EL GUARD DEL GUARD. Rojo contra el oraculo anterior, que resolvia la ruta de click con
    `_click_en(entorno, entorno._ox, entorno._oy)`: `SoloElFrame` levanta `AttributeError` ante
    cualquier lectura que una politica no podria hacer. Verificado corriendo el oraculo VIEJO
    (`git show 2e171e5470:...`) detras de este mismo envoltorio: explota en los 25 mundos."""
    envoltorio = SoloElFrame(EntornoMedido(mundo, seed="sin-trampa"))
    assert envoltorio.reset() is not None
    for privado in ("_ox", "_oy", "_x", "_y", "_tablero", "niveles", "en_menu", "ruta"):
        with pytest.raises(AttributeError):
            getattr(envoltorio, privado)


@pytest.mark.parametrize("mundo", MUNDOS, ids=lambda m: m.nombre)
def test_la_magnitud_de_cada_mundo_esta_dentro_de_lo_que_la_sonda_midio(mundo) -> None:
    """LA TABLA DE MUNDOS TAMBIEN SE VERIFICA, no solo la regla de colocacion.

    Antes de esto, mutar la magnitud de ls20 de 5 a 7, la de ar25 de 3 a 11 o la de sk48 de 6 a 13
    dejaba la suite entera en verde: las tres aserciones de la rama de movimiento se DERIVAN de
    `_objetivo_por_movimiento`, asi que no pueden contradecirla. Estas dos si son independientes:
    el rango sale de la medicion publicada ("2 a 6 celdas", mas el selector de tu93 en 1) y la
    profundidad de la reticula se cuenta con BFS. Un mundo con magnitud 59, que desde (3,3) deja un
    solo movimiento posible en todo el tablero, cae por la segunda."""
    trasladan = [t for t in trasladores(mundo) if not t[2]]
    if not trasladan:
        assert mundo.magnitud == 0 or ruta_de_nivel(mundo) != RUTA_MOVIMIENTO
        return
    assert MAGNITUD_MINIMA_MEDIDA <= mundo.magnitud <= MAGNITUD_MAXIMA_MEDIDA, (
        f"{mundo.nombre}: magnitud {mundo.magnitud} fuera del rango medido "
        f"[{MAGNITUD_MINIMA_MEDIDA}, {MAGNITUD_MAXIMA_MEDIDA}]. La sonda midio de 2 a 6 celdas por "
        "pulsacion (tu93, el selector, es el 1): un numero afuera no reproduce ninguna medicion"
    )
    profundidades = alcanzables_desde(mundo)
    assert max(profundidades.values()) >= PROFUNDIDAD_DEL_OBJETIVO, (
        f"{mundo.nombre}: con magnitud {mundo.magnitud} su reticula llega a profundidad "
        f"{max(profundidades.values())} y el objetivo tiene que quedar a {PROFUNDIDAD_DEL_OBJETIVO} "
        "movimientos. Un mundo que no puede plantear ese problema no mide ninguna politica"
    )


class _PoliticaQueClickeaLoQueCambia:
    """Politica de PRUEBA que reproduce la falla MEDIDA de la politica de dev en los mundos de
    click: clickea la celda que cambio respecto del frame anterior. En este banco eso es siempre el
    HUD o la barra de progreso -- las filas 61 a 63, FUERA del tablero --, que es exactamente donde
    `ExplorationPolicy` tiro 36 de sus 40 clicks el 2026-08-19."""

    def __init__(self) -> None:
        self._anterior: tuple[tuple[int, ...], ...] | None = None

    def decide(self, frame):
        grilla = tuple(frame.frame[0])
        objetivo = (ANCHO - 1, 0)
        if self._anterior is not None:
            for y, (fila, previa) in enumerate(zip(grilla, self._anterior)):
                cambiada = [x for x, (v, a) in enumerate(zip(fila, previa)) if v != a]
                if cambiada:
                    objetivo = (y, cambiada[0])
                    break
        self._anterior = grilla
        return _decision("ACTION6", objetivo[1], objetivo[0])


def test_los_mundos_de_click_discriminan_entre_dos_politicas() -> None:
    """LA COLUMNA DE CLICK MIDE POLITICA, y esto lo demuestra con dos politicas.

    Es la respuesta medida a "el banco sigue mudo en los 11 mundos de click": no esta mudo, esta
    midiendo un cero REAL. Una politica que mira el frame y clickea el objetivo cobra el nivel en
    una accion; una que clickea "lo que cambio" -- la falla medida de la politica de dev, 36 de 40
    clicks en el HUD -- no cobra ninguno. Si algun dia las dos midieran lo mismo, la columna dejo de
    discriminar y estos mundos hay que rehacerlos."""
    de_click = [m for m in MUNDOS if ruta_de_nivel(m) == RUTA_CLICK]
    assert len(de_click) == 11, sorted(m.nombre for m in de_click)

    vidente = sum(1 for m in de_click if _oraculo_alcanza(m, "discriminacion")[0])
    ciega = sum(
        int(jugar(m, lambda _rng: _PoliticaQueClickeaLoQueCambia(), 40, "discriminacion")["niveles"])
        for m in de_click
    )

    assert vidente == len(de_click), (
        f"la politica que LEE el frame cobro nivel en {vidente} de {len(de_click)} mundos de click: "
        "si no llega a todos, la via de click no esta disponible para ninguna politica"
    )
    assert ciega == 0, (
        f"la politica que clickea lo que cambia cobro {ciega} niveles: era el contraejemplo, y sin "
        "el la columna no demuestra que discrimine"
    )


@pytest.mark.parametrize(
    "nombre,boton", [("cn04", "ACTION5"), ("sp80", "ACTION3"), ("cd82", "ACTION3")]
)
def test_el_barrido_no_direccional_sigue_produciendo_diff_toda_la_partida(nombre, boton) -> None:
    """EL MUNDO NO PUEDE APAGARSE A MITAD DE PARTIDA.

    La medicion que el banco reproduce dice que el diff del boton no direccional "se repite
    pulsacion tras pulsacion". Con un color destino fijo el barrido se apagaba solo al dejar el
    tablero uniforme: medido antes de esta correccion, cn04/ACTION5 (bloque de 185 celdas) no
    producia mas cambio a partir de la pulsacion 21 y sp80/cd82 (34 celdas) a partir de la 108,
    dentro de los mismos 200 pasos de la partida. A partir de ahi el boton era indistinguible de uno
    muerto y `accionesEnBotonesMuertos` -- la columna que decide -- contaba mal el mundo."""
    mundo = MUNDOS_POR_NOMBRE[nombre]
    entorno = EntornoMedido(mundo, "barrido")
    for _ in range(20):
        if not entorno.en_menu:
            break
        entorno.step(_decision("ACTION6", None, None))
    con_diff = 0
    for _ in range(PASOS_POR_PARTIDA):
        antes = entorno.productivos
        entorno.step(_decision(boton))
        con_diff += int(entorno.productivos > antes)
    assert con_diff == PASOS_POR_PARTIDA, (
        f"{nombre}/{boton}: solo {con_diff} de {PASOS_POR_PARTIDA} pulsaciones cambiaron el "
        "tablero. El resto de la partida el mundo miente sobre su propia mecanica"
    )
