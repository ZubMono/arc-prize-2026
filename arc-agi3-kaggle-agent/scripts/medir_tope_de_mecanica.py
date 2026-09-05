"""[arc-agi3-kaggle-agent/scripts/medir_tope_de_mecanica] BL.21728 + BL.21741 -- EL EXPERIMENTO que
decide donde va `MAX_CELDAS_CAMBIADAS` y, sobre todo, si la percepcion objeto-centrica DISTINGUE
las subidas de nivel entre si.

DE DONDE SALE EL CORTE. `MAX_CELDAS_CAMBIADAS = 2048` aparece en BL.21561 con el comentario "un
frame que cambia entero (RESET, cambio de nivel) no es una mecanica de objeto". El commit cita
mediciones para lo que SI midio (290 traslaciones, mapeo canonico de direcciones en 3 juegos) y
NINGUNA para el tope. 2048 es exactamente la MITAD de una grilla 64x64: un numero redondo elegido a
ojo, sin experimento detras y sin ningun test que lo fije.

LO QUE MIDIO BL.21728 Y HAY QUE SEGUIR PUDIENDO REPRODUCIR. Con la percepcion de BL.21561,
`firma_del_evento` valia "desconocida" en 14 de 14 eventos del corpus persistido, y levantar el tope
al tamano completo de la grilla cambiaba la firma en 0 de 14. O sea: el tope NO era la causa de la
ceguera. La causa estaba aguas arriba -- la firma global colapsaba a "desconocida" en cuanto los
clusters no eran todos del mismo tipo, y una subida de nivel es SIEMPRE una mezcla. `--legado`
reproduce ese numero con la firma vieja, para que el diagnostico se pueda volver a verificar.

QUE MIDE AHORA (BL.21741). Con la firma arreglada (tipo propio `sobreElTope` para "no mire", firma
COMPUESTA para las mezclas), la pregunta del tope pasa a tener respuesta medible, y es OTRA que la
de antes: cuantas de las 8 transiciones distintas del corpus quedan con firmas DIFERENTES entre si
segun donde este el corte. Y con ella su riesgo simetrico: cuantas COMPARTEN firma -- una firma
tan fina que hace unico a cada evento memoriza y no generaliza, y los juegos de evaluacion son
otros. Las dos cuentas salen juntas o el numero no significa nada.

EL COSTO SE MIDE INTERLEAVED Y POR MINIMO, no de una pasada. La version anterior de este script
corria primero el tope de produccion sobre los 14 eventos y despues el tope levantado sobre los
mismos 14, y reportaba que levantar el tope SALIA MAS BARATO (4,878s -> 4,447s) -- imposible: con
el tope levantado se hace estrictamente mas trabajo. El "ahorro" era el cache calentado por la
primera pasada. Aca cada par se cronometra `--repeticiones` veces por tope, alternando topes, y se
toma el MINIMO de cada (par, tope): el minimo es el estimador menos contaminado por la contencion
de la maquina, que en este entorno hace variar la misma llamada de 0,079s a 0,897s.

AUN ASI, EL COSTO PIDE LA MAQUINA TRANQUILA. Con otro barrido pesado corriendo en paralelo, ni el
minimo de 2 repeticiones alcanza: una corrida asi midio 7,31s para el tope 2048 contra 7,26s para
4096 -- o sea, el tope mas alto "gratis", que es imposible. Si la tabla de costos muestra un tope
mas alto saliendo mas barato, la medicion es ruido: subir `--repeticiones` y esperar a que baje la
carga. La tabla de DISCRIMINACION, en cambio, es deterministica y no depende de la carga.

Y EL TOTAL TAMPOCO ES EL NUMERO QUE HAY QUE LEER (correccion de BL.21741). Este script publicaba una
MEDIANA por llamada que pasaba de 0,001554 a 0,002938 al subir el tope, casi el doble. Imposible
como senal: solo 6 de los 272 pares del corpus cruzan el corte, o sea que 266 recorren el MISMO
camino con los dos topes y no pueden mover la mediana -- ese 89% era ruido de la maquina. El costo
del tope tiene una forma concreta y muy desigual, y por eso ahora se reporta POR CAMINO DE CODIGO:
los que recorren el mismo camino (donde la diferencia es ruido) y los que cruzan el corte, que
cuestan 85-120 ms cada uno segun la carga y caen EXACTAMENTE en el frame de la subida de nivel.
Amortizado: 1,9-2,8 ms/paso.

Uso:
    python3 scripts/medir_tope_de_mecanica.py --corpus runtime_reports/corpus
    python3 scripts/medir_tope_de_mecanica.py --corpus <dir> --experimento --json <ruta>
    python3 scripts/medir_tope_de_mecanica.py --corpus <dir> --legado   # el 14/14 de BL.21728

Stdlib pura. SOLO REPO."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from arc_agent.world_model import object_mechanics  # noqa: E402
from arc_agent.world_model import mechanics_signature  # noqa: E402
from arc_agent.world_model.mechanics_signature import (  # noqa: E402
    PREFIJO_DE_FIRMA_COMPUESTA,
    es_firma_de_silencio,
)
# FUENTE UNICA (correccion de BL.21728): `indice_del_evento` y `celdas_cambiadas` estaban
# reimplementados aca. La copia de `celdas_cambiadas` era ademas PEOR que la canonica -- tomaba
# alto/ancho de `post` e indexaba `pre` sin el guard de dimensiones distintas, o sea IndexError o
# conteo mal ante una subida de nivel que cambia el tamano de la grilla.
from caracterizacion_de_niveles import celdas_cambiadas, indice_del_evento  # noqa: E402
from corpus_persistido import CorpusInvalido, etiqueta_de_transicion, leer_corpus  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORPUS_POR_DEFECTO = PROJECT_ROOT / "runtime_reports" / "corpus"

#: Topes que compara el experimento. 4096 es la grilla 64x64 ENTERA (o sea: sin tope efectivo);
#: 2048 es el corte historico; 1024 y 3072 estan para que la curva tenga forma y no dos puntos.
TOPES_DEL_EXPERIMENTO: tuple[int, ...] = (1024, 2048, 3072, 4096)

#: El corte historico de BL.21561, contra el que se mide el RIESGO de haberlo movido.
TOPE_HISTORICO: int = 2048

def _firma_legado(mecanica: object_mechanics.Mecanica) -> str:
    """La firma ANTERIOR a BL.21741, reimplementada aca para poder reproducir el 14/14 de BL.21728
    sin resucitar el codigo viejo. Los tres silencios y la mezcla eran la misma palabra."""
    firma = mechanics_signature.firma_de_mecanica(mecanica)
    if es_firma_de_silencio(firma) or firma.startswith(PREFIJO_DE_FIRMA_COMPUESTA):
        return "desconocida"
    return firma


def _pares_del_evento(ventanas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Un registro por SUBIDA DE NIVEL: el par (frame previo, frame del evento)."""
    pares: list[dict[str, Any]] = []
    for ventana in ventanas:
        frames = ventana.get("frames") or []
        indice = indice_del_evento(frames, ventana.get("pasoDelEvento", -1))
        if indice <= 0:
            continue
        pares.append(
            {
                "transicion": etiqueta_de_transicion(ventana),
                "juego": ventana.get("juego"),
                "nivelNuevo": ventana.get("nivelNuevo"),
                "pasoDelEvento": ventana.get("pasoDelEvento"),
                "pre": frames[indice - 1]["grilla"],
                "post": frames[indice]["grilla"],
            }
        )
    return pares


