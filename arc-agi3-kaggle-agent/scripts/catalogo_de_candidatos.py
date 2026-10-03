"""[arc-agi3-kaggle-agent/scripts/catalogo_de_candidatos] BL.21728 + BL.21765 -- EL CATALOGO: que
categorias se postulan como vocabulario de objetivos, con que criterio EJECUTABLE se decide cada
una y que insumos lee ese criterio.

Vive aparte de `vocabulario_de_objetivos.py` (que es quien DECIDE con ellos) por tamano: ese modulo
cruzo el limite de 500 lineas del repo al agregarsele la varianza de los insumos. Aca esta la
DECLARACION; alla, la maquinaria de veredicto. Ningun import en sentido contrario, para que no haya
ciclo.

LA REGLA QUE NO SE AFLOJA: un candidato existe para ser CONFIRMADO O DESCARTADO con el dato, nunca
para darse por bueno por ser plausible. Por eso cada uno trae (a) un criterio numerico explicito y
(b) `insumos`, la lista de campos que ese criterio lee -- que es lo que le permite al informe
distinguir un candidato REFUTADO de uno que esta SIN MEDIR porque sus insumos no varian en la
muestra (correccion de BL.21728: el cierre presentaba las dos cosas como el mismo 0/14).

Stdlib pura. SOLO REPO."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from arc_agent.world_model.mechanics_signature import es_firma_de_silencio  # noqa: E402
from maniobra_previa import MINIMO_DE_PASOS_QUE_MUEVEN  # noqa: E402


@dataclass(frozen=True)
class Candidato:
    """Un candidato a vocabulario con su criterio ejecutable.

    `tipo` separa dos cosas que NO son lo mismo, y de ahi sale QUE recibe `prueba`:
      - OBJETIVO: hipotesis sobre que hay que LOGRAR. Recibe `VistaDeLaManiobra` -- lo que se puede
        afirmar mirando solo los frames ANTERIORES al evento. Si el criterio necesitara el frame del
        evento para dar True, esta describiendo el desenlace y no la meta.
      - DESCRIPTOR: describe el desenlace o la maniobra y no postula meta alguna. Recibe la
        `MedicionDeEvento` completa porque de eso habla. Un evento que solo satisface descriptores
        es, para lo que este BL necesita, un objetivo DESCONOCIDO."""

    tipo: str
    criterio: str
    prueba: Callable[[Any], bool]
    #: Campos del sujeto que el criterio LEE. No es documentacion: con ellos el informe puede
    #: distinguir un candidato REFUTADO (sus insumos variaron y aun asi nunca dio True) de uno SIN
    #: MEDIR (sus insumos son constantes en todo el corpus, asi que el criterio nunca tuvo con que
    #: dar True ni False). Ver `_varianza_de_los_insumos`.
    insumos: tuple[str, ...] = ()

    @property
    def se_evalua_sobre(self) -> str:
        return "maniobra" if self.tipo == "objetivo" else "evento"


#: Prefijos de firma que nombran UNA mecanica de objeto unica. Todo lo demas (`compuesta:`,
#: `sobreElTope`, `formaIncompatible`, `desconocida`) NO lo es -- BL.21741.
MECANICAS_DE_OBJETO_UNICA: tuple[str, ...] = (
    "traslacion:",
    "recoloreo:",
    "aparicion:",
    "desaparicion:",
)

#: Candidatos a vocabulario de objetivos, con su criterio MEDIBLE. Los nombres salen del enunciado
#: de BL.21695 y estan aca para ser CONFIRMADOS O DESCARTADOS con el dato -- ninguno se da por bueno
#: por ser plausible.
CANDIDATOS: dict[str, Candidato] = {
    # INTERSECCION y no dos condiciones sueltas: el color del PROPIO objeto movil siempre esta a
    # distancia 0 de si mismo, asi que "hay algun color alcanzado" se cumple siempre y no dice nada.
    # Exigir que el MISMO color haya sido alcanzado Y se haya acercado de forma monotona deja fuera
    # ese caso trivial (una distancia constante en 0 nunca es estrictamente decreciente).
    "alcanzarDestino": Candidato(
        "objetivo",
        "en la MANIOBRA previa el objeto movil se acerco monotonamente a un color y quedo a <=1 "
        "celda de ESE color, ANTES del frame del evento",
        lambda v: v.pasos_con_traslacion_en_la_maniobra > 0
        and bool(
            set(v.colores_alcanzados_en_la_maniobra) & set(v.aproximacion_monotona_en_la_maniobra)
        ),
        insumos=(
            "pasos_con_traslacion_en_la_maniobra",
            "colores_alcanzados_en_la_maniobra",
            "aproximacion_monotona_en_la_maniobra",
        ),
    ),
    "recolectarTodo": Candidato(
        "objetivo",
        "DURANTE la maniobra un color se quedo sin componentes y la ocupacion del tablero bajo de "
        "forma monotona -- sin contar el frame del evento, que en 6 de 6 casos era el unico que "
        "bajaba",
        lambda v: bool(v.colores_agotados_en_la_maniobra) and v.vaciado_monotono_en_la_maniobra,
        insumos=("colores_agotados_en_la_maniobra", "vaciado_monotono_en_la_maniobra"),
    ),
    # ATRIBUCION CORREGIDA (refutacion medida de BL.21728). El cierre del BL decia "`pintarRegion`
    # queda en 1 transicion (g50t crecia por UN salto de +0,58pp y ocho pasos planos...)", que se
    # lee como que la transicion sobreviviente es la de g50t. Es al reves: corriendo el informe
    # sobre el corpus persistido, la unica transicion que queda es **m0r0** -- g50t sostenia el
    # criterio VIEJO (el que incluia el frame del evento) y cae a 0 con el arreglo, mientras que
    # m0r0 daba False CON ese frame adentro y queda en pie sin el. Recomputando el criterio viejo
    # sobre los mismos 14 eventos: 4/14 en 3 transiciones (ft09-no, g50t, sc25, vc33). Repetir en
    # el acta que cierra el BL el mismo tipo de error que el BL vino a corregir -- una atribucion
    # escrita a mano que el programa desmiente -- es la sobreafirmacion que hay que evitar.
    "pintarRegion": Candidato(
        "objetivo",
        "la fraccion de celdas no-fondo crecio de forma monotona DURANTE la maniobra, sin contar "
        "el frame del evento",
        lambda v: v.llenado_monotono_en_la_maniobra,
        insumos=("llenado_monotono_en_la_maniobra",),
    ),
    # --- BL.21765: las MISMAS dos categorias, medidas por OBJETOS en vez de por `fraccion_no_fondo`.
    # No son categorias nuevas. El cambio de instrumento no es cosmetico: la ocupacion es un escalar
    # GLOBAL sobre celdas y en el corpus esta clavada durante toda la maniobra en 12 de los 14
    # eventos, asi que no puede distinguir "el agente esta sacando objetos del tablero" de "no pasa
    # nada". El desglose de clusters por tipo es la medicion objeto-centrica de lo mismo. Ambas
    # variantes quedan en el informe a proposito: el contraste entre las dos ES el resultado.
    #
    # DE DONDE SALE EL INSTRUMENTO, CON LA ATRIBUCION CORRECTA. Lo que faltaba era PLOMERIA, no
    # percepcion: `Mecanica.clusters` con su `.tipo` por cluster existe desde ANTES de BL.21741
    # (verificado en `git show 246fc969fc~1` -- ese commit agrego el helper
    # `conteo_de_tipos_de_cluster` como fuente unica y la firma COMPUESTA, sobre el mismo dato), y
    # el agujero real era que ese desglose no llegaba a `VistaDeLaManiobra`, que es lo unico que
    # reciben los criterios de objetivo. MEDIDO con mutacion sobre el corpus persistido: colapsar
    # TODA firma `compuesta:*` a "desconocida" -- exactamente la percepcion previa a BL.21741 --
    # deja los 6 veredictos IDENTICOS; vaciar los clusters los cambia. O sea que estos dos criterios
    # se pueden reproducir con la percepcion de BL.21728 y NO son evidencia de que el arreglo de
    # BL.21741 desbloquee vocabulario. La firma SI es load-bearing en otros dos lugares del camino
    # (`es_animacion_en_loop` y el guard `maniobra_completamente_mirada`), y el test de
    # caracterizacion de BL.21765 fija las dos mitades para que nadie vuelva a afirmar la de mas.
    "recolectarTodoPorObjetos": Candidato(
        "objetivo",
        "en la maniobra hubo al menos "
        f"{MINIMO_DE_PASOS_QUE_MUEVEN} pasos informativos con SALDO NETO negativo de objetos (mas "
        "clusters que se van que los que llegan, EN ESE MISMO PASO), el saldo de toda la maniobra "
        "supera a los clusters que el detector no supo nombrar, y no quedo ningun paso sin mirar",
        lambda v: v.maniobra_completamente_mirada
        and v.pasos_que_hacen_desaparecer_netamente_en_la_maniobra >= MINIMO_DE_PASOS_QUE_MUEVEN
        and -v.saldo_neto_de_objetos_en_la_maniobra > v.clusters_sin_nombrar_en_la_maniobra,
        insumos=(
            "maniobra_completamente_mirada",
            "pasos_que_hacen_desaparecer_netamente_en_la_maniobra",
            "saldo_neto_de_objetos_en_la_maniobra",
            "clusters_sin_nombrar_en_la_maniobra",
        ),
    ),
    "pintarRegionPorObjetos": Candidato(
        "objetivo",
        "espejo del anterior: al menos "
        f"{MINIMO_DE_PASOS_QUE_MUEVEN} pasos informativos con SALDO NETO positivo de objetos, saldo "
        "de la maniobra por encima de los clusters sin nombrar, y ningun paso sin mirar",
        lambda v: v.maniobra_completamente_mirada
        and v.pasos_que_hacen_aparecer_netamente_en_la_maniobra >= MINIMO_DE_PASOS_QUE_MUEVEN
        and v.saldo_neto_de_objetos_en_la_maniobra > v.clusters_sin_nombrar_en_la_maniobra,
        insumos=(
            "maniobra_completamente_mirada",
            "pasos_que_hacen_aparecer_netamente_en_la_maniobra",
            "saldo_neto_de_objetos_en_la_maniobra",
            "clusters_sin_nombrar_en_la_maniobra",
        ),
    ),
    "resueltoTocandoUnObjeto": Candidato(
        "objetivo",
        "el paso que subio el nivel fue un CLICK que, EN LA GRILLA PREVIA, cayo sobre una "
        "componente (no sobre el fondo) Y ADEMAS la linea base NO esta saturada: hubo clicks "
        "previos que cayeron sobre el fondo. Sin esa segunda mitad el rasgo tiene varianza cero "
        "-- si TODOS los clicks del episodio caen sobre objetos, el que gano no se distingue en "
        "nada de los que no ganaron, y el criterio afirma algo que se cumple siempre",
        lambda v: v.hubo_click_del_evento
        and v.color_bajo_el_click_previo is not None
        and not v.linea_base_de_click_saturada,
        insumos=(
            "hubo_click_del_evento",
            "color_bajo_el_click_previo",
            "linea_base_de_click_saturada",
        ),
    ),
    "transicionDePantalla": Candidato(
        "descriptor",
        "el evento reescribio >=50% de la grilla: el tablero se rehizo, no dice CUAL era la meta",
        lambda m: m.pantalla_nueva,
        insumos=("pantalla_nueva",),
    ),
    "cadenaDeRecoloreo": Candidato(
        "descriptor",
        "las mecanicas previas al evento fueron recoloreos encadenados (un color que cicla)",
        lambda m: sum(1 for f in m.firmas_previas if f.startswith("recoloreo:")) >= 2,
        insumos=("firmas_previas",),
    ),
    "eventoSinMecanicaDeObjeto": Candidato(
        "descriptor",
        "la transicion del evento no es UNA mecanica de objeto unica (ni traslacion ni recoloreo "
        "ni aparicion/desaparicion homogeneos): es una mezcla, y desde BL.21741 la firma compuesta "
        "dice DE QUE mezcla se trata en vez de decir 'desconocida'",
        lambda m: not m.firma_del_evento.startswith(MECANICAS_DE_OBJETO_UNICA),
        insumos=("firma_del_evento",),
    ),
    # CORRECCION DE BL.21741 (defecto medido aguas abajo). `eventoSinMecanicaDeObjeto` excluye TODO
    # `compuesta:` en bloque, asi que no puede distinguir `compuesta:desconocida=1` -- nada nombrado,
    # el silencio con otro deletreo -- de
    # `compuesta:aparicion=10+,desaparicion=4-9,desconocida=4-9,recoloreo=1`, que nombra cuatro
    # tipos. Esa es EXACTAMENTE la distincion que BL.21741 dice haber comprado, y el informe la
    # perdia. Este descriptor la publica leyendo `es_firma_de_silencio`, la fuente unica del modulo
    # de percepcion. Medido sobre el corpus: 3 eventos (las tres capturas de vc33) sobre 2
    # transiciones distintas.
    "eventoSinNingunaMecanicaNombrada": Candidato(
        "descriptor",
        "la firma del evento NO NOMBRA NINGUNA mecanica: es `desconocida`, uno de los dos tipos de "
        "'no mire', o una compuesta cuyos componentes son todos `desconocida`. Es el silencio del "
        "detector con cualquiera de sus tres deletreos -- distinto de una mezcla que SI nombra "
        "tipos, que es informacion",
        lambda m: es_firma_de_silencio(m.firma_del_evento),
        insumos=("firma_del_evento",),
    ),
    "eventoSobreElTopeDeMecanica": Candidato(
        "descriptor",
        "el evento cambio mas de MAX_CELDAS_CAMBIADAS celdas: `detectar_mecanica` NO MIRO esa "
        "transicion y lo dice con el tipo `sobreElTope` (BL.21741); no confundir con haber mirado "
        "y no haber encontrado nada",
        lambda m: m.sobre_el_tope_de_mecanica,
        insumos=("sobre_el_tope_de_mecanica",),
    ),
}

#: Candidatos que BL.21695 enumera y que esta captura NO puede medir. Estan aca EXPLICITAMENTE, con
#: la razon, para que el informe no de la falsa impresion de haber cubierto el espacio: un candidato
#: ausente del informe se lee como "descartado", y estos no estan descartados -- estan sin medir.
NO_MEDIBLES: dict[str, str] = {
    "emparejarUOrdenar": "haria falta un detector de EQUIVALENCIA entre regiones (dos zonas que se "
    "igualan). No existe en world_model/ y escribirlo seria percepcion nueva, fuera de alcance.",
    "secuenciaCorrecta": "el orden de las pulsaciones no se lee de la grilla: haria falta cruzar la "
    "ventana con el historial completo de acciones del episodio, que la captura no guarda.",
    "evitarOSobrevivir": "es un objetivo NEGATIVO: se manifiesta en los episodios que NO suben de "
    "nivel (GAME_OVER), y esta captura solo graba subidas de nivel. Muestra estructuralmente vacia.",
}
