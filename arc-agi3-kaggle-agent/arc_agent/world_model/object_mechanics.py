"""[arc-agi3-kaggle-agent/world_model/object_mechanics] BL.21561 -- analizador de mecanicas
OBJETO-CENTRICO. REEMPLAZA a `propose_all_steps` como el analizador que alimenta
`TransitionMemory.record_observation`: en vez de preguntar "que funcion grilla->grilla explica el
par", pregunta "que le paso a los OBJETOS". Puerto de
arc-agi-runner/src/worldModel/objectMechanics.ts.

POR QUE. Medido sobre 1.569 pasos reales de ARC-AGI-3, el DSL global confirmo regla en 253 pasos y
las 253 son la IDENTIDAD -- cero reglas no triviales. Las causas son estructurales, no de
presupuesto: `propose_translate` usa el bbox GLOBAL del foreground, que las paredes del tablero
fijan; `propose_recolor` exige un mapping color->color consistente en TODA la grilla, y un objeto
que se mueve pide mapear fondo->jugador y jugador->fondo a la vez; flood fill y conditional recolor
exigen UN color origen y UNO destino sobre el diff, y un movimiento tiene dos.

QUE DETECTA (parametrico sobre objetos y deltas, NUNCA sobre game_id):
1. traslacion -- una region acotada se movio (dy,dx) conservando su contenido: cursor/jugador.
2. recoloreo -- un grupo de celdas cambio de color en el lugar: toggle/pintado.
3. aparicion / desaparicion -- un grupo aparecio sobre el fondo o volvio al fondo.
Los detectores 4 (marco/HUD estatico) y 5 (contador monotono) son de EPISODIO: mechanics_memory.py.

BL.21741 -- EL SILENCIO TIENE QUE DECIR POR QUE. Medido sobre el corpus persistido de subidas de
nivel (14 eventos, 8 transiciones distintas, 6 juegos), `firma_de_mecanica` valia "desconocida" en
14 de 14: la percepcion objeto-centrica era ciega EXACTAMENTE en el instante que decide el score, y
las 8 transiciones distintas eran indistinguibles entre si. Dos causas, las dos arregladas aca:
  a) `_mecanica_vacia("desconocida")` se devolvia tanto cuando el analisis miro y no supo nombrar
     como cuando NO MIRO (por el tope de celdas, o por grillas de forma distinta). Ahora esos dos
     casos tienen tipo propio -- `sobreElTope` y `formaIncompatible` -- y el silencio deja de
     leerse como quietud.
  b) la firma global colapsaba a "desconocida" en cuanto los clusters no eran todos del mismo tipo,
     y una subida de nivel es SIEMPRE una mezcla. Para ese caso la firma ahora es COMPUESTA: el
     desglose por tipo de cluster (ver `firma_compuesta`).
Resultado medido tras el cambio: 7 firmas distintas sobre 8 transiciones (antes 1), sin ninguna
firma inestable -- con el caveat de que solo 4 de las 8 transiciones tienen mas de una captura con
que contrastarse (ver `mechanics_signature`).

LO QUE ESTE BL NO PROBO (correccion, con los numeros al lado). El cierre original vendio
"vc33:nivel1 y vc33:nivel2 comparten firma" como la evidencia de que la firma GENERALIZA en vez de
memorizar. Es falso en las dos mitades: (a) la firma que comparten es `compuesta:desconocida=1`, un
solo cluster que el detector NO supo nombrar -- compartir el silencio no es generalizar; (b) son dos
niveles del MISMO juego. De los 28 pares de transiciones, 26 son entre juegos DISTINTOS y NINGUNO
comparte firma. Con 6 juegos salen 6 familias de firma disjuntas, que es compatible con memorizar la
escena de cada mundo. La cuenta honesta: 6 de 8 transiciones con firma propia informativa, 2 con la
firma del silencio, 0 de 26 pares entre juegos con firma compartida. Ver
`mechanics_signature.es_firma_de_silencio`, que existe para que la distincion no se pierda otra vez
en un `startswith`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .grid import BoundingBox, Grid, VolatilityMask, is_volatile_cell
from .object_geometry import Celda, agrupar_en_clusters, caja_de_celdas
from .object_geometry import cobertura_de_objetos, fondo_local
from .object_geometry import traslacion_de_objeto_entero

# Area maxima del bbox de un cluster de cambios que se analiza. Por encima, el "objeto" seria medio
# tablero y la hipotesis de traslacion rigida no describe nada.
MAX_AREA_CAJA_DE_CAMBIOS: Final[int] = 4096

# Tope de celdas cambiadas analizadas en una transicion. Por encima, `detectar_mecanica` NO ANALIZA
# y lo dice con un tipo propio (`sobreElTope`), nunca con `desconocida`.
#
# EL NUMERO SALE DE UN EXPERIMENTO (BL.21741), no de ser redondo. 2048 -- la mitad exacta de una
# grilla 64x64 -- venia de BL.21561 sin medicion detras y sin ningun test que lo fijara. Medido con
# `scripts/medir_tope_de_mecanica.py` sobre el corpus persistido (8 transiciones de subida de nivel
# distintas), cuantas quedan con firmas DIFERENTES entre si y cuantas quedan CALLADAS -- con firma
# que no nombra NINGUNA mecanica, contada con `es_firma_de_silencio`:
#   tope 1024 -> 3 firmas distintas | 6 transiciones calladas
#   tope 2048 -> 5 firmas distintas | 4 calladas   <- el corte historico
#   tope 3072 -> 7 firmas distintas | 3 calladas
#   tope 4096 -> 7 firmas distintas | 2 calladas   <- este
# ESTA TABLA NO ES UN COMENTARIO QUE PUEDA DRIFTEAR: la mide `mediciones/BL21741_tope_de_mecanica.json`
# y `test_la_tabla_del_tope_escrita_aca_es_la_medida` la parsea de ESTE texto y la compara. La
# version anterior decia "3072 -> 1 callada" y "4096 -> 0 calladas", numeros producidos por un
# contador de silencio que no veia `compuesta:desconocida=N`.
# POR QUE 4096 Y NO 3072, con la cuenta corregida: empatan en firmas distintas y 4096 calla una
# transicion menos. Ninguno de los dos "salva" a las dos transiciones de vc33: con la grilla entera
# mirada, el detector las MIRA y sigue sin saber nombrarlas (`compuesta:desconocida=1`), o sea que
# el tope ya no es lo que las calla y subirlo mas no compra nada. Efecto colateral honesto: con el
# tope en el area de la grilla, `sobreElTope` es INALCANZABLE en ARC-AGI-3 (harian falta 4097 celdas
# de 4096) -- queda como guard estructural para grillas de otro tamano, no como camino vivo.
# COSTO MEDIDO (272 pares consecutivos del corpus, minimo de 5 repeticiones interleaved, separado
# por CAMINO DE CODIGO): el sobrecosto NO esta repartido. 266 de los 272 pares recorren el mismo
# camino con los dos topes y miden igual (3,72s contra 3,72-3,76s: la diferencia es ruido); los 6
# que cruzan el corte pasan de 0,003s a 0,51-0,72s, o sea 85 ms por par con la maquina tranquila y
# 120 ms con load 30 (dos corridas, misma forma). Amortizado: 1,9-2,8 ms/paso. El paso caro es
# EXACTAMENTE el de la subida de nivel -- +85-120 ms sobre un costo por accion de 0,154-0,202s
# (+40-60%), UNA vez por nivel, contra un presupuesto ENTREGADO de 8,0 h (`reloj_presupuesto.py`;
# las 9 h son el techo duro de Kaggle, no lo que se reparte). La version anterior publicaba
# "mediana 0,001554 -> 0,002938" y "+4 ms por paso": la mediana no puede casi duplicarse porque
# cambiaron 6 de 272 pares -- esa columna era ruido de la maquina, no senal del tope.
MAX_CELDAS_CAMBIADAS: Final[int] = 4096

# `k` del enunciado: tamano maximo (en celdas) de la caja que puede ser un OBJETO. Los cursores de
# los juegos medidos miden 4-27 celdas.
MAX_TAMANO_OBJETO: Final[int] = 256

# Evidencia minima (0-1) para aceptar una hipotesis de traslacion. Se mide de dos formas
# independientes y alcanza con UNA (ver `_traslacion_de_cluster`).
MIN_EVIDENCIA_DE_OBJETO: Final[float] = 0.5

TIPOS_DE_MECANICA: Final[tuple[str, ...]] = (
    "sinCambio",
    "traslacion",
    "recoloreo",
    "aparicion",
    "desaparicion",
    "desconocida",
    # BL.21741 -- los dos casos de "NO MIRE", que hasta este BL se confundian con "mire y no
    # encontre". El silencio del detector se leia como quietud: `caracterizar_completados.py`
    # tenia que mirar un booleano aparte (`sobre_el_tope_de_mecanica`) para saber de cual de los
    # dos silencios se trataba, y ninguna capa aguas abajo lo hacia.
    "sobreElTope",
    "formaIncompatible",
)

# Los tipos que significan "NO MIRE" -- el detector no analizo los clusters, ni bien ni mal.
# FUENTE UNICA (BL.21741) para cualquier consumidor que distinga "no paso nada" de "no se".
TIPOS_DE_NO_MIRE: Final[tuple[str, ...]] = ("sobreElTope", "formaIncompatible")

# El unico tipo cuyo `celdas_cambiadas` NO ES UNA MEDICION sino la ausencia de una.
#
# POR QUE ESTA SEPARADO DE `TIPOS_DE_NO_MIRE` (BL.21741). Los dos tipos de "no mire" no son
# igual de ciegos: `sobreElTope` no analizo los CLUSTERS, pero conto las celdas antes de rendirse
# y ese conteo es exacto -- un consumidor que solo mira el tamano del cambio (la firma
# `cambioDeEscena` de `IncognitaDeMecanica`) sigue teniendo dato bueno y clasificar ahi como
# "desconocida" PERDERIA informacion. `formaIncompatible`, en cambio, sale con `celdas_cambiadas
# == 0` sin haber contado nada, y ese cero es indistinguible del cero legitimo de `sinCambio`:
# los dos consumidores que deciden si una accion es INERTE (`_evento_sin_traslacion` e
# `IncognitaDeMecanica._clasificar`, en direction_beliefs.py) preguntaban `celdas_cambiadas == 0`,
# o sea que "ni pude comparar las grillas" alimentaba la evidencia de que el boton no hace nada
# -- la inferencia OPUESTA a la correcta. Nombrar el tipo en `detectar_mecanica` no alcanzaba si
# aguas abajo nadie lo leia.
TIPO_SIN_MEDICION: Final[str] = "formaIncompatible"

# El tipo de cluster que el detector MIRO y no supo nombrar. Constante y no literal porque la firma
# compuesta lo deletrea DENTRO de la etiqueta (`compuesta:desconocida=1`) y hay consumidores que
# necesitan reconocerlo ahi adentro -- ver `mechanics_signature.es_firma_de_silencio`.
TIPO_SIN_NOMBRAR: Final[str] = "desconocida"


@dataclass(frozen=True)
class Traslacion:
    """La caja `[min_y..min_y+alto-1] x [min_x..min_x+ancho-1]` de `pre` reaparece intacta en
    `post` desplazada (dy,dx). `cobertura` y `relleno` son las dos evidencias de que lo que se
    movio es un objeto y no un recorte del fondo."""

    dy: int
    dx: int
    min_y: int
    min_x: int
    alto: int
    ancho: int
    cobertura: float
    relleno: float


@dataclass(frozen=True)
class CambioDeColor:
    desde: int
    hasta: int
    celdas: int


@dataclass(frozen=True)
class MecanicaDeCluster:
    tipo: str
    celdas: int
    caja: BoundingBox
    traslacion: Traslacion | None
    cambio_de_color: CambioDeColor | None


@dataclass(frozen=True)
class Mecanica:
    tipo: str
    celdas_cambiadas: int
    clusters: list[MecanicaDeCluster]
    traslacion_principal: Traslacion | None
    cambio_de_color_principal: CambioDeColor | None


def _mecanica_vacia(tipo: str, celdas_cambiadas: int) -> Mecanica:
    return Mecanica(
        tipo=tipo,
        celdas_cambiadas=celdas_cambiadas,
        clusters=[],
        traslacion_principal=None,
        cambio_de_color_principal=None,
    )


def _misma_forma(a: Grid, b: Grid) -> bool:
    if len(a) != len(b):
        return False
    for y in range(len(a)):
        if len(a[y]) != len(b[y]):
            return False
    return len(a) > 0 and len(a[0]) > 0


def detectar_mecanica(
    pre: Grid,
    post: Grid,
    mask: VolatilityMask | None = None,
    max_tamano_objeto: int = MAX_TAMANO_OBJETO,
    min_evidencia: float = MIN_EVIDENCIA_DE_OBJETO,
    max_celdas_cambiadas: int | None = None,
) -> Mecanica:
    """Detecta que le paso a los objetos entre `pre` y `post`, ignorando las celdas volatiles
    (BL.21558: la barra de progreso avanza una celda por paso y no es mecanica de tablero). Nunca
    lanza: ante dos grillas que ni siquiera se pueden comparar devuelve `formaIncompatible`, y por
    encima de `MAX_CELDAS_CAMBIADAS` devuelve `sobreElTope` sin analizar (BL.21741). Ninguno de los
    dos es `desconocida`, que significa "mire los clusters y no supe nombrarlos".

    `max_celdas_cambiadas` mueve el tope SOLO en esta llamada: existe para que el experimento del
    tope y el fixture de paridad no tengan que parchear la constante del modulo y restaurarla en un
    `finally` (que es lo que hacia `medir_tope_de_mecanica.py`). None = la constante."""
    if not _misma_forma(pre, post):
        # BL.21741: NO es "desconocida". "Desconocida" significa "mire los clusters y no supe
        # nombrarlos"; esto significa "ni siquiera pude comparar las dos grillas".
        return _mecanica_vacia("formaIncompatible", 0)

    cambios: list[Celda] = []
    for y in range(len(pre)):
        fila = pre[y]
        fila_post = post[y]
        for x in range(len(fila)):
            if fila[x] != fila_post[x] and not is_volatile_cell(mask, y, x):
                cambios.append((y, x))
    if not cambios:
        return _mecanica_vacia("sinCambio", 0)
    tope = MAX_CELDAS_CAMBIADAS if max_celdas_cambiadas is None else max_celdas_cambiadas
    if len(cambios) > tope:
        # BL.21741: tipo PROPIO. Devolver "desconocida" aca hacia que "no mire porque cambio
        # demasiado" fuera indistinguible de "mire y no encontre" -- y como la transicion de nivel
        # es siempre el frame que mas cambia, el detector callaba justo donde se decide el score.
        return _mecanica_vacia("sobreElTope", len(cambios))

    clusters = [
        _clasificar_cluster(pre, post, grupo, max_tamano_objeto, min_evidencia)
        for grupo in agrupar_en_clusters(cambios)
    ]
    con_traslacion = [c for c in clusters if c.traslacion is not None]
    if not con_traslacion and len(clusters) > 1:
        # Un objeto que se mueve MENOS que su propio ancho deja dos regiones cambiadas separadas
        # por la parte que se solapa y no cambio. Son dos clusters y ninguno se explica solo, pero
        # la union si. Respaldo y no primera opcion: fusionar de entrada juntaria eventos
        # independientes, y sobre las partidas reales el analisis por cluster ya resuelve todo.
        fusionado = _clasificar_cluster(pre, post, cambios, max_tamano_objeto, min_evidencia)
        if fusionado.traslacion is not None:
            clusters = [fusionado]
            con_traslacion = [fusionado]

    # BL.21853 -- ULTIMO respaldo: el objeto ENTERO. Las dos vias de arriba despejan la caja `R` del
    # bbox del CLUSTER (solo ven al objeto que se mueve menos que su propio ancho) y la acotan por
    # AREA (256): un objeto de 153 celdas en una caja de 17x17 no entra aunque el objeto sea chico.
    # Medido sobre 7.258 transiciones: 146 (2,01%) son traslaciones rigidas CARDINALES de objetos
    # de 53 y 153 celdas que hoy caen en `desconocida`. Esas 146 salen de DOS juegos de los 27 con
    # transiciones (re86 77, cn04 69): es una medicion en dos escenas, no una propiedad del corpus.
    # Va TERCERA a proposito: si una de las dos vias anteriores ya explico el paso, esta ni se
    # llama. ALCANCE EXACTO de eso, que no es "solo toca `desconocida`": estructuralmente tambien
    # puede reetiquetar un paso cuyo tipo global era `recoloreo`/`aparicion`/`desaparicion`. Sobre
    # el corpus NO paso -- las 146 salen las 146 de `desconocida` -- pero la guarda no lo impide.
    traslacion_entera: Traslacion | None = None
    if not con_traslacion:
        fondo_del_cambio = fondo_local(pre, cambios, caja_de_celdas(cambios))
        entera = traslacion_de_objeto_entero(pre, post, cambios, fondo_del_cambio, mask)
        if entera is not None:
            dy, dx, objeto = entera
            caja_obj = caja_de_celdas(objeto)
            alto_obj = caja_obj.max_y - caja_obj.min_y + 1
            ancho_obj = caja_obj.max_x - caja_obj.min_x + 1
            # `cobertura` y `relleno` NO se miden igual que en `_traslacion_de_cluster`: alla son
            # las dos evidencias que rompen la ambiguedad objeto/hueco, aca esa ambiguedad ya la
            # rompio la RECONSTRUCCION exacta, que es mas fuerte que las dos.
            # `cobertura` es la fraccion de la caja que ocupa el objeto; `relleno` es 1.0 porque la
            # reconstruccion exigio el fondo en cada celda desalojada -- salvo las VOLATILES, que
            # saltea: el 1.0 es exacto solo fuera de la mascara.
            traslacion_entera = Traslacion(
                dy=dy,
                dx=dx,
                min_y=caja_obj.min_y,
                min_x=caja_obj.min_x,
                alto=alto_obj,
                ancho=ancho_obj,
                cobertura=len(objeto) / (alto_obj * ancho_obj),
                relleno=1.0,
            )

    con_traslacion.sort(
        key=lambda c: (
            -(c.traslacion.alto * c.traslacion.ancho),
            c.traslacion.min_y,
            c.traslacion.min_x,
        )
    )

    if con_traslacion or traslacion_entera is not None:
        tipo = "traslacion"
    else:
        tipos = {c.tipo for c in clusters}
        tipo = clusters[0].tipo if len(tipos) == 1 else "desconocida"

    con_color = sorted(
        (c for c in clusters if c.cambio_de_color is not None),
        key=lambda c: -c.cambio_de_color.celdas,
    )

    return Mecanica(
        tipo=tipo,
        celdas_cambiadas=len(cambios),
        clusters=clusters,
        traslacion_principal=(
            con_traslacion[0].traslacion if con_traslacion else traslacion_entera
        ),
        cambio_de_color_principal=con_color[0].cambio_de_color if con_color else None,
    )


def _clasificar_cluster(
    pre: Grid,
    post: Grid,
    grupo: list[Celda],
    max_tamano_objeto: int,
    min_evidencia: float,
) -> MecanicaDeCluster:
    caja = caja_de_celdas(grupo)
    traslacion = _traslacion_de_cluster(
        pre, post, grupo, caja, max_tamano_objeto, min_evidencia
    )
    if traslacion is not None:
        return MecanicaDeCluster(
            tipo="traslacion",
            celdas=len(grupo),
            caja=caja,
            traslacion=traslacion,
            cambio_de_color=None,
        )

    # Sin traslacion: el cluster entero tiene que ser UN solo par (desde -> hasta) para llamarse
    # mecanica. Dos pares distintos son un cambio compuesto que este analizador no pretende
    # nombrar -- decir "desconocida" es informacion; inventar un nombre, no.
    y0, x0 = grupo[0]
    desde = pre[y0][x0]
    hasta = post[y0][x0]
    for y, x in grupo:
        if pre[y][x] != desde or post[y][x] != hasta:
            return MecanicaDeCluster(
                tipo="desconocida",
                celdas=len(grupo),
                caja=caja,
                traslacion=None,
                cambio_de_color=None,
            )

    fondo = fondo_local(pre, grupo, caja)
    if desde == fondo:
        tipo = "aparicion"
    elif hasta == fondo:
        tipo = "desaparicion"
    else:
        tipo = "recoloreo"
    return MecanicaDeCluster(
        tipo=tipo,
        celdas=len(grupo),
        caja=caja,
        traslacion=None,
        cambio_de_color=CambioDeColor(desde=desde, hasta=hasta, celdas=len(grupo)),
    )


def _traslacion_de_cluster(
    pre: Grid,
    post: Grid,
    grupo: list[Celda],
    caja: BoundingBox,
    max_tamano_objeto: int,
    min_evidencia: float,
) -> Traslacion | None:
    """Busca una caja `R` de `pre` y un desplazamiento `d != 0` tales que `post[R+d] == pre[R]` y
    todo cambio del cluster caiga dentro de `R U (R+d)`.

    LA AMBIGUEDAD QUE HAY QUE ROMPER (medida en dato real): cuando un objeto se mueve a un hueco
    vacio, la hipotesis simetrica "el HUECO se movio en sentido contrario" satisface las MISMAS
    ecuaciones y devuelve la direccion INVERTIDA. Se rompe con dos evidencias independientes:
    `cobertura` (fraccion de R ocupada por componentes contenidas en la caja) y `relleno`
    (fraccion de celdas desalojadas que quedaron del color del fondo local). Alcanza con UNA por
    encima del umbral: hay objetos articulados que solo pasan por relleno y tableros con fondo
    texturado que solo pasan por cobertura."""
    alto_caja = caja.max_y - caja.min_y + 1
    ancho_caja = caja.max_x - caja.min_x + 1
    if alto_caja * ancho_caja > MAX_AREA_CAJA_DE_CAMBIOS:
        return None

    alto = len(pre)
    ancho = len(pre[0])
    fondo = fondo_local(pre, grupo, caja)
    candidatas: list[Traslacion] = []

    for dy in range(-(alto_caja - 1), alto_caja):
        for dx in range(-(ancho_caja - 1), ancho_caja):
            if dy == 0 and dx == 0:
                continue
            # `R U (R+d)` tiene exactamente el bbox del cluster, asi que `R` se despeja del bbox y
            # de d sin buscar: el desplazamiento come |dy| filas y |dx| columnas.
            r = BoundingBox(
                min_y=caja.min_y - min(0, dy),
                max_y=caja.max_y - max(0, dy),
                min_x=caja.min_x - min(0, dx),
                max_x=caja.max_x - max(0, dx),
            )
            if r.min_y > r.max_y or r.min_x > r.max_x:
                continue
            if (r.max_y - r.min_y + 1) * (r.max_x - r.min_x + 1) > max_tamano_objeto:
                continue
            if not _contenido_se_movio(pre, post, r, dy, dx, alto, ancho):
                continue
            if not _cambios_dentro_de_la_union(grupo, r, dy, dx):
                continue
            cobertura = cobertura_de_objetos(pre, r, max_tamano_objeto)
            relleno = _relleno_de_fondo(post, r, dy, dx, fondo)
            if cobertura < min_evidencia and relleno < min_evidencia:
                continue
            candidatas.append(
                Traslacion(
                    dy=dy,
                    dx=dx,
                    min_y=r.min_y,
                    min_x=r.min_x,
                    alto=r.max_y - r.min_y + 1,
                    ancho=r.max_x - r.min_x + 1,
                    cobertura=cobertura,
                    relleno=relleno,
                )
            )

    if not candidatas:
        return None
    candidatas.sort(
        key=lambda t: (
            -t.cobertura,
            -t.relleno,
            abs(t.dy) + abs(t.dx),
            t.alto * t.ancho,
            t.dy,
            t.dx,
        )
    )
    return candidatas[0]


def _contenido_se_movio(
    pre: Grid, post: Grid, r: BoundingBox, dy: int, dx: int, alto: int, ancho: int
) -> bool:
    """`post[R+d] == pre[R]` celda a celda, y el movimiento tiene que cambiar ALGO -- si no,
    cualquier region de fondo "se traslada" a otra region de fondo identica."""
    algo_cambio = False
    for y in range(r.min_y, r.max_y + 1):
        for x in range(r.min_x, r.max_x + 1):
            ny = y + dy
            nx = x + dx
            if ny < 0 or nx < 0 or ny >= alto or nx >= ancho:
                return False
            if post[ny][nx] != pre[y][x]:
                return False
            if pre[y][x] != post[y][x]:
                algo_cambio = True
    return algo_cambio


def _cambios_dentro_de_la_union(
    grupo: list[Celda], r: BoundingBox, dy: int, dx: int
) -> bool:
    for y, x in grupo:
        en_r = r.min_y <= y <= r.max_y and r.min_x <= x <= r.max_x
        en_destino = (
            r.min_y + dy <= y <= r.max_y + dy and r.min_x + dx <= x <= r.max_x + dx
        )
        if not en_r and not en_destino:
            return False
    return True


def _relleno_de_fondo(
    post: Grid, r: BoundingBox, dy: int, dx: int, fondo: int
) -> float:
    desalojadas = 0
    con_fondo = 0
    for y in range(r.min_y, r.max_y + 1):
        for x in range(r.min_x, r.max_x + 1):
            en_destino = (
                r.min_y + dy <= y <= r.max_y + dy and r.min_x + dx <= x <= r.max_x + dx
            )
            if en_destino:
                continue
            desalojadas += 1
            if post[y][x] == fondo:
                con_fondo += 1
    return 0.0 if desalojadas == 0 else con_fondo / desalojadas
