"""[arc-agi3-kaggle-agent/scripts/paso_de_la_maniobra] BL.21728 + BL.21765 -- UN PASO de la
maniobra previa: que se midio de esa transicion, si el detector la miro siquiera, y las dos formas
de serie que NO son evidencia de una maniobra (la animacion en loop y la oscilacion entre dos
estados).

Vive aparte de `maniobra_previa` (que agrega estos pasos en la vista que reciben los criterios) por
tamano: aquel modulo cruzo el limite de lineas al agregarsele el saldo de objetos por paso. Aca esta
EL PASO; alla, la VISTA. `maniobra_previa` lo re-exporta entero, asi que ningun llamador cambia.

Stdlib pura, sin imports del resto del paquete (asi `caracterizacion_de_niveles` puede importarlo
sin ciclo). SOLO REPO."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from serie_de_la_maniobra import sin_variacion  # noqa: E402

#: Minimo de pasos no-inertes iguales para llamar "animacion en loop" a la serie. Con dos pasos
#: iguales la coincidencia es barata (cualquier maniobra repetitiva la produce); con tres o mas y
#: la ocupacion clavada, la hipotesis "el tablero se anima solo" es la unica que queda en pie.
MINIMO_DE_PASOS_PARA_LOOP = 3

#: Veces que, EN PROMEDIO, tiene que repetirse cada firma para que la serie sea un loop (BL.21765).
#: DOS: un loop es, por definicion, un ciclo -- vuelve a pasar por los mismos estados. Con este
#: minimo, ft09 (9 pasos alternando `recoloreo:8>9` y `recoloreo:9>8`, 2 firmas) sigue siendo el
#: loop que se midio, y lp85 nivel 1 (4 pasos con `recoloreo:1>2`, `2>10`, `10>9`, `9>15` -- una
#: CADENA en la que cada paso continua el anterior, 4 firmas en 4 pasos) deja de serlo. Los dos
#: casos son indistinguibles por celdas cambiadas: los cuatro pasos de lp85 tocan EXACTAMENTE 293
#: celdas con la ocupacion clavada, que era el unico instrumento que habia antes de BL.21741.
#: Cuando ningun paso trae firma medida todas valen `FIRMA_SIN_MEDIR`, la condicion se cumple sola
#: y el comportamiento es el de antes: este criterio solo puede QUITAR la etiqueta de loop cuando
#: hay percepcion que la contradiga, nunca ponerla donde no estaba.
REPETICIONES_MINIMAS_DE_FIRMA_EN_LOOP = 2

#: Firma de un paso previo que NADIE midio. NO es lo mismo que `desconocida` (el detector miro y no
#: supo nombrar) ni que `sobreElTope` (el detector se nego a mirar): es un paso construido sin
#: percepcion, y por eso no puede sostener NINGUN criterio basado en firmas. El centinela existe
#: para que ese caso sea visible y auditable en vez de contarse como evidencia nula silenciosa.
FIRMA_SIN_MEDIR = "sinMedir"

#: Tipos de cluster de `object_mechanics` que este modulo cuenta por separado sobre la maniobra.
#: Se repiten como literales (y no se importan) para no atar `maniobra_previa` -- que es stdlib
#: pura y la importa `caracterizacion_de_niveles` -- al paquete de percepcion; el test de BL.21765
#: fija que la lista coincide con la del detector.
TIPOS_DE_CLUSTER: tuple[str, ...] = (
    "aparicion",
    "desaparicion",
    "desconocida",
    "recoloreo",
    "traslacion",
)

#: Firmas que significan QUE EL DETECTOR NO MIRO ESA TRANSICION -- espejo de `TIPOS_DE_NO_MIRE`, la
#: fuente unica de `object_mechanics` (BL.21741), replicado aca por la misma razon que
#: `TIPOS_DE_CLUSTER` y fijado contra el original por un test.
#:
#: POR QUE LO NECESITA ESTE MODULO (defecto medido, BL.21765). Un paso `sobreElTope` o
#: `formaIncompatible` sale del detector con CERO clusters, y cero clusters es indistinguible de
#: "no cambio nada" para cualquier consumidor que solo cuente clusters. Peor todavia:
#: `formaIncompatible` sale ademas con `celdas_cambiadas == 0` sin haber contado una sola celda, o
#: sea que el `inerte` de este modulo lo declaraba "el agente actuo y el tablero no se movio" --
#: exactamente la regresion que BL.21741 documento para `direction_beliefs` y que se colo un nivel
#: mas abajo, en el consumidor nuevo. El silencio del detector NO es evidencia de quietud y NO
#: puede sostener ni contradecir un veredicto: tiene que declararse.
TIPOS_DE_NO_MIRE: tuple[str, ...] = ("sobreElTope", "formaIncompatible")

#: Estados distintos como maximo para llamar OSCILACION a una serie de firmas. DOS: es la forma
#: minima de "el tablero va y vuelve entre dos configuraciones". Ver `es_oscilacion_de_firmas`.
MAXIMO_DE_ESTADOS_EN_OSCILACION = 2

@dataclass(frozen=True)
class PasoPrevio:
    """Una transicion ANTERIOR al evento: cuanto cambio, como quedo la ocupacion, y QUE MECANICA
    fue segun la percepcion objeto-centrica.

    `firma` y `clusters` los agrega BL.21765 y son la entrada que faltaba: hasta ese BL la unica
    firma que salia de la percepcion viajaba en `MedicionDeEvento` (el frame del EVENTO y las cinco
    transiciones previas), y ningun criterio de tipo objetivo la veia -- los criterios reciben
    `VistaDeLaManiobra`, que no tenia un solo campo de firma. Es decir: el vocabulario de BL.21728
    se re-derivo sobre una vista CIEGA a las firmas, incluso despues de que BL.21741 las arreglara."""

    paso: int
    celdas_cambiadas: int
    ocupacion: float
    #: Firma de BL.21741 de ESTA transicion previa (`firma_de_mecanica`, compuesta si la transicion
    #: es una mezcla). `FIRMA_SIN_MEDIR` si el paso se construyo sin percepcion.
    firma: str = FIRMA_SIN_MEDIR
    #: Desglose (tipo, cantidad) de los clusters de cambio de ESTA transicion, ordenado por tipo.
    #: Tupla de pares y no dict para que el dataclass siga siendo frozen y hasheable.
    clusters: tuple[tuple[str, int], ...] = ()

    @property
    def no_mirado(self) -> bool:
        """El detector NO analizo esta transicion (`sobreElTope` / `formaIncompatible`, BL.21741).

        Sus cero clusters no significan "no paso nada": significan "no se". Un paso asi no puede
        sostener NI CONTRADECIR un criterio de saldo de objetos."""
        return self.firma in TIPOS_DE_NO_MIRE

    @property
    def inerte(self) -> bool:
        """Cero celdas cambiadas Y el detector SI miro. El agente actuo y el tablero no se movio.

        El `and not self.no_mirado` no es defensivo: `formaIncompatible` sale del detector con
        `celdas_cambiadas == 0` sin haber contado nada (`_mecanica_vacia`), y sin esta mitad ese
        cero se contaba como quietud medida. Es la regresion que BL.21741 saco de
        `direction_beliefs` reapareciendo en el consumidor nuevo."""
        return self.celdas_cambiadas == 0 and not self.no_mirado

    @property
    def firma_medida(self) -> bool:
        """Alguien corrio la percepcion sobre este paso. Si es False, el paso NO puede sostener un
        criterio de firma -- ni a favor ni en contra."""
        return self.firma != FIRMA_SIN_MEDIR

    def clusters_de(self, tipo: str) -> int:
        return next((cantidad for t, cantidad in self.clusters if t == tipo), 0)

    # --- SALDO DE OBJETOS DE ESTE PASO (BL.21765, corregido) -----------------------------------
    # POR QUE EL SALDO SE MIDE POR PASO Y NO SOBRE EL TOTAL DE LA MANIOBRA (defecto MEDIDO). La
    # primera version de estos criterios sumaba apariciones y desapariciones sobre toda la maniobra
    # y comparaba los dos totales. Sobre el corpus persistido eso hizo SOBREVIVIR
    # `pintarRegionPorObjetos` en vc33 con un margen de 1 (5 apariciones contra 4 desapariciones), y
    # el desglose paso a paso muestra que ahi no hay ninguna maniobra de llenado: la ventana de
    # vc33 nivel 1 ALTERNA exactamente dos estados,
    #     A->B  (aparicion 1, desconocida 1, recoloreo 1)  x5
    #     B->A  (desaparicion 1, traslacion 1, recoloreo 1) x4
    # o sea que el MISMO objeto prende y apaga, el saldo real es CERO y el excedente de 1 existe
    # solo porque 9 es impar. Contrafactual corrido sobre el corpus real: quitando UN frame previo
    # de la ventana el "superviviente" desaparece y el vocabulario vuelve a vacio. Un veredicto que
    # depende de la PARIDAD de la cantidad de frames capturados no mide el mundo, mide la captura.
    #
    # El saldo por paso es el espejo objeto-centrico de `pasos_que_suben` / `pasos_que_bajan` sobre
    # la ocupacion: ahi tampoco se comparan los extremos de la serie, se cuentan los pasos que se
    # mueven de verdad en la direccion afirmada.

    @property
    def apariciones(self) -> int:
        return self.clusters_de("aparicion")

    @property
    def desapariciones(self) -> int:
        return self.clusters_de("desaparicion")

    @property
    def clusters_sin_nombrar(self) -> int:
        """Clusters que el detector miro y NO supo nombrar (`desconocida`).

        Por construccion (`_clasificar_cluster`) un cluster es `desconocida` cuando NO es un par
        unico desde->hasta: puede contener una aparicion y una desaparicion a la vez. Se cuentan
        aparte porque son la contraparte DIRECTA de los que si se supo nombrar -- medido: en vc33
        nivel 1 la MISMA region de 156 celdas sale `desconocida` en el sentido A->B y `traslacion`
        en el sentido B->A. Ignorarlos convierte el saldo de objetos en una medida del REGIMEN DE
        ETIQUETADO del detector y no del tablero."""
        return self.clusters_de("desconocida")

    @property
    def hace_aparecer_netamente(self) -> bool:
        """En ESTE paso aparecieron mas objetos de los que se fueron, contando como "se fueron"
        tambien a los clusters sin nombrar (que pueden serlo). Es la lectura CONSERVADORA: si el
        detector no supo nombrar la contraparte, el paso no cuenta como llenado."""
        return self.apariciones > self.desapariciones + self.clusters_sin_nombrar

    @property
    def hace_desaparecer_netamente(self) -> bool:
        """Espejo de `hace_aparecer_netamente`."""
        return self.desapariciones > self.apariciones + self.clusters_sin_nombrar


def es_animacion_en_loop(pasos: Sequence[PasoPrevio]) -> bool:
    """La serie de pasos previos es una ANIMACION EN LOOP: todos los pasos que cambian algo cambian
    exactamente la misma cantidad de celdas y la ocupacion no se mueve.

    TODO O NADA sobre los pasos no-inertes, no por tramos: una serie mixta (algunos pasos de 38
    celdas y uno de 40) es una maniobra CON repeticion, no un loop, y llamarla loop descartaria
    evidencia real. El sesgo va deliberadamente hacia no declarar loop."""
    activos = [p for p in pasos if not p.inerte]
    if len(activos) < MINIMO_DE_PASOS_PARA_LOOP:
        return False
    if not (
        sin_variacion([p.celdas_cambiadas for p in activos])
        and sin_variacion([p.ocupacion for p in activos])
    ):
        return False
    # BL.21765: y ademas las firmas tienen que CICLAR. Sin esto, una cadena de mecanicas distintas
    # que casualmente tocan la misma cantidad de celdas se contaba como "el tablero animandose
    # solo" y sus frames desaparecian de la evidencia (medido: los 4 pasos de lp85 nivel 1).
    distintas = len({p.firma for p in activos})
    return distintas * REPETICIONES_MINIMAS_DE_FIRMA_EN_LOOP <= len(activos)


#: Las TRES clases de paso previo, con el nombre exacto con el que viajan al corpus persistido
#: (BL.21794). Son las mismas tres de BL.21728 -- lo nuevo es que ahora tienen un nombre estable,
#: se calculan UNA vez (en la captura) y se guardan, en vez de reconstruirse en cada informe.
CLASE_INERTE = "inerte"
CLASE_EN_ANIMACION = "enAnimacion"
CLASE_INFORMATIVO = "informativo"
CLASES_DE_PASO: tuple[str, ...] = (CLASE_INERTE, CLASE_EN_ANIMACION, CLASE_INFORMATIVO)


def clasificar_pasos(pasos: Sequence[PasoPrevio]) -> tuple[str, ...]:
    """Clase de CADA paso de la serie: `inerte`, `enAnimacion` o `informativo`.

    ES LA FUENTE UNICA DE LA CLASIFICACION (BL.21794). Antes las tres categorias existian solo como
    tres contadores independientes de `VistaDeLaManiobra` (`pasos_inertes`, `pasos_en_animacion`,
    `pasos_informativos`, este ultimo por resta), y la captura no las registraba: se reconstruian en
    cada informe. Ahora la vista cuenta SOBRE esta funcion y la captura la persiste por frame, asi
    que "55 informativos, 27 inertes, 18 en animacion" deja de ser una lectura que hay que rehacer y
    pasa a ser un dato del corpus -- verificable contra su propia re-derivacion.

    La clase de un paso NO se puede decidir mirando solo ese paso: `enAnimacion` es una propiedad de
    la SERIE (`es_animacion_en_loop`), asi que la funcion recibe la serie entera y devuelve una
    clase por paso, en orden. Un paso inerte sigue siendo inerte aunque la serie sea un loop: es la
    misma prioridad que tenian los contadores (`pasos_en_animacion` solo cuenta los NO inertes)."""
    loop = es_animacion_en_loop(pasos)
    return tuple(
        CLASE_INERTE if p.inerte else (CLASE_EN_ANIMACION if loop else CLASE_INFORMATIVO)
        for p in pasos
    )


def es_oscilacion_de_firmas(pasos: Sequence[PasoPrevio]) -> bool:
    """La serie de pasos activos VA Y VUELVE entre a lo sumo `MAXIMO_DE_ESTADOS_EN_OSCILACION`
    mecanicas, cada una repetida al menos `REPETICIONES_MINIMAS_DE_FIRMA_EN_LOOP` veces.

    POR QUE EXISTE, SEPARADO DE `es_animacion_en_loop` (defecto MEDIDO, BL.21765). La deteccion de
    loop exige que TODOS los pasos activos cambien EXACTAMENTE la misma cantidad de celdas y que la
    ocupacion quede clavada -- comparacion exacta, a proposito. La maniobra de vc33 nivel 1 cambia
    [266, 265, 265, 265, 266, 265, 265, 266, 265] celdas con la ocupacion en sube-y-baja
    (0,3799 <-> 0,3652), asi que UNA celda de diferencia alcanza para que sus 9 pasos se cuenten
    como informativos. Pero sus firmas son DOS y se alternan: el tablero va y vuelve entre dos
    configuraciones. El informe los presentaba como "18 frames informativos, 0 de animacion", que
    es literalmente cierto segun el instrumento y engañoso sobre lo que hay en esos frames.

    SOLO SE REPORTA, NO GATEA NADA. Endurecer el descarte de frames despues de haber visto el
    resultado es la otra cara de forzar supervivientes; ademas la evidencia que hace falta no es
    "descontar estos frames" sino "no dejar que una oscilacion se lea como saldo", y de eso se
    ocupan `hace_aparecer_netamente` / `hace_desaparecer_netamente`, que miden por paso. Este
    predicado existe para que el numero este a la vista del que lee el informe."""
    activos = [p for p in pasos if not p.inerte]
    if len(activos) < MINIMO_DE_PASOS_PARA_LOOP:
        return False
    if not all(p.firma_medida for p in activos):
        return False
    conteo: dict[str, int] = {}
    for paso in activos:
        conteo[paso.firma] = conteo.get(paso.firma, 0) + 1
    return (
        len(conteo) <= MAXIMO_DE_ESTADOS_EN_OSCILACION
        and min(conteo.values()) >= REPETICIONES_MINIMAS_DE_FIRMA_EN_LOOP
    )



__all__ = [
    "FIRMA_SIN_MEDIR",
    "MAXIMO_DE_ESTADOS_EN_OSCILACION",
    "MINIMO_DE_PASOS_PARA_LOOP",
    "REPETICIONES_MINIMAS_DE_FIRMA_EN_LOOP",
    "TIPOS_DE_CLUSTER",
    "TIPOS_DE_NO_MIRE",
    "PasoPrevio",
    "es_animacion_en_loop",
    "es_oscilacion_de_firmas",
]