def _todos_los_pares(ventanas: list[dict[str, Any]]) -> list[tuple[Any, Any]]:
    """TODOS los pares consecutivos del corpus, no solo los del evento. El costo del tope se paga
    en cada paso de la partida, asi que medirlo solo sobre los 14 frames mas grandes exagera el
    precio por un factor igual a la longitud de la ventana."""
    pares: list[tuple[Any, Any]] = []
    for ventana in ventanas:
        frames = ventana.get("frames") or []
        for i in range(1, len(frames)):
            pares.append((frames[i - 1]["grilla"], frames[i]["grilla"]))
    return pares


def _discriminacion(filas: list[dict[str, Any]]) -> dict[str, Any]:
    """Las DOS cuentas que definen si la firma paga, juntas y nunca una sola.

    `transicionesConFirmaPropia` es cuantas de las transiciones distintas quedan con una firma que
    ninguna otra transicion comparte. `transicionesQueComparten` es su riesgo simetrico: los grupos
    de transiciones que caen en la MISMA firma. Un detector que da una firma unica por evento tiene
    la primera cuenta perfecta y no generaliza a nada."""
    por_transicion: dict[str, set[str]] = {}
    for fila in filas:
        por_transicion.setdefault(fila["transicion"], set()).add(fila["firma"])

    inestables = sorted(t for t, firmas in por_transicion.items() if len(firmas) > 1)
    firma_de: dict[str, str] = {
        t: sorted(firmas)[0] for t, firmas in por_transicion.items() if len(firmas) == 1
    }
    grupos: dict[str, list[str]] = {}
    for transicion, firma in firma_de.items():
        grupos.setdefault(firma, []).append(transicion)

    comparten = sorted(
        (sorted(ts) for ts in grupos.values() if len(ts) > 1), key=lambda ts: ts[0]
    )
    return {
        "transiciones": len(por_transicion),
        "firmasDistintasEntreTransiciones": len(set(firma_de.values())) + len(inestables),
        "transicionesConFirmaPropia": sum(1 for ts in grupos.values() if len(ts) == 1),
        "transicionesQueComparten": comparten,
        "transicionesConFirmaInestable": inestables,
        # CORRECCION DE BL.21741. Antes esta cuenta era
        # `f.startswith(("sobreElTope", "formaIncompatible", "desconocida"))`, y
        # `"compuesta:desconocida=1".startswith(...)` es False: con el tope en 4096 la tabla
        # imprimia "0 transiciones calladas" habiendo DOS (vc33:nivel1 y vc33:nivel2, las dos con
        # firma `compuesta:desconocida=1`), y ese "0" era el unico argumento que separaba 4096 de
        # 3072. Ahora la pregunta la contesta `es_firma_de_silencio`, fuente unica del modulo de
        # percepcion, que si mira DENTRO de la etiqueta compuesta.
        "transicionesEnSilencio": sorted(
            t for t, f in firma_de.items() if es_firma_de_silencio(f)
        ),
        "firmaPorTransicion": {t: sorted(f) for t, f in sorted(por_transicion.items())},
    }


