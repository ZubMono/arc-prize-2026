"""[arc-agi3-kaggle-agent/scripts/ablacion_de_palancas] BL.21702 -- ATRIBUYE el delta del gate a
CADA palanca por separado, corriendo la MISMA build con una palanca menos por vez.

POR QUE EXISTE. BL.21594 metio tres mecanismos en un commit, midio el paquete entero y el neto fue
ruido alrededor de cero: quedo sin saberse cual pagaba y cual restaba, y el BL se cerro sin
aprender nada. `arc_agent/banderas.py` hace cada palanca apagable; este script es lo que convierte
esa capacidad en un NUMERO por palanca.

QUE MIDE, y por que asi. Barrido LEAVE-ONE-OUT contra el harness REAL:

    ninguna                        linea base (agente previo a BL.21702, misma build)
    todas                          el candidato completo
    todas menos <palanca>          una corrida por palanca

El aporte de una palanca es `niveles(todas) - niveles(todas menos esa)`. Se elige leave-one-out y
no "una sola encendida" porque lo que hay que decidir es si SACARLA del paquete cambia el
resultado: dos palancas pueden ser redundantes entre si (la cobertura de coordenadas y la mascara
de accion unica atacan el mismo juego por lados distintos) y medirlas aisladas sobreestimaria a las
dos. Igual se imprime tambien el total de `ninguna`, que es lo unico que dice si el paquete SUMA.

NO ES EL GATE. El gate de merge es `gate_de_merge.py --contra` con sus tres semillas; esto es la
herramienta de ATRIBUCION, y por defecto corre con UNA semilla para que el barrido entero quepa en
un rato razonable. Un aporte por palanca medido con una semilla es una senal, no una sentencia: la
leccion 3 del rescate de BL.21594 es que el SIGNO del delta se daba vuelta entre semillas. Para
decidir con confianza, `--semillas gate-1,gate-2,gate-3` y esperar.

COSTO, y por que conviene acotar `--juego`. Cada configuracion cuesta lo mismo que una corrida del
gate con esas semillas: 25 juegos x 200 pasos x 1 semilla son ~5.000 acciones (~12 min de CPU
medidos en BL.21744), y el barrido son 7 configuraciones. Se corren SIEMPRE de a una, en serie: la
maquina tiene 6 vCPU compartidos y dos gates en paralelo se estorban y ensucian las dos mediciones.

Con ese costo, el barrido de 25 juegos a UNA semilla es el peor de los dos mundos: caro Y ruidoso
(a una semilla el total ronda los 4 niveles y un +-1 no significa nada). Sale MUCHO mejor mirar
primero que juegos MOVIERON entre la linea base y el candidato completo del gate, y ablacionar SOLO
esos con las TRES semillas: los juegos que dieron el mismo numero en las dos puntas no pueden
discriminar entre subconjuntos, asi que pagar por ellos es pagar por nada. En BL.21702 movieron
tres (ar25, ft09, vc33) y el barrido paso de ~175 corridas a 63. Lo que NO reemplaza: el candidato
que salga ganador se vuelve a medir con el gate completo, 25 juegos y 3 semillas.

Uso:
    # atribucion sobre los juegos que movieron en el gate, con las tres semillas
    .venv/bin/python scripts/ablacion_de_palancas.py --juego ar25,ft09,vc33 \
        --semillas gate-1,gate-2,gate-3 --json runtime_reports/ablacion.json
    .venv/bin/python scripts/ablacion_de_palancas.py --pasos 60 --semillas gate-1   # lazo corto
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from arc_agent.banderas import BANDERAS_CONOCIDAS  # noqa: E402  (necesita el sys.path de arriba)

GATE = RAIZ / "scripts" / "gate_de_merge.py"


def configuraciones(palancas: tuple[str, ...]) -> list[tuple[str, str]]:
    """(etiqueta, valor de ARC_AGENT_BANDERAS) de cada corrida del barrido, en orden."""
    salida = [("ninguna", "ninguna"), ("todas", "todas")]
    # `todas,-p` y no `-p`: la base de la gramatica son las palancas ENTREGADAS, que pueden ser
    # menos que todas. Sin el prefijo explicito, "sin p" mediria las entregadas menos p -- otra
    # cosa, y silenciosamente distinta segun cuando se corra el barrido.
    salida += [(f"sin {p}", f"todas,-{p}") for p in palancas]
    return salida


def correr_configuracion(
    etiqueta: str, banderas: str, pasos: int, semillas: str, juegos: str | None, destino: Path
) -> dict:
    """Una corrida del gate con esas palancas. Devuelve el JSON que el gate escribio.

    Se invoca `gate_de_merge.py` como SUBPROCESO y no se lo importa: las palancas se leen al
    importar `arc_agent`, asi que dos configuraciones en el mismo proceso compartirian la primera.
    Un proceso por configuracion es la unica forma de que cada una mida lo que dice medir."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    comando = [
        sys.executable,
        str(GATE),
        "--pasos",
        str(pasos),
        "--semillas",
        semillas,
        "--banderas",
        banderas,
        "--json",
        str(destino),
    ]
    if juegos:
        comando += ["--juego", juegos]
    print(f"\n=== {etiqueta}  (ARC_AGENT_BANDERAS={banderas}) ===", flush=True)
    inicio = time.monotonic()
    resultado = subprocess.run(comando, cwd=str(RAIZ), check=False)
    if resultado.returncode != 0:
        raise SystemExit(
            f"[ablacion] la corrida {etiqueta!r} salio con codigo {resultado.returncode}; "
            "el barrido se corta para no publicar una tabla con un agujero adentro."
        )
    medicion = json.loads(destino.read_text(encoding="utf-8"))
    medicion["minutosDeReloj"] = round((time.monotonic() - inicio) / 60.0, 1)
    return medicion


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Atribuye el delta del gate a cada palanca de BL.21702 (leave-one-out)"
    )
    parser.add_argument("--pasos", type=int, default=200)
    parser.add_argument(
        "--semillas",
        default="gate-1",
        help="Una sola por defecto: el barrido son 7 corridas. Para decidir, las tres del gate.",
    )
    parser.add_argument("--juego", default=None, help="Ids separados por coma. Sin esto, los 25.")
    parser.add_argument(
        "--palancas",
        default=",".join(BANDERAS_CONOCIDAS),
        help="Cuales ablacionar. Por defecto todas las de banderas.py.",
    )
    parser.add_argument("--json", default=None, help="Ruta del resumen de atribucion.")
    parser.add_argument(
        "--directorio",
        default="runtime_reports/ablacion",
        help="Donde dejar el JSON de CADA corrida (uno por configuracion).",
    )
    args = parser.parse_args()

    palancas = tuple(p.strip() for p in args.palancas.split(",") if p.strip())
    desconocidas = [p for p in palancas if p not in BANDERAS_CONOCIDAS]
    if desconocidas:
        raise SystemExit(
            f"[ablacion] palanca(s) desconocida(s): {', '.join(desconocidas)}. "
            f"Conocidas: {', '.join(BANDERAS_CONOCIDAS)}"
        )

    directorio = Path(args.directorio)
    mediciones: dict[str, dict] = {}
    for etiqueta, banderas in configuraciones(palancas):
        nombre = banderas.replace("todas,-", "sin_").replace(",", "_")
        mediciones[etiqueta] = correr_configuracion(
            etiqueta, banderas, args.pasos, args.semillas, args.juego, directorio / f"{nombre}.json"
        )

    base = int(mediciones["ninguna"]["totales"]["nivelesTotales"])
    todas = int(mediciones["todas"]["totales"]["nivelesTotales"])

    print("\n========= ATRIBUCION POR PALANCA =========")
    print(f"  linea base (ninguna): {base} niveles")
    print(f"  candidato  (todas):   {todas} niveles   delta del paquete {todas - base:+d}")
    print("\n  aporte de cada palanca = todas - (todas menos esa):")
    aportes: dict[str, int] = {}
    for palanca in palancas:
        sin = int(mediciones[f"sin {palanca}"]["totales"]["nivelesTotales"])
        aportes[palanca] = todas - sin
        print(f"    {palanca:32} {todas - sin:+d}   (sin ella: {sin})")

    resumen = {
        "config": {
            "pasos": args.pasos,
            "semillas": args.semillas,
            "juegos": args.juego or "todos",
            "palancas": list(palancas),
        },
        "nivelesTotales": {
            etiqueta: int(m["totales"]["nivelesTotales"]) for etiqueta, m in mediciones.items()
        },
        "deltaDelPaquete": todas - base,
        "aportePorPalanca": aportes,
        "minutosDeReloj": {e: m["minutosDeReloj"] for e, m in mediciones.items()},
    }
    if args.json:
        destino = Path(args.json)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(resumen, indent=1, sort_keys=True), encoding="utf-8")
        print(f"\nAtribucion escrita en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
