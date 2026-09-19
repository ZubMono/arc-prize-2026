"""[arc-agi3-kaggle-agent/world_model/regiones_de_cambio] BL.21704 -- historial de cambios por
celda y agrupacion en REGIONES POR FIRMA DE CO-CAMBIO. Es la capa de percepcion sobre la que
`relaciones_no_locales.py` mina la causa a distancia (boton que abre puerta).

POR QUE ESTA GRANULARIDAD Y NO OTRA -- SALE DE UNA MEDICION, NO DE UNA OPINION. La etapa 1 de
BL.21704 corrio sobre 5.490 frames reales (103 partidas, 20 de los 25 juegos publicos) y midio las
tres granularidades posibles:

  * CELDA (la que proponia el brief): 4.513.968 pares con al menos una co-ocurrencia, 757.920 con
    soporte >= 5, y 518.658 sobreviven a Benjamini-Hochberg. Medio millon de "relaciones causales"
    no es un vocabulario, es ruido con formato: las celdas de un mismo objeto co-cambian
    perfectamente y el nulo de independencia por celda es falso por construccion. DESCARTADA.
  * COMPONENTE 8-CONEXA de la mascara activa acumulada: colapsa. Da 1 a 4 regiones por juego
    (ar25 UNA sola region de 1.664 celdas, cn04 dos con una de 2.286) y deja 5 de 20 juegos con
    CERO pares testeables. DESCARTADA.
  * FIRMA DE CO-CAMBIO (esta): agrupar las celdas activas por el CONJUNTO EXACTO de pasos en que
    cambiaron, y fusionar grupos con Jaccard >= 0,9. Da 32 a 253 regiones por juego, de 2 a 25
    celdas. Deduplica la redundancia intra-objeto que hace explotar el nivel celda y no colapsa
    como la adyacencia espacial. ELEGIDA.

EL PRE-FILTRO DE PASOS MASIVOS NO ES COSMETICA. Descartar las celdas que nunca cambian era lo unico
que el brief pedia; medido, lo que domina el ruido es OTRA cosa: un paso que cambia mas del 25% de
la grilla (RESET, transicion de nivel) hace co-ocurrir todo con todo y genera una clique gigante de
co-ocurrencia falsa. Fue el confound DOMINANTE en lp85 (49.883 pares espurios a nivel celda). Un
paso masivo no se registra: no aporta ni marginales ni co-ocurrencias.

EL AREA ACTIVA ES UN PISO, NO UNA CONSTANTE. El brief afirmaba "56 a 684 celdas activas por juego"
con >80% de grilla estatica en todos. Medido sobre el corpus completo (150-751 pasos por partida en
vez de los 20-45 de la sonda de BL.21590) el rango real es 64 a 2.318 (mediana 736), y CRECE con
los pasos observados: cn04 queda 56,6% activa, vc33 45,8%, bp35 42,3%. Por eso el modulo acota el
costo con `MAX_REGIONES` y con la ventana deslizante de `MAX_PASOS_RETENIDOS`, en vez de confiar en
que el pre-filtro de estaticas alcance.

Sin estado global, sin red y solo stdlib -- viaja al entregable de Kaggle.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Sequence

# Imports relativos en UNA sola linea a proposito: submission/build_agent.py los desmonta con el
# regex `^from \.\w* import .+$` y la forma con parentesis dejaria un `)` colgando en el entregable.
from .grid import BoundingBox, Grid, VolatilityMask, is_volatile_cell
from .object_geometry import Celda, agrupar_en_clusters, caja_de_celdas
from .object_mechanics import Mecanica, detectar_mecanica

#: Fraccion de la grilla por encima de la cual un paso se considera MASIVO y NO se registra. 0,25
#: es el corte medido: RESET y transiciones de nivel quedan afuera, y ningun evento de mecanica
#: local del corpus (cursor, toggle, aparicion) se acerca a ese volumen.
FRACCION_DE_PASO_MASIVO: Final[float] = 0.25

#: Similitud de Jaccard entre dos firmas de co-cambio a partir de la cual los dos grupos de celdas
#: se consideran la MISMA region. 0,9 y no 1,0 porque un objeto real pierde o gana una celda suelta
#: por oclusion en algunos pasos; 0,9 y no menos porque por debajo empiezan a fusionarse regiones
#: que solo comparten los pasos en que el tablero entero se movio.
JACCARD_DE_FUSION: Final[float] = 0.9

#: Tope de regiones retenidas por partida. El maximo MEDIDO fue 253 (cn04); 300 deja margen y a la
#: vez acota el enumerado de pares, que es cuadratico. Por encima se conservan las regiones con mas
#: celdas: las chicas son las que mas se parecen a ruido de una celda suelta.
MAX_REGIONES: Final[int] = 300

#: Separacion de Chebyshev minima entre los bounding boxes de dos regiones para llamar NO LOCAL a
#: su co-ocurrencia. La distancia SOLA no alcanza -- medido, sk48 genero 20.856 pares lag-1 con
#: traslaciones perfectamente legitimas -- por eso es condicion NECESARIA y no suficiente, y la
#: exclusion por detectores locales de `relaciones_no_locales.py` es obligatoria ademas de esta.
SEPARACION_CHEBYSHEV_MINIMA: Final[int] = 8

#: Cotas de COSTO de la agrupacion, no de estadistica. `MAX_PARTES_POR_FIRMA` acota en cuantos
#: pedazos no locales se puede partir UNA firma, y `MAX_GRUPOS_A_FUSIONAR` cuantos pedazos entran a
#: la fusion por Jaccard, que es cuadratica. Los dos conservan los grupos con MAS celdas: en un area
#: activa de 2.318 celdas (el maximo medido, cn04) sin estas cotas la pasada deja de ser barata, y
#: lo que se pierde son grupos de una o dos celdas sueltas -- el material del que esta hecho el
#: ruido. Sobre-fragmentar o descartar grupos chicos solo puede QUITAR sensibilidad, nunca inventar
#: un par: es el lado correcto en el que fallar.
MAX_PARTES_POR_FIRMA: Final[int] = 64
MAX_GRUPOS_A_FUSIONAR: Final[int] = 400

#: Pasos retenidos en la ventana. 751 fue la partida mas larga del corpus; 1200 la cubre entera con
#: margen y acota el ancho de los enteros que hacen de mascara de pasos. Al llegar al tope se podan
#: los `PASOS_PODADOS` mas viejos en vez de dejar de aprender: una relacion que aparece recien en
#: el paso 1.300 es exactamente la que un agente que ya exploro tiene que poder ver.
MAX_PASOS_RETENIDOS: Final[int] = 1200
PASOS_PODADOS: Final[int] = 400


@dataclass(frozen=True)
class RegionDeCambio:
    """Un grupo de celdas que cambian JUNTAS. `firma` es la mascara de bits de los pasos en que la
    region cambio (bit i = paso i de la ventana) y `pasos` su popcount -- el marginal que el nulo
    de `relaciones_no_locales.py` conserva."""

    id: int
    celdas: tuple[Celda, ...]
    caja: BoundingBox
    firma: int
    pasos: int


@dataclass(frozen=True)
class PasoObservado:
    """Lo que hace falta recordar de un paso REGISTRADO: que accion lo produjo, DONDE (si la accion
    lleva coordenada) y que cajas del tablero quedan explicadas por los detectores LOCALES de
    `object_mechanics.py`.

    LA COORDENADA NO ES UN EXTRA. Una accion de click no se repite repitiendo su nombre: el mismo
    ACTION6 en otra celda es otra intervencion. Sin este campo, la confirmacion activa de una
    relacion disparada por clicks esta condenada a fallar siempre -- medido en vivo sobre lp85, con
    las 8 relaciones retenidas refutadas en su primera repeticion por ese motivo y no porque fueran
    falsas. El modulo no sabe QUE accion lleva coordenada (eso es vocabulario del wire): sabe que
    algunas la traen y que esas solo se pueden repetir con ella."""

    accion: str
    cajas_locales: tuple[BoundingBox, ...]
    coordenada: tuple[int, int] | None = None


def _union_de_cajas(a: BoundingBox, b: BoundingBox) -> BoundingBox:
    return BoundingBox(
        min_x=min(a.min_x, b.min_x),
        min_y=min(a.min_y, b.min_y),
        max_x=max(a.max_x, b.max_x),
        max_y=max(a.max_y, b.max_y),
    )


def cajas_explicadas_por_locales(mecanica: Mecanica | None) -> tuple[BoundingBox, ...]:
    """Cajas del tablero cuyo cambio YA tiene nombre en el vocabulario local.

    Son dos familias, y la segunda es la que importa para el control negativo del objeto que se
    traslada: (1) la caja de cada cluster de cambios, y (2) la UNION de la caja ORIGEN y la caja
    DESTINO de cada traslacion detectada. Un objeto que se mueve deja dos regiones cambiadas lejos
    entre si -- la que abandona y la que ocupa -- y sin la union esa traslacion se leeria como una
    relacion causal a distancia entre su celda vieja y la nueva."""
    if mecanica is None:
        return ()
    cajas: list[BoundingBox] = []
    for cluster in mecanica.clusters:
        if _puede_contener_un_par_no_local(cluster.caja):
            # PODA EXACTA, no heuristica: una caja que mide menos de
            # SEPARACION_CHEBYSHEV_MINIMA en los dos ejes no puede contener dos regiones separadas
            # por ese hueco, asi que guardarla solo agrega trabajo al filtro que la consulta. Los
            # clusters chicos -- que son casi todos -- salen aca.
            cajas.append(cluster.caja)
        traslacion = cluster.traslacion
        if traslacion is None:
            continue
        origen = BoundingBox(
            min_x=traslacion.min_x,
            min_y=traslacion.min_y,
            max_x=traslacion.min_x + traslacion.ancho - 1,
            max_y=traslacion.min_y + traslacion.alto - 1,
        )
        destino = BoundingBox(
            min_x=origen.min_x + traslacion.dx,
            min_y=origen.min_y + traslacion.dy,
            max_x=origen.max_x + traslacion.dx,
            max_y=origen.max_y + traslacion.dy,
        )
        cajas.append(_union_de_cajas(origen, destino))
    return tuple(cajas)


def _puede_contener_un_par_no_local(caja: BoundingBox) -> bool:
    ancho = caja.max_x - caja.min_x
    alto = caja.max_y - caja.min_y
    return max(ancho, alto) - SEPARACION_CHEBYSHEV_MINIMA >= 0


def _contenida(interior: BoundingBox, exterior: BoundingBox) -> bool:
    return (
        interior.min_x >= exterior.min_x
        and interior.max_x <= exterior.max_x
        and interior.min_y >= exterior.min_y
        and interior.max_y <= exterior.max_y
    )


def separacion_chebyshev(a: BoundingBox, b: BoundingBox) -> int:
    """Distancia de Chebyshev entre dos cajas (0 si se tocan o se solapan)."""
    hueco_y = max(0, a.min_y - b.max_y, b.min_y - a.max_y)
    hueco_x = max(0, a.min_x - b.max_x, b.min_x - a.max_x)
    return max(hueco_y, hueco_x)


def _separar_por_localidad(celdas: list[Celda]) -> list[list[Celda]]:
    """Parte un grupo de celdas en sub-grupos que NO estan separados por un hueco no local.

    Se apoya en la MISMA segmentacion 8-conexa que usa el vocabulario local
    (`agrupar_en_clusters`) y despues vuelve a unir los clusters que quedaron a menos de
    `SEPARACION_CHEBYSHEV_MINIMA`: un objeto real se fragmenta en varios clusters por un hueco de
    dos celdas y partirlo ahi seria inventar regiones. Lo que nunca se une es lo que esta lejos."""
    clusters = agrupar_en_clusters(celdas)
    if len(clusters) <= 1:
        return clusters
    # Los mas grandes primero (y por posicion ante empate, para que sea determinista): son los que
    # absorben a los chicos. Si una firma se dispersa en mas de `MAX_PARTES_POR_FIRMA` pedazos, se
    # conservan los mayores -- un enjambre de celdas sueltas con la misma firma es ruido, y ademas
    # es el unico caso donde esta pasada dejaria de ser barata.
    clusters.sort(key=lambda c: (-len(c), min(c)))
    del clusters[MAX_PARTES_POR_FIRMA:]
    partes: list[list[Celda]] = []
    cajas: list[BoundingBox] = []
    for cluster in clusters:
        caja = caja_de_celdas(cluster)
        for i, otra in enumerate(cajas):
            if separacion_chebyshev(caja, otra) < SEPARACION_CHEBYSHEV_MINIMA:
                partes[i].extend(cluster)
                cajas[i] = _union_de_cajas(otra, caja)
                break
        else:
            partes.append(list(cluster))
            cajas.append(caja)
    return partes


def particionar_pares(
    regiones: Sequence[RegionDeCambio],
) -> tuple[list[tuple[int, int]], list[list[int]]]:
    """Un SOLO recorrido de los pares de regiones que devuelve las dos particiones a la vez: los
    pares NO LOCALES (el denominador honesto de la multiplicidad) y la lista de adyacencia de los
    CERCANOS (el grafo sobre el que se decide si dos regiones lejanas estan unidas por una cadena
    de cambios). Son complementarios por definicion, y con 300 regiones el doble bucle es 45.000
    comparaciones: hacerlo dos veces era pagar el mismo precio dos veces."""
    pares: list[tuple[int, int]] = []
    adyacencia: list[list[int]] = [[] for _ in regiones]
    for i in range(len(regiones)):
        caja_i = regiones[i].caja
        for j in range(i + 1, len(regiones)):
            if separacion_chebyshev(caja_i, regiones[j].caja) - SEPARACION_CHEBYSHEV_MINIMA >= 0:
                pares.append((i, j))
            else:
                adyacencia[i].append(j)
                adyacencia[j].append(i)
    return pares, adyacencia


def regiones_contiguas(regiones: Sequence[RegionDeCambio]) -> list[list[int]]:
    """Solo la adyacencia de `particionar_pares`. Se conserva por claridad de lectura."""
    return particionar_pares(regiones)[1]


def componentes_por_paso(
    regiones: Sequence[RegionDeCambio], adyacencia: list[list[int]], pasos: int
) -> list[dict[int, int]]:
    """Para cada paso, en que COMPONENTE DE CAMBIO CONTIGUO cayo cada region activa.

    POR QUE ESTO ES NECESARIO Y NO UN LUJO. Medido en vivo sobre lp85 (200 acciones, harness real),
    las 8 relaciones que el detector confirmaba eran pares de celdas de la MISMA fila (fila 26,
    x = 17, 20, 23, 26, ..., separadas de a 3) disparadas por el MISMO click: una franja contigua
    que se repinta entera. Pasaban la no localidad porque dos celdas de esa franja separadas por 9
    columnas superan el Chebyshev >= 8, y pasaban la confirmacion intervencional porque repetir el
    click vuelve a repintar la franja -- una tautologia, no una causa a distancia. La distancia
    entre los EXTREMOS no distingue una causa a distancia de una franja larga; lo que la distingue
    es el HUECO: en un boton que abre una puerta no hay nada que cambie en el medio, y en una
    franja que se repinta hay cambios cada 3 celdas todo a lo largo.

    Dos regiones activas en el mismo paso caen en la misma componente si existe una cadena de
    regiones activas ESE PASO donde cada eslabon esta a menos de `SEPARACION_CHEBYSHEV_MINIMA` del
    siguiente. La componente se calcula UNA vez por paso y no por candidato: el costo es lineal en
    las activaciones, no cuadratico en los pares."""
    activas_por_paso: list[list[int]] = [[] for _ in range(pasos)]
    for indice, region in enumerate(regiones):
        pendiente = region.firma
        while pendiente:
            bit = pendiente & -pendiente
            paso = bit.bit_length() - 1
            if paso < pasos:
                activas_por_paso[paso].append(indice)
            pendiente ^= bit

    salida: list[dict[int, int]] = []
    for activas in activas_por_paso:
        en_paso = set(activas)
        componente: dict[int, int] = {}
        siguiente = 0
        for raiz in activas:
            if raiz in componente:
                continue
            componente[raiz] = siguiente
            pila = [raiz]
            while pila:
                actual = pila.pop()
                for vecino in adyacencia[actual]:
                    if vecino in en_paso and vecino not in componente:
                        componente[vecino] = siguiente
                        pila.append(vecino)
            siguiente += 1
        salida.append(componente)
    return salida


class HistorialDeCambios:
    """Acumula, paso a paso, QUE celdas cambiaron y BAJO QUE ACCION. Una instancia por partida.

    No decide nada: es el sustrato del que `relaciones_no_locales.py` saca regiones, marginales y
    co-ocurrencias. Se mantiene aparte a proposito -- la mineria se recalcula cada tantos pasos y
    la observacion tiene que ser barata en TODOS los pasos."""

    def __init__(self) -> None:
        self._alto = 0
        self._ancho = 0
        self._cambios_por_celda: dict[Celda, int] = {}
        self._pasos: list[PasoObservado] = []
        self._descartados_por_masivos = 0
        self._descartados_por_forma = 0
        self._reinicios_por_forma = 0

    @property
    def pasos(self) -> int:
        """Pasos REGISTRADOS en la ventana (los masivos no cuentan: no ocurrieron para el conteo)."""
        return len(self._pasos)

    @property
    def descartados_por_masivos(self) -> int:
        return self._descartados_por_masivos

    @property
    def descartados_por_forma(self) -> int:
        """Transiciones descartadas porque `pre` y `post` no son comparables entre si. Se expone
        para que el diagnostico pueda distinguir un cero por AUSENCIA DE SENAL de un cero por
        transiciones que nunca entraron -- un cero por bug y un cero honesto se leian igual."""
        return self._descartados_por_forma

    @property
    def reinicios_por_forma(self) -> int:
        """Veces que la grilla cambio de tamano y el historial se reinicio (tipicamente, un cambio
        de NIVEL). Ver `observar`: antes de BL.21704-v2 el primer cambio de tamano dejaba el
        detector MUERTO por el resto de la partida."""
        return self._reinicios_por_forma

    @property
    def celdas_activas(self) -> int:
        return len(self._cambios_por_celda)

    def accion_de(self, paso: int) -> str:
        return self._pasos[paso].accion

    def coordenada_de(self, paso: int) -> tuple[int, int] | None:
        return self._pasos[paso].coordenada

    def observar(
        self,
        accion: str,
        pre: Sequence[Sequence[int]] | Grid,
        post: Sequence[Sequence[int]] | Grid,
        mecanica: Mecanica | None = None,
        mask: VolatilityMask | None = None,
        coordenada: tuple[int, int] | None = None,
    ) -> bool:
        """Registra la transicion `pre -> post` producida por `accion` (en `coordenada`, si la
        accion lleva uno).

        Devuelve True si el paso quedo REGISTRADO y False si se descarto (grillas incomparables o
        paso masivo). `mecanica` se recibe ya calculada porque la politica la computa una vez por
        paso para el modelo de mundo y correr `detectar_mecanica` de nuevo seria un SEGUNDO
        detector sobre la misma transicion; si no llega, se calcula aca con el detector REAL --
        nunca con una aproximacion propia."""
        alto = len(pre)
        if alto == 0 or len(post) != alto or len(pre[0]) != len(post[0]):
            self._descartados_por_forma += 1
            return False
        ancho = len(pre[0])
        if self._alto and (alto != self._alto or ancho != self._ancho):
            # LA GRILLA CAMBIO DE TAMANO: es OTRO TABLERO, tipicamente un cambio de NIVEL. Las
            # firmas de co-cambio acumuladas hablan de coordenadas que ya no existen, asi que se
            # reinicia el historial y se sigue aprendiendo sobre el tablero nuevo.
            #
            # ANTES ESTO MATABA AL DETECTOR. La version anterior hacia `return False` sin tocar
            # `self._alto`, de modo que las dimensiones quedaban latcheadas en las del PRIMER paso
            # y TODOS los pasos posteriores al cambio de tamano se descartaban: el almacen no
            # volvia a minar, ni a confirmar, ni a refutar. Y como el objetivo del BL es subir de
            # NIVEL -- el evento que justamente cambia el tablero --, el detector se apagaba
            # exactamente en la mitad de la partida donde la senal importaba. Medido en vivo sobre
            # lp85: 160 pasos registrados de ~199 ofrecidos, con las ~38 restantes desaparecidas
            # por esta via y sin ninguna traza en el diagnostico.
            self._reinicios_por_forma += 1
            self._cambios_por_celda = {}
            self._pasos = []
        self._alto, self._ancho = alto, ancho

        cambios: list[Celda] = []
        tope = int(FRACCION_DE_PASO_MASIVO * alto * ancho)
        for y in range(alto):
            fila_pre = pre[y]
            fila_post = post[y]
            for x in range(ancho):
                if fila_pre[x] != fila_post[x] and not is_volatile_cell(mask, y, x):
                    cambios.append((y, x))
            if len(cambios) > tope:
                # Corte temprano: en cuanto se supera el tope el paso ya esta descartado y seguir
                # recorriendo la grilla es trabajo puro. Ver el docstring del modulo: un RESET
                # registrado genera una clique de co-ocurrencia que se come toda la senal.
                self._descartados_por_masivos += 1
                return False

        if mecanica is None:
            mecanica = detectar_mecanica([list(f) for f in pre], [list(f) for f in post], mask)

        indice = len(self._pasos)
        bit = 1 << indice
        for celda in cambios:
            self._cambios_por_celda[celda] = self._cambios_por_celda.get(celda, 0) | bit
        self._pasos.append(
            PasoObservado(
                accion=accion,
                cajas_locales=cajas_explicadas_por_locales(mecanica),
                coordenada=coordenada,
            )
        )
        if len(self._pasos) >= MAX_PASOS_RETENIDOS:
            self._podar()
        return True

    def _podar(self) -> None:
        """Ventana deslizante: descarta los `PASOS_PODADOS` mas viejos. Las celdas que quedan sin
        ningun cambio en la ventana salen del area activa -- es el pre-filtro de estaticas aplicado
        de nuevo sobre la ventana vigente, no una sola vez al principio."""
        self._pasos = self._pasos[PASOS_PODADOS:]
        supervivientes: dict[Celda, int] = {}
        for celda, firma in self._cambios_por_celda.items():
            recortada = firma >> PASOS_PODADOS
            if recortada:
                supervivientes[celda] = recortada
        self._cambios_por_celda = supervivientes

    def regiones(self) -> list[RegionDeCambio]:
        """Agrupa el area activa en regiones por FIRMA DE CO-CAMBIO (ver docstring del modulo).

        Tres etapas, y la del medio NO estaba en el diseno original -- es una correccion obligada,
        no un refinamiento: (1) agrupacion exacta por firma, que ya deduplica casi toda la
        redundancia intra-objeto porque las celdas de un mismo objeto comparten la mascara de pasos
        bit a bit; (2) SEPARACION POR LOCALIDAD dentro de cada firma; (3) fusion de grupos con
        Jaccard >= `JACCARD_DE_FUSION`, que absorbe al objeto que pierde una celda suelta por
        oclusion, y que TAMPOCO puede cruzar la frontera de no localidad.

        POR QUE LA ETAPA 2 ES OBLIGATORIA. Un boton y la puerta que abre co-cambian EXACTAMENTE en
        los mismos pasos: esa es la definicion del fenomeno que este modulo existe para detectar. Y
        justamente por eso comparten la firma bit a bit y la etapa 1 los mete en UNA sola region --
        con lo cual no queda ningun par que testear y el detector se come su propia senal. Una
        region es un OBJETO; dos grupos de celdas separados por mas de
        `SEPARACION_CHEBYSHEV_MINIMA` no son un objeto por muy correlacionados que esten. El
        invariante que sale de aca es que NINGUNA region abarca un hueco no local."""
        por_firma: dict[int, list[Celda]] = {}
        for celda, firma in self._cambios_por_celda.items():
            por_firma.setdefault(firma, []).append(celda)

        # Orden por popcount descendente y despues por la firma: determinista y con las regiones
        # mas activas primero, que son las que absorben a las parecidas en la fusion.
        grupos: list[tuple[int, list[Celda]]] = []
        for firma, miembros in sorted(
            por_firma.items(), key=lambda par: (-par[0].bit_count(), par[0])
        ):
            for parte in _separar_por_localidad(miembros):
                grupos.append((firma, parte))
        grupos.sort(key=lambda par: (-len(par[1]), min(par[1])))
        del grupos[MAX_GRUPOS_A_FUSIONAR:]

        firmas: list[int] = []
        celdas: list[list[Celda]] = []
        cajas: list[BoundingBox] = []
        for firma, miembros in grupos:
            caja = caja_de_celdas(miembros)
            destino = -1
            for i, otra in enumerate(firmas):
                if separacion_chebyshev(caja, cajas[i]) >= SEPARACION_CHEBYSHEV_MINIMA:
                    # La fusion por Jaccard nunca cruza la frontera de no localidad: si lo hiciera,
                    # reintroduciria por la puerta de atras el colapso que la etapa 2 evita.
                    continue
                interseccion = (firma & otra).bit_count()
                union = (firma | otra).bit_count()
                if union and interseccion / union >= JACCARD_DE_FUSION:
                    destino = i
                    break
            if destino >= 0:
                firmas[destino] |= firma
                celdas[destino].extend(miembros)
                cajas[destino] = _union_de_cajas(cajas[destino], caja)
            else:
                firmas.append(firma)
                celdas.append(list(miembros))
                cajas.append(caja)

        indices = sorted(range(len(firmas)), key=lambda i: (-len(celdas[i]), sorted(celdas[i])[0]))
        salida: list[RegionDeCambio] = []
        for nuevo_id, i in enumerate(indices[:MAX_REGIONES]):
            miembros = sorted(celdas[i])
            salida.append(
                RegionDeCambio(
                    id=nuevo_id,
                    celdas=tuple(miembros),
                    caja=caja_de_celdas(miembros),
                    firma=firmas[i],
                    pasos=firmas[i].bit_count(),
                )
            )
        return salida

    def pares_no_locales(self, regiones: list[RegionDeCambio]) -> list[tuple[int, int]]:
        """Pares de regiones separadas por al menos `SEPARACION_CHEBYSHEV_MINIMA` celdas entre sus
        bounding boxes. Es el DENOMINADOR HONESTO de la correccion por multiplicidad: se testean
        todos, co-ocurran o no."""
        pares: list[tuple[int, int]] = []
        for i in range(len(regiones)):
            caja_i = regiones[i].caja
            for j in range(i + 1, len(regiones)):
                if separacion_chebyshev(caja_i, regiones[j].caja) >= SEPARACION_CHEBYSHEV_MINIMA:
                    pares.append((i, j))
        return pares

    def explicado_por_locales(self, paso: int, caja_a: BoundingBox, caja_b: BoundingBox) -> bool:
        """True si en ese paso ALGUNA caja explicada por los detectores locales contiene a las DOS
        regiones -- o sea, si lo que parece causa a distancia es en realidad un unico cluster o una
        unica traslacion ya nombrada por el vocabulario local."""
        for caja in self._pasos[paso].cajas_locales:
            if _contenida(caja_a, caja) and _contenida(caja_b, caja):
                return True
        return False

    def acciones_de(self, mascara: int) -> dict[str, int]:
        """Histograma de acciones sobre los pasos marcados en `mascara`. La accion de un paso es la
        que PRODUJO esa transicion, asi que el histograma es directamente la evidencia de que la
        co-activacion esta ligada a UN boton."""
        conteo: dict[str, int] = {}
        pendiente = mascara
        while pendiente:
            bit = pendiente & -pendiente
            indice = bit.bit_length() - 1
            accion = self._pasos[indice].accion
            conteo[accion] = conteo.get(accion, 0) + 1
            pendiente ^= bit
        return conteo

    def pasos_de(self, mascara: int) -> list[int]:
        """Indices de los pasos marcados en `mascara`, en orden ascendente."""
        indices: list[int] = []
        pendiente = mascara
        while pendiente:
            bit = pendiente & -pendiente
            indices.append(bit.bit_length() - 1)
            pendiente ^= bit
        return indices