def _costo(pares: list[tuple[Any, Any]], topes: tuple[int, ...], repeticiones: int) -> dict[str, Any]:
    """Segundos por tope sobre TODOS los pares del corpus, alternando topes y quedandose con el
    minimo de cada (par, tope). Ver el encabezado: de una sola pasada, el cache miente.

    SEPARADO POR CAMINO DE CODIGO (correccion de BL.21741). Antes esto publicaba una MEDIANA y una
    MAXIMA por llamada, y la mediana pasaba de 0,001554 a 0,002938 al subir el tope -- casi el
    doble. Imposible como senal: solo 6 de los 272 pares cruzan el corte, o sea que 266 recorren el
    MISMO camino con los dos topes y no pueden mover la mediana; ese 89% era ruido de la maquina.
    El costo del tope tiene una forma muy concreta -- un pico concentrado en el frame de la subida
    de nivel -- y publicar un promedio o una mediana la esconde. Aca se reportan las dos poblaciones
    por separado y el amortizado por paso, que son los tres numeros que describen la distribucion
    real."""
    minimos: dict[int, list[float]] = {tope: [0.0] * len(pares) for tope in topes}
    for i, (pre, post) in enumerate(pares):
        for repeticion in range(repeticiones):
            for tope in topes:
                inicio = time.monotonic()
                object_mechanics.detectar_mecanica(pre, post, max_celdas_cambiadas=tope)
                segundos = time.monotonic() - inicio
                if repeticion == 0 or segundos < minimos[tope][i]:
                    minimos[tope][i] = segundos
    resumen: dict[str, Any] = {"pares": len(pares), "repeticiones": repeticiones, "porTope": {}}
    for tope in topes:
        resumen["porTope"][str(tope)] = {"segundosTotales": round(sum(minimos[tope]), 4)}

    # Las dos poblaciones, contra el corte historico y el vigente: el unico contraste que decide.
    vigente = object_mechanics.MAX_CELDAS_CAMBIADAS
    if TOPE_HISTORICO in minimos and vigente in minimos:
        cruzan = [
            i
            for i, (pre, post) in enumerate(pares)
            if celdas_cambiadas(pre, post) > TOPE_HISTORICO
        ]
        iguales = [i for i in range(len(pares)) if i not in set(cruzan)]
        extra = sum(minimos[vigente][i] for i in cruzan) - sum(minimos[TOPE_HISTORICO][i] for i in cruzan)
        resumen["porCamino"] = {
            "desde": TOPE_HISTORICO,
            "hasta": vigente,
            "mismoCamino": {
                "pares": len(iguales),
                "segundosDesde": round(sum(minimos[TOPE_HISTORICO][i] for i in iguales), 4),
                "segundosHasta": round(sum(minimos[vigente][i] for i in iguales), 4),
            },
            "cruzanElCorte": {
                "pares": len(cruzan),
                "celdas": sorted(celdas_cambiadas(*pares[i]) for i in cruzan),
                "segundosDesde": round(sum(minimos[TOPE_HISTORICO][i] for i in cruzan), 4),
                "segundosHasta": round(sum(minimos[vigente][i] for i in cruzan), 4),
                "msExtraPorPar": round(1000 * extra / len(cruzan), 1) if cruzan else 0.0,
            },
            "msExtraAmortizadoPorPaso": round(
                1000 * (sum(minimos[vigente]) - sum(minimos[TOPE_HISTORICO])) / max(1, len(pares)), 2
            ),
        }
    return resumen


