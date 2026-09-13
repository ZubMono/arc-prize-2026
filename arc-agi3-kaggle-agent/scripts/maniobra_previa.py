"""[arc-agi3-kaggle-agent/scripts/maniobra_previa] BL.21728 -- TODO lo que se mide EXCLUYENDO el
frame de la transicion, y la clasificacion de los pasos previos en informativos / inertes /
animacion en loop.

POR QUE EXISTE ESTE MODULO APARTE (defecto MEDIDO, BL.21728 defecto 1). El vocabulario de objetivos
de BL.21695 se derivo con el frame del evento ADENTRO de las series, asi que sus criterios detectan
el RESULTADO y no la maniobra:
  - `recolectarTodo` afirmaba "la ocupacion bajo de forma monotona" en 6 de 14 eventos. Medido: la
    ocupacion es PLANA los 10 frames previos y cae SOLO en el frame del evento (ft09 0,4727 x10 ->
    0,1553; lp85 0,5171 x10 -> 0,4338). Excluyendo ese frame el criterio es False en 6 de 6.
  - `pintarRegion` igual: sc25 y vc33:1 daban True SOLO con el frame del evento adentro.
  - `colores_agotados` en ft09 es el mismo artefacto: el evento reescribio el 88% de la grilla, asi
    que TODO color "se agoto" porque el tablero entero fue reemplazado.
Un criterio que se cumple unicamente gracias al frame que define el evento no es evidencia de nada:
es la definicion del evento escrita dos veces.

LA GARANTIA ES ESTRUCTURAL, NO UNA CONVENCION. `VistaDeLaManiobra` es el UNICO objeto que reciben
los criterios de tipo OBJETIVO, y sus campos se llaman `..._en_la_maniobra` justamente para que NO
colisionen con los homonimos de `MedicionDeEvento` (que si incluyen el frame del evento). Si alguien
vuelve a escribir un criterio contra `m.vaciado_monotono`, la llamada revienta con AttributeError en
vez de devolver silenciosamente el artefacto. El test correspondiente fija ese contrato.

TRES CATEGORIAS DE PASO PREVIO, porque "10 frames antes" no significa "10 frames de evidencia":
  - INERTE: la transicion no cambio NI UNA celda. Medido: en lp85 5 de 9 pasos previos y en m0r0
    4 de 9. Un paso que no cambia nada no sostiene ningun veredicto sobre lo que hizo el agente.
  - EN ANIMACION EN LOOP: todos los pasos no-inertes cambian EXACTAMENTE la misma cantidad de
    celdas y la ocupacion queda clavada. Medido en ft09: 9 pasos de 38 celdas con ocupacion fija en
    0,4727. Eso es el juego animandose solo, no una maniobra.
  - INFORMATIVO: lo que queda. Es el unico numero que el informe puede citar como "frames reales
    que sostienen este veredicto".

BL.21765 -- LA VISTA TAMBIEN LLEVA LAS FIRMAS. Hasta este BL `VistaDeLaManiobra` no tenia UN SOLO
campo de firma: las unicas firmas del sistema viajaban en `MedicionDeEvento` (`firma_del_evento` y
`firmas_previas`) y ahi solo las leen criterios de tipo DESCRIPTOR, que por construccion no entran
al vocabulario. Consecuencia medida: cuando BL.21741 arreglo la percepcion -- las 8 transiciones
distintas dejaron de valer todas "desconocida" y pasaron a tener 7 firmas distintas -- ese arreglo
NO llego a la re-derivacion del vocabulario, que siguio decidiendo con ocupacion, colores agotados
y distancias. Ahora cada `PasoPrevio` lleva su firma y su desglose de clusters, y la vista los
agrega SOLO sobre los pasos informativos: un paso inerte o de animacion en loop no aporta clusters,
igual que no aporta monotonia.

Stdlib pura, sin imports del resto del paquete (asi `caracterizacion_de_niveles` puede importarlo
sin ciclo). SOLO REPO."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Re-exportados a proposito: al agregarse el saldo de objetos por paso (BL.21765) este modulo cruzo
# el limite de lineas y se partio en tres -- EL PASO (`paso_de_la_maniobra`), las SERIES NUMERICAS
# (`serie_de_la_maniobra`) y la VISTA (aca). Los llamadores siguen importando todo desde aca.
from paso_de_la_maniobra import (  # noqa: E402,F401
    CLASE_EN_ANIMACION,
    CLASE_INERTE,
    CLASE_INFORMATIVO,
    CLASES_DE_PASO,
    FIRMA_SIN_MEDIR,
    MAXIMO_DE_ESTADOS_EN_OSCILACION,
    MINIMO_DE_PASOS_PARA_LOOP,
    REPETICIONES_MINIMAS_DE_FIRMA_EN_LOOP,
    TIPOS_DE_CLUSTER,
    TIPOS_DE_NO_MIRE,
    PasoPrevio,
    clasificar_pasos,
    es_animacion_en_loop,
    es_oscilacion_de_firmas,
)
from serie_de_la_maniobra import (  # noqa: E402,F401
    MINIMO_DE_PASOS_QUE_MUEVEN,
    creciente_monotona,
    decreciente_monotona,
    pasos_que_bajan,
    pasos_que_suben,
    sin_variacion,
    tendencia_creciente,
    tendencia_decreciente,
)

#: Ancho nominal de la ventana capturada (`captura_de_niveles.VENTANA_POR_DEFECTO`). Se repite aca
#: como referencia de TRUNCAMIENTO -- una ventana con menos frames previos que esto vota con menos
#: evidencia que una completa, y el informe tiene que decirlo. No se importa para no atar este
#: modulo al capturador: si el ancho cambia, cambia el aviso, no la medicion.
ANCHO_NOMINAL_DE_VENTANA = 10

#: Clicks previos minimos para poder afirmar que la linea base esta SATURADA. Dos y no uno, por el
#: mismo argumento con el que `MINIMO_DE_PASOS_QUE_MUEVEN` es 2 y `creciente_monotona` exige 3
#: puntos: una sola observacion no tiene varianza que medir. Es el unico predicado del modulo que
#: MATA un candidato, asi que era el que menos podia quedar sin minimo (correccion de BL.21728).
MINIMO_DE_CLICKS_PREVIOS = 2


@dataclass(frozen=True)
class VistaDeLaManiobra:
    """Lo que se puede afirmar mirando SOLO los frames anteriores al evento.

    Es el unico objeto que reciben los criterios de tipo OBJETIVO de `caracterizar_completados`. Los
    sufijos `_en_la_maniobra` existen para que un criterio escrito contra el campo equivocado
    (`vaciado_monotono`, el que incluye el frame del evento) falle con AttributeError en vez de
    devolver el artefacto en silencio."""

    #: Frames anteriores al evento presentes en la ventana. Puede ser menor que el ancho nominal si
    #: el evento ocurrio cerca del arranque de la partida (medido: vc33 nivel 1 tiene 2).
    frames_previos: int
    pasos: tuple[PasoPrevio, ...] = ()
    ocupacion: tuple[float, ...] = ()
    vaciado_monotono_en_la_maniobra: bool = False
    llenado_monotono_en_la_maniobra: bool = False
    colores_agotados_en_la_maniobra: tuple[int, ...] = ()
    pasos_con_traslacion_en_la_maniobra: int = 0
    colores_alcanzados_en_la_maniobra: tuple[int, ...] = ()
    aproximacion_monotona_en_la_maniobra: tuple[int, ...] = ()
    #: Click del evento leido sobre la grilla PREVIA (donde apunto el agente en el tablero tal como
    #: estaba). No es informacion del desenlace: la grilla posterior no participa.
    #:
    #: DECLARADO, NO AFLOJADO (BL.21765): estos dos campos son la UNICA via por la que algo del
    #: frame del evento entra a la vista de la maniobra. Todo lo demas se construye con
    #: `range(1, indice)` y nunca toca `frames[indice]`. Que el paso ganador haya sido un click es
    #: informacion sobre CUAL paso gano, no sobre la maniobra, asi que el criterio que los usa
    #: (`resueltoTocandoUnObjeto`) exige ademas que la linea base NO este saturada -- sin esa
    #: segunda mitad estaria leyendo el desenlace por la puerta de al lado. Hoy da 0/14 justamente
    #: por la linea base; si alguna vez se captura una muestra con clicks al fondo, esta nota es el
    #: lugar por donde hay que volver a entrar.
    hubo_click_del_evento: bool = False
    color_bajo_el_click_previo: int | None = None
    clicks_previos: int = 0
    clicks_previos_en_objeto: int = 0

    @property
    def clases_de_los_pasos(self) -> tuple[str, ...]:
        """Clase de cada paso, de la FUENTE UNICA (`clasificar_pasos`, BL.21794). Los tres
        contadores de abajo la cuentan; antes cada uno tenia su propio predicado en linea y la
        captura no registraba ninguno."""
        return clasificar_pasos(self.pasos)

    @property
    def pasos_inertes(self) -> int:
        return sum(1 for c in self.clases_de_los_pasos if c == CLASE_INERTE)

    @property
    def animacion_en_loop(self) -> bool:
        return es_animacion_en_loop(self.pasos)

    @property
    def pasos_en_animacion(self) -> int:
        """Pasos que solo son el tablero animandose. 0 si la serie no es un loop."""
        return sum(1 for c in self.clases_de_los_pasos if c == CLASE_EN_ANIMACION)

    @property
    def pasos_informativos(self) -> int:
        """Pasos que cambian algo y no son parte de un loop. ES el numero de frames REALES que
        sostienen cualquier veredicto sobre esta maniobra."""
        return sum(1 for c in self.clases_de_los_pasos if c == CLASE_INFORMATIVO)

    @property
    def ventana_truncada(self) -> bool:
        return self.frames_previos < ANCHO_NOMINAL_DE_VENTANA

    @property
    def pasos_que_suben_la_ocupacion(self) -> int:
        return pasos_que_suben(self.ocupacion)

    @property
    def pasos_que_bajan_la_ocupacion(self) -> int:
        return pasos_que_bajan(self.ocupacion)

    @property
    def linea_base_de_click_saturada(self) -> bool:
        """TODOS los clicks previos de la ventana tambien cayeron sobre un objeto, con al menos
        `MINIMO_DE_CLICKS_PREVIOS` de muestra.

        Cuando esto es True, "el click que gano cayo sobre un objeto" tiene VARIANZA CERO en la
        muestra: los clicks que NO ganaron cumplen exactamente lo mismo, asi que el rasgo no puede
        explicar el desenlace. Es el mismo confound que meter el frame del evento en la serie de
        monotonia, escrito sobre el eje de las acciones en vez del eje del tiempo.

        EL MINIMO ES UNA CORRECCION DE BL.21728 (defecto medido). El predicado era
        `clicks_previos > 0 and ...`, o sea que con UN SOLO click previo daba saturada SIEMPRE --
        y le tocaba justo a vc33 nivel 1, la ventana que el propio informe marca TRUNCADA
        (framesAntes=2, 1/1). El rigor era asimetrico: este modulo exige `MINIMO_DE_PASOS_QUE_MUEVEN
        = 2` para admitir una tendencia y `>= 3` puntos para una monotonia, pero el criterio que
        MATA candidatos se conformaba con una observacion. "Varianza cero" sobre n=1 no es una
        medicion.

        NUMEROS DEL CORPUS PERSISTIDO, contados del informe y no a ojo (el docstring anterior decia
        "los 6 eventos que se resuelven con click" y sub-declaraba la muestra en 4 de 10):
          - 10 eventos tienen click del evento;
          - en 6 el click cayo sobre una COMPONENTE (ft09 x2, lp85 nivel 2, vc33 x3);
          - los otros 4 son los de lp85 nivel 1 y quedan fuera del criterio por OTRA razon: el
            click gano cayendo sobre el FONDO (`color_bajo_el_click_previo is None`), con lineas
            base 0/9, 5/9, 5/9 y 3/9 -- o sea que NO estan saturados. Atribuirles "varianza cero"
            era describir un mecanismo que no es el que actua;
          - de los 6 sobre componente, 5 tienen la linea base saturada con 9 de 9 clicks previos, y
            el sexto es vc33 nivel 1 paso 3: ventana TRUNCADA (framesAntes=2) con 1 solo click
            previo. Con el minimo puesto deja de matarse a si mismo, y `resueltoTocandoUnObjeto`
            pasa de 0/14 a 1/14 sobre 1 transicion distinta: sigue sin sobrevivir al gate de
            muestra, pero ahora por la razon correcta."""
        return (
            self.clicks_previos >= MINIMO_DE_CLICKS_PREVIOS
            and self.clicks_previos_en_objeto == self.clicks_previos
        )

    # --- BL.21765: la maniobra vista con las firmas de BL.21741 --------------------------------
    # TODO lo de abajo se calcula SOBRE LOS PASOS INFORMATIVOS y nunca sobre el frame del evento
    # (que ni siquiera esta en `self.pasos`). Un paso inerte no cambio nada y uno de animacion en
    # loop es el tablero animandose solo: ninguno de los dos puede sostener una afirmacion sobre
    # que estaba haciendo el agente, y contar sus clusters seria reintroducir por el eje de las
    # mecanicas el mismo relleno que BL.21728 saco del eje del tiempo.

    @property
    def pasos_que_sostienen(self) -> tuple[PasoPrevio, ...]:
        """Los pasos INFORMATIVOS, como objetos. `pasos_informativos` cuenta estos mismos."""
        if self.animacion_en_loop:
            return ()
        return tuple(p for p in self.pasos if not p.inerte)

    @property
    def firmas_en_la_maniobra(self) -> tuple[str, ...]:
        """Firma de BL.21741 de cada paso informativo, en orden."""
        return tuple(p.firma for p in self.pasos_que_sostienen)

    @property
    def sin_pasos_informativos(self) -> bool:
        """No queda NI UN paso que pueda sostener nada: o todos son inertes, o la serie entera es
        una animacion en loop. NO es lo mismo que no haber corrido la percepcion."""
        return not self.pasos_que_sostienen

    @property
    def maniobra_sin_firmas_medidas(self) -> bool:
        """HAY pasos informativos y NINGUNO trae firma medida. Cuando es True, TODO criterio de
        firma da False por AUSENCIA DE PERCEPCION y no por ausencia del rasgo -- y el informe tiene
        que poder decir cual de las dos cosas paso.

        EL `bool(self.pasos_que_sostienen)` ES EL ARREGLO (defecto MEDIDO, BL.21765). Sin el, un
        `any()` sobre la tupla vacia daba False y la propiedad devolvia True para toda maniobra sin
        pasos informativos: los 2 eventos de ft09 del corpus salian marcados "SIN FIRMAS MEDIDAS"
        teniendo 9 de 9 pasos con firma REALMENTE medida (`recoloreo:8>9` / `recoloreo:9>8`) -- son
        un loop, que es una razon distinta y ya tiene su propio contador. El informe afirmaba
        "no hubo percepcion" sobre el unico juego donde la percepcion habia corrido limpia."""
        return bool(self.pasos_que_sostienen) and not any(
            p.firma_medida for p in self.pasos_que_sostienen
        )

    @property
    def clusters_en_la_maniobra(self) -> dict[str, int]:
        """Clusters de cambio acumulados por tipo sobre los pasos informativos."""
        total: dict[str, int] = {}
        for paso in self.pasos_que_sostienen:
            for tipo, cantidad in paso.clusters:
                total[tipo] = total.get(tipo, 0) + cantidad
        return {tipo: total[tipo] for tipo in sorted(total)}

    def pasos_con_clusters_de(self, tipo: str) -> int:
        """Cuantos pasos INFORMATIVOS traen al menos un cluster de `tipo`. Se cuenta por PASOS y no
        por clusters por el mismo argumento de `MINIMO_DE_PASOS_QUE_MUEVEN`: una sola transicion
        que borra seis objetos es un escalon, no una maniobra de recoleccion sostenida."""
        return sum(1 for p in self.pasos_que_sostienen if p.clusters_de(tipo) > 0)

    @property
    def objetos_aparecidos_en_la_maniobra(self) -> int:
        return self.clusters_en_la_maniobra.get("aparicion", 0)

    @property
    def objetos_desaparecidos_en_la_maniobra(self) -> int:
        return self.clusters_en_la_maniobra.get("desaparicion", 0)

    @property
    def pasos_que_hacen_desaparecer_en_la_maniobra(self) -> int:
        """Pasos con AL MENOS un cluster que desaparece, mire o no la contraparte. Es el
        instrumento VIEJO y queda para el contraste: `pasos_que_hacen_desaparecer_NETAMENTE` es el
        que usan los criterios. Medido sobre el corpus: en vc33 nivel 2 los 9 pasos traen 1
        aparicion Y 1 contraparte que se va, o sea que este contador declara "sostenido en 9 pasos"
        sobre una serie de saldo CERO."""
        return self.pasos_con_clusters_de("desaparicion")

    @property
    def pasos_que_hacen_aparecer_en_la_maniobra(self) -> int:
        """Espejo del anterior, y con el mismo aviso: cuenta presencia, no saldo."""
        return self.pasos_con_clusters_de("aparicion")

    # --- SALDO NETO DE OBJETOS (BL.21765, corregido) ---------------------------------------------
    # Estos son los que leen los criterios. Ver el bloque de `PasoPrevio` para el defecto que los
    # motiva: contar presencia de clusters por paso y comparar totales de la maniobra hacia
    # sobrevivir un candidato sobre una OSCILACION de saldo cero muestreada un numero impar de
    # veces.

    @property
    def pasos_que_hacen_aparecer_netamente_en_la_maniobra(self) -> int:
        return sum(1 for p in self.pasos_que_sostienen if p.hace_aparecer_netamente)

    @property
    def pasos_que_hacen_desaparecer_netamente_en_la_maniobra(self) -> int:
        return sum(1 for p in self.pasos_que_sostienen if p.hace_desaparecer_netamente)

    @property
    def clusters_sin_nombrar_en_la_maniobra(self) -> int:
        """Clusters `desconocida` acumulados. El excedente de un saldo tiene que SUPERARLOS para
        contar: si no, el veredicto mide el regimen de etiquetado del detector."""
        return self.clusters_en_la_maniobra.get("desconocida", 0)

    @property
    def saldo_neto_de_objetos_en_la_maniobra(self) -> int:
        """Apariciones menos desapariciones sobre los pasos informativos. Positivo = el tablero
        termino con mas objetos de los que tenia."""
        return self.objetos_aparecidos_en_la_maniobra - self.objetos_desaparecidos_en_la_maniobra

    @property
    def pasos_no_mirados_en_la_maniobra(self) -> int:
        """Pasos informativos que el detector NO analizo (`sobreElTope` / `formaIncompatible`).

        No aportan clusters, pero tampoco son evidencia de que no haya pasado nada: son un agujero
        DECLARADO en la medicion de la maniobra."""
        return sum(1 for p in self.pasos_que_sostienen if p.no_mirado)

    @property
    def maniobra_completamente_mirada(self) -> bool:
        """El detector miro TODOS los pasos informativos. Un criterio de saldo no puede afirmar
        nada sobre una maniobra con agujeros: los clusters que faltan podrian ir en cualquier
        direccion. Medido: en el corpus de hoy NINGUN paso previo cae sobre el tope (el mas grande
        cambia 293 celdas contra un tope de 4096), asi que este guard no cambia ningun veredicto
        actual -- existe porque el corpus que el propio BL recomienda capturar SI los va a tener,
        y sin el, el agujero se lee como saldo medido."""
        return self.pasos_no_mirados_en_la_maniobra == 0

    @property
    def oscilacion_de_firmas(self) -> bool:
        """Los pasos INFORMATIVOS van y vuelven entre a lo sumo dos mecanicas. Ver
        `es_oscilacion_de_firmas`: se REPORTA, no gatea.

        Se mide sobre `pasos_que_sostienen` y no sobre `self.pasos` para no contar dos veces lo
        mismo: una animacion en loop ya esta declarada como tal y sus frames ya salieron de los
        informativos. Este numero responde una pregunta distinta -- de los frames que SI se estan
        contando como evidencia, cuantos son un ciclo de dos estados."""
        return es_oscilacion_de_firmas(self.pasos_que_sostienen)

    @property
    def pasos_en_oscilacion(self) -> int:
        """Pasos informativos que forman parte de una oscilacion de dos estados. 0 si no la hay."""
        return len(self.pasos_que_sostienen) if self.oscilacion_de_firmas else 0

    @property
    def firmas_distintas_en_la_maniobra(self) -> int:
        return len(set(self.firmas_en_la_maniobra))

    @property
    def firma_dominante_en_la_maniobra(self) -> str | None:
        """La firma que mas pasos informativos repite, o None si no hay pasos informativos.

        No es un criterio de objetivo: es lo que permite preguntar si DOS TRANSICIONES DISTINTAS
        se resolvieron repitiendo la misma mecanica, que es la evidencia de generalizacion que
        pide BL.21765. Empate: gana el nombre menor, para que la salida sea determinista."""
        firmas = self.firmas_en_la_maniobra
        if not firmas:
            return None
        conteo: dict[str, int] = {}
        for firma in firmas:
            conteo[firma] = conteo.get(firma, 0) + 1
        return min(conteo, key=lambda f: (-conteo[f], f))

    @property
    def pasos_con_la_firma_dominante(self) -> int:
        dominante = self.firma_dominante_en_la_maniobra
        if dominante is None:
            return 0
        return sum(1 for f in self.firmas_en_la_maniobra if f == dominante)

    def a_json(self) -> dict[str, Any]:
        return {
            "framesPrevios": self.frames_previos,
            "ventanaTruncada": self.ventana_truncada,
            "pasosPrevios": len(self.pasos),
            "pasosInertes": self.pasos_inertes,
            "pasosEnAnimacion": self.pasos_en_animacion,
            "pasosInformativos": self.pasos_informativos,
            "animacionEnLoop": self.animacion_en_loop,
            "celdasCambiadasPorPaso": [p.celdas_cambiadas for p in self.pasos],
            "ocupacionDeLaManiobra": [round(o, 4) for o in self.ocupacion],
            "pasosQueSubenLaOcupacion": self.pasos_que_suben_la_ocupacion,
            "pasosQueBajanLaOcupacion": self.pasos_que_bajan_la_ocupacion,
            "lineaBaseDeClickSaturada": self.linea_base_de_click_saturada,
            "vaciadoMonotonoEnLaManiobra": self.vaciado_monotono_en_la_maniobra,
            "llenadoMonotonoEnLaManiobra": self.llenado_monotono_en_la_maniobra,
            "coloresAgotadosEnLaManiobra": list(self.colores_agotados_en_la_maniobra),
            "pasosConTraslacionEnLaManiobra": self.pasos_con_traslacion_en_la_maniobra,
            "coloresAlcanzadosEnLaManiobra": list(self.colores_alcanzados_en_la_maniobra),
            "aproximacionMonotonaEnLaManiobra": list(self.aproximacion_monotona_en_la_maniobra),
            "huboClickDelEvento": self.hubo_click_del_evento,
            "colorBajoElClickPrevio": self.color_bajo_el_click_previo,
            "clicksPrevios": self.clicks_previos,
            "clicksPreviosEnObjeto": self.clicks_previos_en_objeto,
            "firmasEnLaManiobra": list(self.firmas_en_la_maniobra),
            "firmaDominanteEnLaManiobra": self.firma_dominante_en_la_maniobra,
            "pasosConLaFirmaDominante": self.pasos_con_la_firma_dominante,
            "firmasDistintasEnLaManiobra": self.firmas_distintas_en_la_maniobra,
            "maniobraSinFirmasMedidas": self.maniobra_sin_firmas_medidas,
            "sinPasosInformativos": self.sin_pasos_informativos,
            "clustersEnLaManiobra": self.clusters_en_la_maniobra,
            "objetosAparecidosEnLaManiobra": self.objetos_aparecidos_en_la_maniobra,
            "objetosDesaparecidosEnLaManiobra": self.objetos_desaparecidos_en_la_maniobra,
            "pasosQueHacenAparecerEnLaManiobra": self.pasos_que_hacen_aparecer_en_la_maniobra,
            "pasosQueHacenDesaparecerEnLaManiobra": self.pasos_que_hacen_desaparecer_en_la_maniobra,
            # BL.21765 corregido: lo que de verdad leen los criterios, mas los dos numeros sin los
            # cuales un saldo no se puede auditar (cuanto no supo nombrar el detector y cuanto ni
            # siquiera miro).
            "pasosQueHacenAparecerNetamenteEnLaManiobra": (
                self.pasos_que_hacen_aparecer_netamente_en_la_maniobra
            ),
            "pasosQueHacenDesaparecerNetamenteEnLaManiobra": (
                self.pasos_que_hacen_desaparecer_netamente_en_la_maniobra
            ),
            "saldoNetoDeObjetosEnLaManiobra": self.saldo_neto_de_objetos_en_la_maniobra,
            "clustersSinNombrarEnLaManiobra": self.clusters_sin_nombrar_en_la_maniobra,
            "pasosNoMiradosEnLaManiobra": self.pasos_no_mirados_en_la_maniobra,
            "maniobraCompletamenteMirada": self.maniobra_completamente_mirada,
            "oscilacionDeFirmas": self.oscilacion_de_firmas,
            "pasosEnOscilacion": self.pasos_en_oscilacion,
        }


def construir_vista(
    *,
    pasos: Sequence[PasoPrevio],
    ocupacion: Sequence[float],
    colores_agotados: Sequence[int],
    pasos_con_traslacion: int,
    colores_alcanzados: Sequence[int],
    aproximacion_monotona: Sequence[int],
    hubo_click_del_evento: bool = False,
    color_bajo_el_click_previo: int | None = None,
    clicks_previos: int = 0,
    clicks_previos_en_objeto: int = 0,
) -> VistaDeLaManiobra:
    """Arma la vista derivando las monotonias de la ocupacion QUE SE LE PASA.

    El llamador (`caracterizacion_de_niveles.medir_evento`) es responsable de pasar la serie SIN el
    frame del evento; este modulo no puede verificarlo y por eso el contrato esta fijado con un test
    sobre la forma exacta que produjo el artefacto (ocupacion plana + caida en el evento)."""
    return VistaDeLaManiobra(
        frames_previos=len(ocupacion),
        pasos=tuple(pasos),
        ocupacion=tuple(ocupacion),
        vaciado_monotono_en_la_maniobra=tendencia_decreciente(list(ocupacion)),
        llenado_monotono_en_la_maniobra=tendencia_creciente(list(ocupacion)),
        colores_agotados_en_la_maniobra=tuple(colores_agotados),
        pasos_con_traslacion_en_la_maniobra=pasos_con_traslacion,
        colores_alcanzados_en_la_maniobra=tuple(colores_alcanzados),
        aproximacion_monotona_en_la_maniobra=tuple(aproximacion_monotona),
        hubo_click_del_evento=hubo_click_del_evento,
        color_bajo_el_click_previo=color_bajo_el_click_previo,
        clicks_previos=clicks_previos,
        clicks_previos_en_objeto=clicks_previos_en_objeto,
    )


__all__ = [
    "ANCHO_NOMINAL_DE_VENTANA",
    "FIRMA_SIN_MEDIR",
    "MAXIMO_DE_ESTADOS_EN_OSCILACION",
    "TIPOS_DE_CLUSTER",
    "TIPOS_DE_NO_MIRE",
    "MINIMO_DE_PASOS_PARA_LOOP",
    "REPETICIONES_MINIMAS_DE_FIRMA_EN_LOOP",
    "MINIMO_DE_PASOS_QUE_MUEVEN",
    "MINIMO_DE_CLICKS_PREVIOS",
    "PasoPrevio",
    "VistaDeLaManiobra",
    "construir_vista",
    "creciente_monotona",
    "decreciente_monotona",
    "es_animacion_en_loop",
    "es_oscilacion_de_firmas",
    "pasos_que_bajan",
    "pasos_que_suben",
    "sin_variacion",
    "tendencia_creciente",
    "tendencia_decreciente",
]
