"""[arc-agi3-kaggle-agent/scripts/caracterizar_completados] BL.21695 paso 1 + BL.21728 -- INFORME de
los completados PERSISTIDOS: mide cada ventana con `caracterizacion_de_niveles.py` y cuenta en
cuantos de ellos se sostiene cada CANDIDATO a objetivo.

QUE ES Y QUE NO ES. Esto NO decide el vocabulario de objetivos: cuenta evidencia. Cada candidato
tiene un criterio NUMERICO explicito (abajo, `CANDIDATOS`) y el informe dice en cuantos eventos se
cumple, sobre cuantas TRANSICIONES DISTINTAS, y con cuantos frames REALES detras.

LAS CUATRO REGLAS QUE IMPUSO BL.21728, cada una contra un defecto medido del informe anterior:

1. LOS CRITERIOS DE OBJETIVO SE EVALUAN SIN EL FRAME DEL EVENTO. Reciben una `VistaDeLaManiobra` y
   nunca la `MedicionDeEvento` completa, asi que leer el campo que incluye la transicion revienta
   con AttributeError en vez de devolver el artefacto. El defecto: `recolectarTodo` afirmaba "la
   ocupacion bajo de forma monotona" en 6 eventos y la ocupacion era PLANA los 10 frames previos --
   caia SOLO en el frame que DEFINE el evento.

2. LA MUESTRA ES LA PERSISTIDA, SIEMPRE. La entrada es un export de `arcReplayFrames` con
   manifiesto verificado por sha256 (`corpus_persistido.py`); no hay forma de correr el informe
   sobre un directorio de capturas sueltas. El defecto: el informe declaraba 12 eventos / 7
   transiciones / 5 juegos cuando el corpus persistido eran 14 / 8 / 6.
   CORRECCION: el sha256 ataba el informe al EXPORT y nunca el export a la COLECCION -- un export a
   medias con su manifiesto recalculado pasaba los tres chequeos. Ahora se verifican tambien el
   CENSO (las subidas de nivel contadas por un segundo camino sobre los documentos, lo que el
   filtro de runId dejo afuera) y la ANTIGUEDAD del export, que es la forma exacta que tomo el
   defecto original.

3. `muestraChica` GATEA. Se calcula sobre TRANSICIONES DISTINTAS (no sobre juegos) y decide
   `sobrevive`. El defecto: se imprimia y no cambiaba ningun veredicto.

4. EL INFORME DICE CUANTOS FRAMES REALES SOSTIENEN CADA VEREDICTO, separando informativos de
   INERTES (cero celdas cambiadas: 5 de 9 pasos previos en lp85, 4 de 9 en m0r0) y de ANIMACION EN
   LOOP (ft09: 9 pasos de exactamente 38 celdas con la ocupacion clavada), e imprime `framesAntes`
   -- vc33 nivel 1 tiene 2 y votaba igual que una ventana de 10.
   CORRECCION: el gate era una SUMA sobre todos los sostenidos, asi que un candidato entraba con
   "1 observacion real + 1 vacia". Ahora un evento sin un solo frame informativo NO cuenta para las
   transiciones distintas de un objetivo.

5. SIN MEDIR NO ES REFUTADO (correccion). Cada candidato declara sus `insumos` y el informe mide la
   VARIANZA de cada uno: un 0/N con algun insumo constante no es un descarte, es una medicion que
   la captura no permite hacer. El vocabulario re-derivado devuelve tres listas -- `sobreviven`,
   `refutados` y `sinMedir` -- porque la diferencia decide si el proximo paso es recapturar o
   descartar.

BL.21765 -- LA RE-DERIVACION AHORA CONSUME LAS FIRMAS. Los candidatos y sus gates se mudaron a
`vocabulario_de_objetivos.py` (este modulo IMPRIME y los re-exporta). El defecto que cierra: las
firmas de BL.21741 llegaban a `MedicionDeEvento` y ahi solo las leian DESCRIPTORES, que no entran
al vocabulario; los criterios de objetivo reciben la vista de la maniobra, que no tenia un solo
campo de firma. O sea que el vacio de BL.21728 se midio con una entrada CIEGA a la percepcion que
BL.21741 acababa de arreglar. Ahora cada paso de la maniobra lleva su firma, y el informe agrega
tres cosas: la firma DOMINANTE de la maniobra de cada evento, `juegosDistintos` en cada veredicto
(sobrevivir al gate de muestra y transferir a otro mundo no son la misma afirmacion) y la seccion
COBERTURA, que dice cuantas transiciones distintas quedan cubiertas y cuantas COMPARTEN tipo.

`objetivoDesconocido` no es un residuo vergonzante: es la masa que el posterior de BL.21695 tiene
que reservar con piso, igual que hace `mechanics_posterior.py` (BL.21593) con las mecanicas. Un
vocabulario honesto y chico es MEJOR que uno inflado: repartir masa entre hipotesis infladas es como
se llega a "elegir con confianza la menos mala de las opciones equivocadas".

Uso:
    node scripts/exportar-ventanas-nivel-arc.cjs <dir>     # desde la raiz del monorepo, primero
    .venv/bin/python scripts/caracterizar_completados.py --corpus <dir>
    .venv/bin/python scripts/caracterizar_completados.py --corpus <dir> --json <ruta>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from caracterizacion_de_niveles import MedicionDeEvento, medir_evento  # noqa: E402
from clasificacion_del_corpus import (  # noqa: E402
    auditoria_de_la_clasificacion,
    origen_de_la_muestra,
)
from corpus_persistido import CorpusInvalido, Procedencia, leer_corpus  # noqa: E402
from fragilidad_del_veredicto import (  # noqa: E402
    fragilidad_del_veredicto,
    lineas_de_fragilidad,
)
from linea_de_evento import linea_de_evento  # noqa: E402

# Re-exportados a proposito: los candidatos y sus gates se mudaron a `vocabulario_de_objetivos` por
# tamano (BL.21765) y los llamadores los siguen importando desde aca, que es el punto de entrada.
from vocabulario_de_objetivos import (  # noqa: E402,F401
    CANDIDATOS,
    MECANICAS_DE_OBJETO_UNICA,
    MINIMO_DE_TRANSICIONES,
    NO_MEDIBLES,
    Candidato,
    cobertura_de_transiciones,
    prueba_de,
    resumen_de_candidatos,
    se_sostiene,
    sujeto_de,
    transiciones_distintas,
    vocabulario_rederivado,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORPUS_POR_DEFECTO = PROJECT_ROOT / "runtime_reports" / "corpus"


def cargar_mediciones(
    corpus: Path, permitir_export_viejo: bool = False
) -> tuple[list[MedicionDeEvento], Procedencia, list[dict[str, Any]]]:
    """Mide TODAS las ventanas del corpus persistido. La procedencia viaja con las mediciones para
    que el informe no pueda declarar una muestra que no sea la que midio.

    Las VENTANAS CRUDAS tambien se devuelven (BL.21794): las dos auditorias nuevas -- de que
    poblacion sale cada ventana y si la clase de frame que trae el corpus coincide con la
    re-derivada -- miran campos que `MedicionDeEvento` no lleva, y volver a leer el export por
    separado abriria la puerta a que el informe audite un corpus distinto del que midio."""
    ventanas, procedencia = leer_corpus(corpus, permitir_export_viejo=permitir_export_viejo)
    mediciones = [m for m in (medir_evento(v) for v in ventanas) if m is not None]
    return mediciones, procedencia, ventanas


def _imprimir_muestra_y_clasificacion(ventanas: list[dict[str, Any]]) -> dict[str, Any]:
    """BL.21794 -- las dos auditorias que van ANTES de cualquier veredicto.

    Se imprimen primero por la misma razon por la que la procedencia va arriba: un numero de
    candidatos sin saber de que poblacion salio la muestra, y sin saber si la clasificacion de
    frames es del corpus o reconstruida, se lee como si las dos preguntas ya estuvieran contestadas."""
    origen = origen_de_la_muestra(ventanas)
    clasificacion = auditoria_de_la_clasificacion(ventanas)

    print("\n=== DE QUE POBLACION SALE LA MUESTRA (BL.21794) ===")
    print(
        f"  politica ENTREGADA: {origen['ventanasDePoliticaEntregada']} ventana(s), "
        f"{len(origen['transicionesDePoliticaEntregada'])} transicion(es), "
        f"juegos={origen['juegosDePoliticaEntregada']}"
    )
    print(
        f"  cobertura de FONDO forzada (corridas de MEDICION, puntuan peor a proposito): "
        f"{origen['ventanasConCoberturaDeFondo']} ventana(s), "
        f"{len(origen['transicionesConCoberturaDeFondo'])} transicion(es), "
        f"juegos={origen['juegosConCoberturaDeFondo']}"
    )
    print(
        f"  transiciones que SOLO existen gracias a la fase de fondo: "
        f"{origen['transicionesQueSoloExistenConFondo'] or 'ninguna'}"
    )
    # BL.21798 -- cuales de estas ventanas se pueden VOLVER A PRODUCIR. Va aca arriba, junto a la
    # procedencia, porque una receta de reproduccion que no regenera la muestra es un defecto de la
    # MUESTRA y no una nota al pie.
    print(
        f"  semilla declarada: {origen['ventanasConSemillaDeclarada']} ventana(s) la traen, "
        f"{origen['ventanasSinSemillaDeclarada']} NO (capturadas antes de BL.21798 o sin "
        f"--semilla) | semillas={origen['semillasDeclaradas'] or 'ninguna'}"
    )
    print("  una ventana sin semilla declarada NO se puede regenerar: el runId lleva el LOTE, y el")
    print("  lote no siembra nada desde e7f70322d1.")

    print("\n=== CLASIFICACION DE FRAMES: DEL CORPUS O RECONSTRUIDA (BL.21794) ===")
    print(
        f"  {clasificacion['framesConClaseDeLaCaptura']}/{clasificacion['framesDelCorpus']} "
        f"frame(s) traen la clase decidida EN LA CAPTURA | "
        f"{clasificacion['ventanasConClaseDeLaCaptura']} ventana(s) clasificadas, "
        f"{clasificacion['ventanasSinClasificar']} sin clasificar (capturadas antes de BL.21794)"
    )
    print(f"  reparto por clase en el corpus: {clasificacion['conteoPorClase'] or '{}'}")
    print(
        f"  ACUERDO con la re-derivacion (solo frames de maniobra): "
        f"{clasificacion['framesDeManiobraQueCoinciden']}/"
        f"{clasificacion['framesDeManiobraComparables']} = {clasificacion['acuerdo']}"
    )
    # BL.21798: la captura persiste DOS campos por frame y hasta este BL se chequeaba uno solo.
    print(
        f"  ACUERDO de la FIRMA del paso (BL.21741, el otro campo persistido): "
        f"{clasificacion['framesDeManiobraConFirmaQueCoincide']}/"
        f"{clasificacion['framesDeManiobraConFirmaComparable']} = "
        f"{clasificacion['acuerdoDeFirmas']} | "
        f"{clasificacion['framesConFirmaDeLaCaptura']} frame(s) traen firma de la captura"
    )
    for detalle in clasificacion["discrepanciasDeFirma"]:
        print(f"    DISCREPA LA FIRMA {detalle}")
    print("  los veredictos de abajo los sigue calculando la RE-DERIVACION: la clase guardada es un")
    print("  CHEQUEO de dos caminos, del mismo tipo que el censo del exportador, y una discrepancia")
    print("  puede ser legitima (el export recorta las ventanas por bloques contiguos de stepNum).")
    for detalle in clasificacion["discrepancias"]:
        print(f"    DISCREPA {detalle}")

    return {"origenDeLaMuestra": origen, "clasificacionDeFrames": clasificacion}


def imprimir_informe(
    mediciones: list[MedicionDeEvento],
    procedencia: Procedencia,
    ventanas: list[dict[str, Any]],
) -> dict[str, Any]:
    """FALLA CERRADO SI NO RECIBE LAS VENTANAS (correccion de BL.21798, RFM-02).

    `ventanas` era opcional (`= None`) y las dos auditorias de BL.21794 -- de que poblacion sale la
    muestra y si la clasificacion de frames es del corpus o reconstruida -- se volvian un no-op
    silencioso: medido, el informe imprimia "0/0 frame(s) traen la clase decidida EN LA CAPTURA",
    "0 sin clasificar", "ACUERDO ... = None" y "transiciones que SOLO existen gracias a la fase de
    fondo: ninguna", y el numero que decide se seguia imprimiendo igual. Peor que un cero:
    `ventanasSinClasificar = len(ventanas) - clasificadas` daba 0, que se LEE como "todo
    clasificado". Una auditoria que existe para decir si un dato es del corpus o reconstruido no
    puede dar verde cuando su fuente no esta.

    El chequeo no es "la lista no esta vacia" sino contra el MANIFIESTO: `procedencia.ventanas` es
    lo que el export declara, asi que una lista parcial tampoco pasa."""
    if len(ventanas) != procedencia.ventanas:
        raise ValueError(
            f"[informe] recibi {len(ventanas)} ventana(s) crudas y el manifiesto del corpus declara "
            f"{procedencia.ventanas}. Las auditorias de procedencia y de clasificacion de frames "
            "necesitan las ventanas del MISMO export que se midio; sin ellas imprimirian ceros "
            "indistinguibles de 'no habia nada que auditar'. Pasa el tercer valor que devuelve "
            "`cargar_mediciones`."
        )
    por_juego: dict[str, int] = {}
    for medicion in mediciones:
        por_juego[medicion.juego] = por_juego.get(medicion.juego, 0) + 1
    distintas = transiciones_distintas(mediciones)

    print("=== PROCEDENCIA DEL CORPUS (no es un archivo intermedio: es lo persistido) ===")
    print(
        f"  origen: {procedencia.origen} en {procedencia.host}/{procedencia.base_de_datos} | "
        f"{procedencia.documentos_leidos} documento(s), {procedencia.documentos_con_nivel} con "
        f"levelsCompleted>0 | {len(procedencia.corridas)} corrida(s)"
    )
    # LA REGLA QUE DEFINE LA MUESTRA, IMPRESA (correccion de BL.21728): la linea de arriba decia
    # "277 documento(s)" de una coleccion de 5.817 sin decir por que regla quedaron afuera los
    # otros 5.540. Es el mismo tipo de numero sin procedencia que este BL vino a erradicar.
    censo = procedencia.censo
    print(
        f"  seleccion: runId ~ {procedencia.filtro_run_id} sobre "
        f"{censo.get('documentosDeLaColeccion', '?')} documento(s) de la coleccion | "
        f"{censo.get('documentosConNivelFueraDelFiltro', '?')} con levelsCompleted>0 QUEDARON "
        "AFUERA del filtro (si no es 0, el lector fail-closea)"
    )
    print(
        f"  censo directo sobre los documentos: {censo.get('eventosDeSubidaEnLosDocumentos', '?')} "
        f"subida(s) de nivel, {censo.get('subidasSinPredecesor', '?')} sin frame previo persistido "
        "-- contadas por un camino que NO pasa por la reconstruccion de ventanas"
    )
    print(f"  export {procedencia.sha256[:12]}... del {procedencia.exportado_en} (sha256 verificado)")

    print("\n=== COMPLETADOS CAPTURADOS ===")
    print(
        f"eventos medibles: {len(mediciones)} de {procedencia.ventanas} ventana(s) | "
        f"juegos: {len(por_juego)} | TRANSICIONES DISTINTAS (juego, nivel): {len(distintas)}"
    )
    print("  la muestra real es el ultimo numero: varias semillas que superan el MISMO nivel del")
    print("  MISMO juego son una observacion repetida, no varias independientes.")
    for juego, cantidad in sorted(por_juego.items()):
        niveles = sorted(n for j, n in distintas if j == juego)
        print(f"  {juego}: {cantidad} evento(s), niveles alcanzados {niveles}")

    auditorias = _imprimir_muestra_y_clasificacion(ventanas)

    print("\n=== EVENTO POR EVENTO ===")
    for medicion in sorted(mediciones, key=lambda m: (m.juego, m.paso_del_evento)):
        for linea in linea_de_evento(medicion):
            print(linea)

    resumen = resumen_de_candidatos(mediciones)
    print("\n=== CANDIDATOS (sostenidos / medidos, con los frames REALES detras) ===")
    for nombre, datos in resumen.items():
        print(
            f"  [{datos['tipo']:10}] {nombre:26} {datos['eventos']:3}/{datos['deEventos']:<3} "
            f"eventos, {datos['transicionesDistintas']}/{datos['deTransiciones']} transiciones "
            f"distintas, {datos['juegosDistintos']} juego(s)={datos['juegos']}"
        )
        print(
            f"    evaluado sobre: {datos['evaluadoSobre']} | frames reales: "
            f"{datos['framesInformativos']} informativo(s), {datos['framesInertes']} inerte(s), "
            f"{datos['framesEnAnimacion']} de animacion en loop "
            f"({datos['eventosConVentanaTruncada']} evento(s) con ventana truncada, "
            f"{datos['eventosConAnimacionEnLoop']} con animacion en loop)"
        )
        # Lo que la defensa 4 de BL.21728 no podia ver hasta BL.21765: frames que SON un ciclo de
        # dos estados sin ser un loop exacto, y frames que el detector nunca miro.
        print(
            f"    de esos frames informativos: {datos['framesEnOscilacion']} en OSCILACION de dos "
            f"estados ({datos['eventosConOscilacionDeFirmas']} evento(s)) y "
            f"{datos['framesNoMirados']} que el detector NO MIRO "
            f"({datos['eventosConPasosNoMirados']} evento(s)) | "
            f"{datos['eventosSinPasosInformativos']} evento(s) sin ningun paso informativo, "
            f"{datos['eventosSinFirmasMedidas']} sin firmas medidas"
        )
        print(f"    criterio: {datos['criterio']}")
        if datos["sobrevive"] and datos["sostenidoPorUnSoloJuego"]:
            print(
                "    VEREDICTO: SOBREVIVE al gate de muestra, pero SOLO EN UN JUEGO "
                f"({datos['juegos'][0]}): no hay evidencia de que transfiera a un mundo no visto."
            )
        elif datos["sobrevive"]:
            print("    VEREDICTO: SOBREVIVE Y GENERALIZA ENTRE JUEGOS")
        else:
            print(f"    VEREDICTO: NO SOBREVIVE -- {'; '.join(datos['porQueNoSobrevive']) or 'sin evidencia'}")

    vocabulario = vocabulario_rederivado(resumen)
    print("\n=== VOCABULARIO DE OBJETIVOS RE-DERIVADO ===")
    if vocabulario["sobreviven"]:
        for nombre in vocabulario["sobreviven"]:
            datos = resumen[nombre]
            print(
                f"  SOBREVIVE {nombre}: {datos['transicionesDistintas']} transicion(es) distinta(s), "
                f"juegos={datos['juegos']}, {datos['framesInformativos']} frame(s) informativo(s)"
            )
    else:
        print("  NO SOBREVIVE NINGUN TIPO DE OBJETIVO: toda la masa va a objetivoDesconocido.")
        print(
            f"  Pero el cero se compone: {len(vocabulario['refutados'])} candidato(s) MEDIDO(S) que "
            f"no alcanzan el gate y {len(vocabulario['sinMedir'])} que esta captura NO PUEDE MEDIR "
            "(algun insumo suyo no varia en toda la muestra)."
        )
        print("  Los primeros son un resultado negativo; los segundos, una muestra que falta. Decir")
        print("  'no sostiene ninguna categoria' de los dos juntos sobrevende lo que se demostro.")
    # TRES ESTADOS Y NO DOS (correccion de BL.21728). "Se cayo" y "no se pudo medir" no son lo
    # mismo, y el cierre del BL los presentaba juntos: `recolectarTodo` paso de 6/14 a 0/14 -- ahi
    # habia varianza y el arreglo la refuto -- mientras que `alcanzarDestino` daba 0/14 sin una sola
    # observacion en contra, porque su insumo `aproximacion_monotona_en_la_maniobra` esta vacio en
    # los 14 eventos. Para el proximo paso la diferencia es RECAPTURAR contra DESCARTAR.
    for nombre in vocabulario["refutados"]:
        print(f"  SE CAYO   {nombre}: {'; '.join(resumen[nombre]['porQueNoSobrevive'])}")
    for nombre in vocabulario["sinMedir"]:
        print(
            f"  SIN MEDIR {nombre}: insumo(s) sin varianza en la muestra "
            f"({', '.join(resumen[nombre]['insumosSinVarianza'])}). NO esta descartado: esta "
            "captura no puede evaluarlo, igual que los de la seccion de abajo."
        )
    print(
        f"  de los que sobreviven, GENERALIZAN ENTRE JUEGOS: "
        f"{vocabulario['sobrevivenYGeneralizanEntreJuegos'] or 'ninguno'}"
    )

    # QUE PERCEPCION ESTA CONSUMIENDO ESTA RE-DERIVACION, con la atribucion medida y no supuesta.
    # Va impreso porque la pregunta "esto que decide, lo esta decidiendo con lo que crees?" es la
    # que dejo pasar dos defectos seguidos (BL.21704: un gate midiendo codigo muerto; BL.21728 x
    # BL.21741: un vocabulario re-derivado sobre una vista ciega).
    print("\n=== QUE PERCEPCION CONSUME ESTA RE-DERIVACION (atribucion medida) ===")
    print("  CABLEADO: cada paso de la maniobra lleva su firma (`firma_de_mecanica`, BL.21741) y su")
    print("  desglose de clusters. Los criterios de objetivo los leen -- traza sobre estos mismos")
    print("  eventos: los de saldo tocan clusters_en_la_maniobra, apariciones/desapariciones,")
    print("  clusters_sin_nombrar y, via `no_mirado`, la FIRMA de cada paso.")
    print("  LOAD-BEARING, MEDIDO POR MUTACION SOBRE ESTE CORPUS: lo que mueve veredictos es el")
    print("  DESGLOSE DE CLUSTERS. Colapsar toda firma `compuesta:*` a 'desconocida' -- la percepcion")
    print("  EXACTA previa a BL.21741 -- deja los 6 veredictos IDENTICOS. El desglose por tipo de")
    print("  cluster es dato PRE-BL.21741 (`Mecanica.clusters` ya traia `.tipo`); lo que faltaba era")
    print("  la PLOMERIA hasta `VistaDeLaManiobra`, un agujero independiente del colapso de la firma.")
    print("  La firma compuesta SI puede dar vuelta un veredicto por la deteccion de loop (una serie")
    print("  de celdas constantes se salva de ser 'animacion' solo si sus firmas difieren), pero esa")
    print("  via NO se activa en este corpus. Conclusion honesta: el arreglo de percepcion de")
    print("  BL.21741 NO cambia el vocabulario aca. El limite es la MUESTRA, no la percepcion.")

    cobertura = cobertura_de_transiciones(mediciones, resumen)
    print("\n=== COBERTURA DE LAS TRANSICIONES (las dos preguntas de BL.21765) ===")
    print(
        f"  1. transiciones cubiertas por un tipo que SOBREVIVE: "
        f"{cobertura['transicionesCubiertas']}/{cobertura['transicionesDistintas']}"
    )
    print(
        f"  2. transiciones que COMPARTEN tipo con otra: "
        f"{cobertura['transicionesQueComparten']}/{cobertura['transicionesDistintas']} "
        f"(tipos que cubren mas de una: {cobertura['tiposQueCubrenMasDeUnaTransicion'] or 'ninguno'})"
    )
    print("  un tipo que cubre UNA sola transicion no es vocabulario: es un nombre propio, y los")
    print("  juegos de evaluacion son OTROS.")
    print(
        f"  3. transiciones que un tipo SOSTIENE pero sin un solo frame informativo (no cuentan "
        f"como cobertura, misma regla que el veredicto): "
        f"{cobertura['transicionesSostenidasSinFramesInformativos']}/"
        f"{cobertura['transicionesDistintas']}"
    )
    for transicion, detalle in cobertura["porTransicion"].items():
        print(
            f"  {transicion:16} tipos={detalle['tiposQueLaCubren'] or '[]'} | "
            f"firma del evento={detalle['firmaDelEvento']}"
        )
        print(f"      firma dominante de la maniobra: {detalle['firmaDominanteDeLaManiobra']}")
        if detalle["tiposQueLaSostienenSinFramesInformativos"]:
            print(
                "      SOSTENIDA SIN FRAMES INFORMATIVOS por "
                f"{detalle['tiposQueLaSostienenSinFramesInformativos']}: el criterio se satisface, "
                "pero la maniobra no tiene un solo frame que lo respalde -- no cuenta."
            )

    print("\n=== CANDIDATOS QUE ESTA CAPTURA NO PUEDE MEDIR (no estan descartados) ===")
    for nombre, razon in NO_MEDIBLES.items():
        print(f"  {nombre}: {razon}")

    # EL NUMERO QUE DECIDE (BL.21794). El gate de aceptacion de este BL no es "se capturaron N
    # frames": es cuantos tipos de objetivo sobreviven SOSTENIDOS POR MAS DE UN JUEGO, porque los
    # juegos de evaluacion son OTROS y un tipo sostenido por un solo mundo es un nombre propio. Se
    # imprime ULTIMO y solo, para que no haya que buscarlo entre las otras secciones.
    generalizan = vocabulario["sobrevivenYGeneralizanEntreJuegos"]
    print("\n=== EL NUMERO QUE DECIDE (gate de aceptacion de BL.21794) ===")
    print(
        f"  TIPOS DE OBJETIVO QUE SOBREVIVEN SOSTENIDOS POR MAS DE UN JUEGO: {len(generalizan)}"
        + (f" -> {generalizan}" if generalizan else "")
    )
    print(
        f"  sobre {len(distintas)} transicion(es) distinta(s) de {len(por_juego)} juego(s), "
        f"{len(mediciones)} evento(s) medible(s)."
    )
    if not generalizan:
        print("  CERO. Con esta muestra el planner de BL.21695 no tiene contra que planificar, y la")
        print("  respuesta honesta no es inflar el vocabulario para que algo sobreviva (BL.21593:")
        print("  repartir masa entre hipotesis infladas lleva a elegir con confianza la menos mala")
        print("  de las opciones equivocadas): es que el vocabulario POSTULADO es el equivocado y")
        print("  hay que derivar otro DEL DATO.")

    # DE QUE CORRIDAS DEPENDE ESE NUMERO (BL.21798). Va PEGADO al numero y no en otra seccion: el
    # defecto que corrige es que el "de CERO a UNO" de BL.21794 se leyo como resultado cuando salia
    # entero de dos corridas de fondo -- quitarlas devolvia el gate a CERO y el informe no lo decia
    # porque nadie lo calculaba.
    fragilidad = fragilidad_del_veredicto(mediciones)
    print("\n=== DE QUE CORRIDAS DEPENDE ESE NUMERO (leave-one-run-out, BL.21798) ===")
    for linea in lineas_de_fragilidad(fragilidad):
        print(linea)
    print("  la corrida es el PROXY de la semilla: el corpus guarda el lote en el runId, no la")
    print("  semilla. Esto mide dependencia de CORRIDAS, que es cota inferior de la fragilidad")
    print("  entre semillas -- la varianza del indicador entre semillas sigue SIN medirse.")

    return {
        "procedencia": procedencia.a_json(),
        **auditorias,
        "tiposQueSobrevivenEnMasDeUnJuego": len(generalizan),
        "eventosMedibles": len(mediciones),
        "transicionesDistintas": sorted(f"{j}:nivel{n}" for j, n in distintas),
        "eventosPorJuego": por_juego,
        "candidatos": resumen,
        "vocabularioRederivado": vocabulario,
        "coberturaDeTransiciones": cobertura,
        "fragilidadDelVeredicto": fragilidad,
        "noMedibles": NO_MEDIBLES,
        "eventos": [m.a_json() for m in mediciones],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Informe de completados PERSISTIDOS (BL.21695 + BL.21728)."
    )
    parser.add_argument(
        "--corpus",
        default=str(CORPUS_POR_DEFECTO),
        help="Directorio del export del corpus (ventanas.jsonl + manifiesto.json).",
    )
    parser.add_argument("--json", default=None, help="Ruta donde ademas volcar el informe JSON.")
    parser.add_argument(
        "--permitir-corpus-viejo",
        action="store_true",
        help=(
            "acepta un export mas viejo que MAX_ANTIGUEDAD_DEL_EXPORT. Solo para reproducir una "
            "medicion anterior a proposito: un export viejo es la forma exacta del defecto 2."
        ),
    )
    args = parser.parse_args()

    try:
        mediciones, procedencia, ventanas = cargar_mediciones(
            Path(args.corpus), permitir_export_viejo=args.permitir_corpus_viejo
        )
    except CorpusInvalido as error:
        raise SystemExit(str(error)) from error

    informe = imprimir_informe(mediciones, procedencia, ventanas)

    if args.json:
        destino = Path(args.json)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(informe, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\n[caracterizar] informe JSON en {destino}")


if __name__ == "__main__":
    main()
