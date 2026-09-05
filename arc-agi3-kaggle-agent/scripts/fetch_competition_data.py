"""[arc-agi3-kaggle-agent/scripts/fetch_competition_data] BL.21554 -- baja el dataset de la
competencia y materializa sus tres partes en el sub-proyecto.

HALLAZGO QUE HACE QUE ESTO REEMPLACE AL `git clone` DEL STARTER: el framework oficial
`ARC-AGI-3-Agents` VIAJA DENTRO del dataset de `arc-prize-2026-arc-agi-3`, igual que los juegos
reales (`environment_files/`) y las wheels offline (`arc_agi_3_wheels/`). O sea que un unico
`kaggle competitions download` con el token del repo trae TODO -- no hace falta clonar ningun
repositorio externo (que ademas este monorepo bloquea, y con razon).

Reparto de lo descargado:
  ARC-AGI-3-Agents/  -> vendor/ARC-AGI-3-Agents/   (framework, lo importa el loop local)
  environment_files/ -> environment_files/         (juegos REALES, los lee el paquete arc-agi)
  arc_agi_3_wheels/  -> wheels/                    (wheels offline de arc-agi y arcengine)

Los tres destinos estan gitignoreados: son cientos de MB de terceros y no entran al repo.

Uso:
    python3 scripts/fetch_competition_data.py            # no rehace lo que ya esta
    python3 scripts/fetch_competition_data.py --forzar   # re-descarga y re-extrae todo
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from starter_config import (  # noqa: E402  (necesita el sys.path de arriba)
    CACHE_DIR,
    ENVIRONMENTS_DIR,
    PROJECT_ROOT,
    VENDOR_DIR,
    WHEELS_DIR,
    correr_kaggle,
    slug_competencia,
)

#: Nombre de la carpeta dentro del zip -> destino en el sub-proyecto.
REPARTO: dict[str, Path] = {
    "ARC-AGI-3-Agents": VENDOR_DIR,
    "environment_files": ENVIRONMENTS_DIR,
    "arc_agi_3_wheels": WHEELS_DIR,
}


def _ruta_zip(slug: str) -> Path:
    return CACHE_DIR / f"{slug}.zip"


def descargar(slug: str, forzar: bool) -> Path:
    """Descarga el zip de la competencia via `scripts/kaggle-cli.cjs`. Devuelve su ruta."""
    destino = _ruta_zip(slug)
    if destino.exists() and not forzar:
        mb = destino.stat().st_size / (1024 * 1024)
        print(f"[fetch] Ya estaba descargado {destino.name} ({mb:.1f} MB). Usa --forzar para rehacer.")
        return destino

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        destino.unlink()
    print(f"[fetch] Descargando el dataset de {slug} (unos 42 MB)...")
    correr_kaggle(["competitions", "download", "-c", slug, "-p", str(CACHE_DIR)])
    if not destino.exists():
        raise SystemExit(
            f"[fetch] El CLI de Kaggle no dejo {destino}. Revisa que la cuenta haya aceptado las "
            f"reglas de {slug} (userHasEntered) y que el token del .env cifrado siga vigente."
        )
    return destino


def extraer(ruta_zip: Path, forzar: bool) -> Path:
    """Extrae el zip a `.cache/kaggle/extraido/`. Devuelve ese directorio."""
    extraido = CACHE_DIR / "extraido"
    if extraido.is_dir() and not forzar and any(extraido.iterdir()):
        print(f"[fetch] Ya estaba extraido en {extraido}.")
        return extraido
    if extraido.exists():
        shutil.rmtree(extraido)
    extraido.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ruta_zip) as zf:
        zf.extractall(extraido)
        print(f"[fetch] Extraidos {len(zf.namelist())} archivos en {extraido}.")
    return extraido


def materializar(extraido: Path, forzar: bool) -> None:
    """Copia cada parte del dataset a su destino definitivo dentro del sub-proyecto."""
    for nombre, destino in REPARTO.items():
        origen = extraido / nombre
        if not origen.is_dir():
            raise SystemExit(
                f"[fetch] El dataset no trajo `{nombre}/`. Cambio la estructura del dataset: "
                "revisa `kaggle competitions files` antes de seguir."
            )
        if destino.exists():
            if not forzar:
                print(f"[fetch] {destino.relative_to(PROJECT_ROOT)} ya existe; se deja como esta.")
                continue
            shutil.rmtree(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(origen, destino)
        print(f"[fetch] {nombre}/ -> {destino.relative_to(PROJECT_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Baja y materializa el dataset de la competencia.")
    parser.add_argument(
        "--forzar",
        action="store_true",
        help="Re-descarga y re-extrae aunque ya este todo en disco.",
    )
    args = parser.parse_args()

    slug = slug_competencia()
    ruta_zip = descargar(slug, args.forzar)
    extraido = extraer(ruta_zip, args.forzar)
    materializar(extraido, args.forzar)

    juegos = sorted({p.parent.parent.name for p in ENVIRONMENTS_DIR.glob("*/*/metadata.json")})
    print(f"[fetch] Listo. {len(juegos)} juegos reales disponibles: {', '.join(juegos)}")


if __name__ == "__main__":
    main()
