"""[arc-agi3-kaggle-agent/scripts/barrido_de_captura] BL.21695 paso 1, RE-PLANIFICADO POR BL.21794 --
corre partidas de CAPTURA y deja una ventana de frames por cada subida de nivel en
`runtime_reports/ventanas/`.

POR QUE CAMBIO EL PLAN (BL.21794). La version de BL.21695 ajustaba el presupuesto de cada juego a
`PASOS_MEDIDOS`, los pasos en los que cada juego subio de nivel en el barrido de 1.600 acciones del
mapa VIEJO. BL.21783 midio de nuevo con el agente y el banco de hoy y dejo dicho, textual, que
"ninguna de las acciones de subida del mapa viejo se reproduce": g50t subia en 154 y ahora sube en
93 con una semilla y en 1.939 con otra; sc25 subia en 1.298/1.375 y ahora en 593/663/734 con una
semilla y 558/1.802 con la otra. Un presupuesto ajustado a numeros que ya no se reproducen no es
ajuste: es azar con dos decimales. Desde este BL el presupuesto es UNO SOLO para todos los juegos
(`ACCIONES_POR_CORRIDA`) y lo que se ajusta es CUANTAS corridas, que es la palanca que la evidencia
sostiene -- el momento de llegada se movio por un factor de 20 entre semillas, o sea que la muestra
la compran las SEMILLAS y no los pasos.

LAS DOS FASES, Y POR QUE LA SEGUNDA ES LA CARA DEL BL.
  - `normal`: la politica entregada, tal cual. Suma transiciones y juegos al corpus.
  - `fondo`: una fraccion de los clicks redirigida al FONDO (`scripts/cobertura_de_fondo.py`). Estas
    partidas PUNTUAN PEOR a proposito. Existen porque `resueltoTocandoUnObjeto` murio 0/14 con
    VARIANZA CERO en su linea base -- en los 6 eventos de click del corpus, TODOS los clicks previos
    cayeron tambien sobre un objeto (ft09 9/9, lp85 9/9, vc33 1/1 y 9/9) -- y un insumo que no toma
    dos valores distintos no puede sostener ni refutar nada. El objetivo de estas corridas es MEDIR.

DISCIPLINA DE CARGA. Un juego por vez, `nice -n 19` en la invocacion, y el barrido ESPERA entre
corridas mientras el ratio de carga (loadavg 1 min / vCPU) supere `--carga-maxima`. El box comparte
6 vCPU con un cron horario de partidas reales contra la API oficial que se saltea con ratio 1,5, y
esa es la unica recoleccion de datos reales del track: preferir tardar a robarle el box. La espera
se reusa de `partida_instrumentada.esperar_a_que_baje_la_carga` -- una sola implementacion de la
cortesia, no dos.

COSTO MEDIDO, NO ESTIMADO. Cada corrida se cronometra con `getrusage(RUSAGE_CHILDREN)` (CPU real del
subproceso, no reloj) y el JSON de salida trae el costo por accion, el factor PARED/CPU y las
ventanas capturadas. `--costo` corre UNA partida corta y reporta ese numero antes de comprometer el
barrido entero: lanzar sin medir es como se perdieron dias de box en BL.21763.

UN ARCHIVO POR CORRIDA, no un JSONL compartido. Las lineas pesan ~80KB (21 frames de 64x64) y
`O_APPEND` solo garantiza atomicidad hasta PIPE_BUF (4KB en Linux): dos procesos escribiendo al
mismo archivo intercalarian bytes y corromperian el corpus. El ingestor acepta un directorio.

Uso:
    .venv/bin/python scripts/barrido_de_captura.py --listar-plan
    .venv/bin/python scripts/barrido_de_captura.py --costo
    nice -n 19 .venv/bin/python scripts/barrido_de_captura.py --json mediciones/BL21794_barrido.json

EL INFORME JSON VA A `mediciones/`, NO A `runtime_reports/` (BL.21798). `runtime_reports/` esta
gitignoreado: el informe de costo de BL.21794 se escribio ahi, se cito en el cierre del BL (22
corridas, 26.400 acciones, 1,6 h de CPU, 0 fallidas) y despues no quedo NADA en el repo que
sostuviera esos numeros -- el archivo ya no existe. Un numero que se va a citar tiene que quedar
versionado; las VENTANAS capturadas si van a `runtime_reports/` porque su destino es la coleccion.
"""
from __future__ import annotations