def _riesgo_del_cambio_de_tope(
    pares: list[tuple[Any, Any]], desde: int, hasta: int
) -> dict[str, Any]:
    """EL RADIO DE EXPLOSION de mover el tope, sobre TODOS los pares del corpus y no solo sobre los
    14 eventos: cuantas firmas cambian, y de esas cuantas pasan a `traslacion`.

    `traslacion` es la unica transicion peligrosa: `direction_beliefs.direccion_de_traslacion`
    alimenta el mapeo accion -> direccion SOLO con ese tipo, asi que una traslacion espuria en el
    frame del cambio de nivel ensuciaria el mando. No puede pasar por construccion (un cluster de
    mas de 2 * MAX_TAMANO_OBJETO celdas nunca cabe en `R U (R+d)`), y esta cuenta lo verifica sobre
    el dato en vez de confiar en el argumento."""
    cambian: list[dict[str, Any]] = []
    for pre, post in pares:
        antes = object_mechanics.detectar_mecanica(pre, post, max_celdas_cambiadas=desde)
        despues = object_mechanics.detectar_mecanica(pre, post, max_celdas_cambiadas=hasta)
        firma_antes = mechanics_signature.firma_de_mecanica(antes)
        firma_despues = mechanics_signature.firma_de_mecanica(despues)
        if firma_antes != firma_despues:
            cambian.append(
                {
                    "firmaAntes": firma_antes,
                    "firmaDespues": firma_despues,
                    "tipoDespues": despues.tipo,
                    "celdasCambiadas": despues.celdas_cambiadas,
                }
            )
    return {
        "desde": desde,
        "hasta": hasta,
        "pares": len(pares),
        "paresConFirmaDistinta": len(cambian),
        "paresQuePasanASerTraslacion": sum(
            1 for c in cambian if c["tipoDespues"] == "traslacion"
        ),
        "detalle": cambian,
    }


def medir(
    corpus: Path,
    topes: tuple[int, ...] = TOPES_DEL_EXPERIMENTO,
    repeticiones: int = 3,
    con_costo: bool = True,
    legado: bool = False,
    permitir_export_viejo: bool = False,
) -> dict[str, Any]:
    ventanas, procedencia = leer_corpus(corpus, permitir_export_viejo=permitir_export_viejo)
    eventos = _pares_del_evento(ventanas)
    firma = _firma_legado if legado else mechanics_signature.firma_de_mecanica

    por_tope: dict[str, Any] = {}
    for tope in topes:
        filas: list[dict[str, Any]] = []
        for evento in eventos:
            mecanica = object_mechanics.detectar_mecanica(
                evento["pre"], evento["post"], max_celdas_cambiadas=tope
            )
            filas.append(
                {
                    "transicion": evento["transicion"],
                    "pasoDelEvento": evento["pasoDelEvento"],
                    "celdasCambiadas": mecanica.celdas_cambiadas
                    or celdas_cambiadas(evento["pre"], evento["post"]),
                    "tipo": mecanica.tipo,
                    "firma": firma(mecanica),
                    "tiposDeCluster": mechanics_signature.conteo_de_tipos_de_cluster(mecanica),
                }
            )
        por_tope[str(tope)] = {"eventos": filas, **_discriminacion(filas)}

    resultado: dict[str, Any] = {
        "procedencia": procedencia.a_json(),
        "firma": "legado (pre-BL.21741)" if legado else "vigente (BL.21741)",
        "topeDeProduccion": object_mechanics.MAX_CELDAS_CAMBIADAS,
        "topesComparados": list(topes),
        "eventos": len(eventos),
        "discriminacionPorTope": por_tope,
    }
    if con_costo:
        todos = _todos_los_pares(ventanas)
        resultado["costo"] = _costo(todos, topes, repeticiones)
        resultado["riesgoDelCambioDeTope"] = _riesgo_del_cambio_de_tope(
            todos, TOPE_HISTORICO, object_mechanics.MAX_CELDAS_CAMBIADAS
        )
    return resultado