import argparse
import json
import resource
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from captura_de_niveles import VENTANA_POR_DEFECTO, leer_jsonl  # noqa: E402
from cobertura_de_fondo import FRACCION_POR_DEFECTO, etiqueta_de_corrida  # noqa: E402
from partida_instrumentada import (  # noqa: E402
    CARGA_MAXIMA_POR_DEFECTO,
    esperar_a_que_baje_la_carga,
    ratio_de_carga,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESTINO_POR_DEFECTO = PROJECT_ROOT / "runtime_reports" / "ventanas"

#: Los UNICOS juegos del banco publico con una subida de nivel observada alguna vez (BL.21763 mapa,
#: BL.21783 estrato A). Los otros 19 sacaron 0 niveles ya a 1.600 acciones, y correrlos a 1.200
#: costaria 22.800 acciones (~1,2 h de CPU medido) por un rendimiento esperado que la evidencia
#: disponible pone en cero. Ese recorte se DECLARA en el informe, no se disimula.
JUEGOS_QUE_PUNTUAN: tuple[str, ...] = ("ft09", "g50t", "lp85", "m0r0", "sc25", "vc33")

#: De esos, los que efectivamente CLICKEAN. g50t queda afuera de la fase de fondo con un numero
#: medido: 0 coordenadas distintas clickeadas en 4.001 acciones (BL.21783) -- se juega con flechas,
#: asi que redirigirle clicks al fondo no redirige nada y solo gasta box.
JUEGOS_QUE_CLICKEAN: tuple[str, ...] = ("ft09", "lp85", "m0r0", "sc25", "vc33")

#: Presupuesto de acciones de CADA corrida. 1.200 y no 400 ni 4.000, con la evidencia de BL.21783 al
#: lado: los eventos observados con el agente de hoy caen en 93 (g50t), 128 (ft09), 558-734 (sc25,
#: tres niveles), 68 (lp85) y 2-4 (vc33), o sea que 1.200 cubre TODOS los momentos de llegada
#: observados con margen; y el tramo 1.600 -> 4.000 quedo medido como `dentroDelRuido` (suma UN
#: nivel por semilla con un desvio entre semillas de 1,58), asi que pagar mas profundidad compra
#: ruido. Lo que si compra muestra son mas semillas, y ahi va la CPU.
ACCIONES_POR_CORRIDA = 1200

#: Semillas por juego y por fase. DOS y no una: el momento de llegada se movio por un factor de 20
#: entre semillas en el mismo juego (g50t: accion 1.939 contra 93), asi que una sola semilla por
#: juego tiene un riesgo alto de no capturar un evento que el juego SI produce. Y no cuatro (el N
#: que `presupuesto_de_la_medicion.py` pide para un riesgo de 0,10 con p=0,5): cuatro semillas por
#: juego y por fase son 52.800 acciones, y este box no las paga hoy sin comerse el cron.
SEMILLAS_POR_JUEGO = 2

#: Presupuesto de la corrida de `--costo`. Corto a proposito: mide el costo POR ACCION, que es lo
#: unico que hace falta para planificar, y no cuesta una partida entera averiguarlo.
ACCIONES_DE_LA_MEDICION_DE_COSTO = 150


@dataclass(frozen=True)
class Corrida:
    """Una invocacion de `play_local.py`: un juego, un presupuesto, una semilla y una fase."""

    juego: str
    pasos: int
    semilla: str
    fase: str = "normal"
    fraccion_al_fondo: float = 0.0

    @property
    def etiqueta(self) -> str:
        return f"{self.juego}_{self.fase}_{self.semilla}"


def plan_de_corridas(
    juegos: list[str],
    semillas: int = SEMILLAS_POR_JUEGO,
    pasos: int = ACCIONES_POR_CORRIDA,
    fraccion_al_fondo: float = FRACCION_POR_DEFECTO,
    fases: tuple[str, ...] = ("normal", "fondo"),
) -> list[Corrida]:
    """El plan completo: `semillas` corridas por juego en la fase `normal` y otras tantas en la fase
    `fondo` para los juegos que clickean.

    EL ORDEN ES POR RONDA DE SEMILLA, NO POR JUEGO, y no es cosmetico. En un box compartido el
    barrido se corta: BL.21763 alcanzo a medir UN juego de SEIS. Con el orden por juego, un corte a
    mitad deja el corpus con todas las semillas de los primeros juegos y CERO de los ultimos --
    exactamente el sesgo que este BL vino a sacar ("que ningun tipo quede sostenido por un solo
    mundo"). Con el orden por ronda, la primera ronda ya cubre TODOS los juegos y las DOS fases, y
    cada ronda siguiente solo agrega profundidad de muestra."""
    corridas: list[Corrida] = []
    for n in range(1, semillas + 1):
        for juego in juegos:
            if "normal" in fases:
                corridas.append(
                    Corrida(juego=juego, pasos=pasos, semilla=f"bl21794-n{n}", fase="normal")
                )
            if "fondo" in fases and juego in JUEGOS_QUE_CLICKEAN:
                corridas.append(
                    Corrida(
                        juego=juego,
                        pasos=pasos,
                        semilla=f"bl21794-f{n}",
                        fase="fondo",
                        fraccion_al_fondo=fraccion_al_fondo,
                    )
                )
    return corridas


def _cpu_de_los_hijos() -> float:
    uso = resource.getrusage(resource.RUSAGE_CHILDREN)
    return uso.ru_utime + uso.ru_stime


def correr(corrida: Corrida, destino: Path, ventana: int, python: str) -> dict:
    """Corre UNA partida con captura y devuelve su fila: ventanas capturadas, costo y salida.

    El CPU se mide con `RUSAGE_CHILDREN` y no con el reloj: el reloj de este box mide la carga
    ajena (BL.21763 midio 18,8x de contencion), y un plan hecho con reloj prestado no se puede
    comparar con ningun otro."""
    archivo = destino / f"{corrida.etiqueta}.jsonl"
    comando = [
        "nice",
        "-n",
        "19",
        python,
        str(PROJECT_ROOT / "scripts" / "play_local.py"),
        "--juego",
        corrida.juego,
        "--max-pasos",
        str(corrida.pasos),
        "--presupuesto-horas",
        "0",
        "--semilla",
        corrida.semilla,
        "--capturar-niveles",
        str(archivo),
        "--ventana",
        str(ventana),
    ]
    if corrida.fraccion_al_fondo > 0:
        comando += [
            "--fraccion-de-clicks-al-fondo",
            str(corrida.fraccion_al_fondo),
            "--etiqueta-de-corrida",
            etiqueta_de_corrida(corrida.fraccion_al_fondo),
        ]
    cpu_antes = _cpu_de_los_hijos()
    inicio = time.monotonic()
    proceso = subprocess.run(comando, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    pared = time.monotonic() - inicio
    cpu = _cpu_de_los_hijos() - cpu_antes
    capturadas = len(leer_jsonl(archivo))
    estado = "ok" if proceso.returncode == 0 else f"FALLO({proceso.returncode})"
    fila = {
        "juego": corrida.juego,
        "fase": corrida.fase,
        "semilla": corrida.semilla,
        "acciones": corrida.pasos,
        "fraccionAlFondo": corrida.fraccion_al_fondo,
        "ventanasCapturadas": capturadas,
        "cpuSegundos": round(cpu, 2),
        "paredSegundos": round(pared, 2),
        "cpuPorAccion": round(cpu / max(1, corrida.pasos), 4),
        "factorParedSobreCpu": round(pared / cpu, 2) if cpu > 0 else None,
        "ratioDeCargaAlTerminar": round(ratio_de_carga(), 2),
        "codigoDeSalida": proceso.returncode,
        "archivo": str(archivo),
    }
    print(
        f"[barrido] {corrida.etiqueta:28} {estado}, {capturadas} ventana(s), "
        f"{cpu:.0f}s CPU / {pared:.0f}s pared ({fila['cpuPorAccion']}s por accion)",
        flush=True,
    )
    if proceso.returncode != 0:
        print(proceso.stderr[-2000:], file=sys.stderr)
    return fila


def _medir_costo(destino: Path, ventana: int, python: str) -> dict:
    """UNA partida corta, solo para saber cuanto cuesta el barrido antes de comprometerlo."""
    sonda = Corrida(
        juego="vc33", pasos=ACCIONES_DE_LA_MEDICION_DE_COSTO, semilla="costo", fase="costo"
    )
    fila = correr(sonda, destino, ventana, python)
    return fila


def _resumen(filas: list[dict], plan: list[Corrida]) -> dict:
    cpu = sum(f["cpuSegundos"] for f in filas)
    acciones = sum(f["acciones"] for f in filas)
    return {
        "corridas": len(filas),
        "corridasPlanificadas": len(plan),
        "accionesGastadas": acciones,
        "cpuSegundos": round(cpu, 1),
        "cpuPorAccion": round(cpu / acciones, 4) if acciones else None,
        "ventanasCapturadas": sum(f["ventanasCapturadas"] for f in filas),
        "ventanasPorFase": {
            fase: sum(f["ventanasCapturadas"] for f in filas if f["fase"] == fase)
            for fase in sorted({f["fase"] for f in filas})
        },
        "corridasFallidas": sum(1 for f in filas if f["codigoDeSalida"] != 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Barrido de captura de subidas de nivel (BL.21695, re-planificado por BL.21794)."
    )
    parser.add_argument(
        "--juego",
        default=None,
        help="Ids separados por coma. Sin esto, los 6 juegos con alguna subida de nivel observada.",
    )
    parser.add_argument("--destino", default=str(DESTINO_POR_DEFECTO), help="Directorio de salida.")
    parser.add_argument("--ventana", type=int, default=VENTANA_POR_DEFECTO)
    parser.add_argument("--semillas", type=int, default=SEMILLAS_POR_JUEGO)
    parser.add_argument("--acciones", type=int, default=ACCIONES_POR_CORRIDA)
    parser.add_argument(
        "--fraccion-al-fondo",
        type=float,
        default=FRACCION_POR_DEFECTO,
        help="Fraccion de clicks redirigidos al fondo en la fase `fondo`.",
    )
    parser.add_argument(
        "--fases",
        default="normal,fondo",
        help="Fases a correr: `normal`, `fondo` o las dos.",
    )
    parser.add_argument(
        "--carga-maxima",
        type=float,
        default=CARGA_MAXIMA_POR_DEFECTO,
        help="Ratio de carga (loadavg 1 min / vCPU) por encima del cual el barrido ESPERA antes de "
        "arrancar la corrida siguiente. 0 lo apaga.",
    )
    parser.add_argument("--listar-plan", action="store_true", help="Imprime el plan y sale.")
    parser.add_argument(
        "--costo",
        action="store_true",
        help="Corre UNA partida corta, reporta el costo por accion y sale. Medir antes de lanzar.",
    )
    parser.add_argument(
        "--json",
        default=None,
        help=(
            "Ruta del informe JSON de la corrida. Ponerla en mediciones/ y no en runtime_reports/, "
            "que esta gitignoreado: el informe de costo de BL.21794 se cito en el cierre del BL y "
            "hoy no existe (BL.21798)."
        ),
    )
    parser.add_argument(
        "--python",
        default=str(PROJECT_ROOT / ".venv" / "bin" / "python"),
        help="Interprete con el framework oficial instalado.",
    )
    args = parser.parse_args()

    destino = Path(args.destino)
    destino.mkdir(parents=True, exist_ok=True)

    if args.costo:
        fila = _medir_costo(destino, args.ventana, args.python)
        plan = plan_de_corridas(
            list(JUEGOS_QUE_PUNTUAN),
            args.semillas,
            args.acciones,
            args.fraccion_al_fondo,
            tuple(f.strip() for f in args.fases.split(",") if f.strip()),
        )
        acciones = sum(c.pasos for c in plan)
        cpu = acciones * fila["cpuPorAccion"]
        factor = fila["factorParedSobreCpu"] or 1.0
        print(
            f"\n[barrido] COSTO MEDIDO: {fila['cpuPorAccion']}s de CPU por accion, factor "
            f"PARED/CPU {factor} (ratio de carga {fila['ratioDeCargaAlTerminar']}).\n"
            f"[barrido] El plan completo son {len(plan)} corrida(s) / {acciones} acciones = "
            f"{cpu / 60:.0f} min de CPU y ~{cpu * factor / 60:.0f} min de pared con esta carga."
        )
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(
                json.dumps({"costo": fila, "planCompleto": {"corridas": len(plan), "acciones": acciones}}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return

    juegos = (
        [j.strip() for j in args.juego.split(",") if j.strip()]
        if args.juego
        else list(JUEGOS_QUE_PUNTUAN)
    )
    fases = tuple(f.strip() for f in args.fases.split(",") if f.strip())
    corridas = plan_de_corridas(
        juegos, args.semillas, args.acciones, args.fraccion_al_fondo, fases
    )
    total_acciones = sum(c.pasos for c in corridas)
    print(f"[barrido] {len(corridas)} corrida(s), {total_acciones} acciones de presupuesto total.")
    for corrida in corridas:
        print(
            f"  {corrida.etiqueta:28} pasos={corrida.pasos:5} fondo={corrida.fraccion_al_fondo:.2f}"
        )
    if args.listar_plan:
        return

    filas: list[dict] = []
    for corrida in corridas:
        esperar_a_que_baje_la_carga(args.carga_maxima)
        filas.append(correr(corrida, destino, args.ventana, args.python))
        if args.json:
            # Volcado PARCIAL tras cada corrida: en un box compartido el barrido puede quedar
            # cortado, y una medicion que solo existe al final es una medicion que se pierde.
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(
                json.dumps(
                    {"corridas": filas, "resumen": _resumen(filas, corridas)},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    resumen = _resumen(filas, corridas)
    print(f"\n[barrido] {json.dumps(resumen, ensure_ascii=False)}")
    print(f"[barrido] Destino: {destino}")


if __name__ == "__main__":
    main()