def imprimir(resultado: dict[str, Any]) -> None:
    print("=== BL.21741: LA FIRMA, ¿DISTINGUE LAS SUBIDAS DE NIVEL ENTRE SI? ===")
    proc = resultado["procedencia"]
    print(
        f"  corpus: {proc['ventanas']} ventana(s), {len(proc['juegos'])} juego(s), "
        f"{len(proc['transicionesDistintas'])} transicion(es) distinta(s) "
        f"(sha256 {proc['sha256'][:12]}..., exportado {proc['exportadoEn']})"
    )
    print(f"  firma medida: {resultado['firma']} | tope de produccion: {resultado['topeDeProduccion']}")
    print("")
    print("  tope | distintas | propia | en silencio | comparten firma | inestables")
    for tope in resultado["topesComparados"]:
        d = resultado["discriminacionPorTope"][str(tope)]
        comparten = "; ".join("+".join(g) for g in d["transicionesQueComparten"]) or "-"
        inestables = ",".join(d["transicionesConFirmaInestable"]) or "-"
        # "En silencio" es la columna que impide leer mal la tabla: una transicion puede quedar con
        # firma PROPIA solo por ser la unica que el tope callo, y esa unicidad se evapora en cuanto
        # aparece un segundo juego por encima del corte.
        silencio = ",".join(d["transicionesEnSilencio"]) or "-"
        print(
            f"  {tope:5} | {d['firmasDistintasEntreTransiciones']:9} | "
            f"{d['transicionesConFirmaPropia']:6} | {silencio:11} | {comparten:15} | {inestables}"
        )

    if "costo" in resultado:
        costo = resultado["costo"]
        print("")
        print(
            f"  costo sobre los {costo['pares']} pares consecutivos del corpus "
            f"(minimo de {costo['repeticiones']} repeticiones interleaved):"
        )
        for tope in resultado["topesComparados"]:
            c = costo["porTope"][str(tope)]
            print(f"    tope {tope:5}: {c['segundosTotales']:8}s totales")
        camino = costo.get("porCamino")
        if camino is not None:
            mismo = camino["mismoCamino"]
            cruzan = camino["cruzanElCorte"]
            print(
                f"    de {camino['desde']} a {camino['hasta']}, POR CAMINO DE CODIGO: "
                f"{mismo['pares']} par(es) con el mismo camino {mismo['segundosDesde']}s -> "
                f"{mismo['segundosHasta']}s (ruido) | {cruzan['pares']} que cruzan el corte "
                f"{cruzan['segundosDesde']}s -> {cruzan['segundosHasta']}s = "
                f"+{cruzan['msExtraPorPar']} ms por par"
            )
            print(
                f"    amortizado: +{camino['msExtraAmortizadoPorPaso']} ms/paso, y el paso caro es "
                "el de la subida de nivel"
            )

    riesgo = resultado.get("riesgoDelCambioDeTope")
    if riesgo is not None:
        print("")
        print(
            f"  radio de explosion de mover el tope de {riesgo['desde']} a {riesgo['hasta']}: "
            f"{riesgo['paresConFirmaDistinta']} de {riesgo['pares']} pares cambian de firma, y "
            f"{riesgo['paresQuePasanASerTraslacion']} pasan a 'traslacion' (el unico tipo que "
            "alimenta el mapeo de direcciones)"
        )

    tope_vigente = str(resultado["topeDeProduccion"])
    detalle = resultado["discriminacionPorTope"].get(tope_vigente)
    if detalle is not None:
        print("")
        print(f"  evento por evento con el tope vigente ({tope_vigente}):")
        for fila in detalle["eventos"]:
            print(
                f"    {fila['transicion']:14} paso={fila['pasoDelEvento']:5} "
                f"celdas={fila['celdasCambiadas']:5} firma={fila['firma']}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Experimento del tope y de la discriminacion de la firma (BL.21728/BL.21741)."
    )
    parser.add_argument("--corpus", default=str(CORPUS_POR_DEFECTO))
    parser.add_argument("--json", default=None)
    parser.add_argument(
        "--experimento",
        action="store_true",
        help="mide tambien el costo por tope sobre todos los pares del corpus",
    )
    parser.add_argument(
        "--legado",
        action="store_true",
        help="usa la firma anterior a BL.21741 (reproduce el 14/14 de 'desconocida')",
    )
    parser.add_argument("--repeticiones", type=int, default=3)
    parser.add_argument(
        "--permitir-corpus-viejo",
        action="store_true",
        help="acepta un export viejo (solo para reproducir una medicion anterior a proposito)",
    )
    args = parser.parse_args()
    try:
        resultado = medir(
            Path(args.corpus),
            repeticiones=max(1, args.repeticiones),
            con_costo=args.experimento,
            legado=args.legado,
            permitir_export_viejo=args.permitir_corpus_viejo,
        )
    except CorpusInvalido as error:
        raise SystemExit(str(error)) from error
    imprimir(resultado)
    if args.json:
        destino = Path(args.json)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps(resultado, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"\n[tope-mecanica] medicion en {destino}")


if __name__ == "__main__":
    main()
