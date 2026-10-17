"""[arc-agi3-kaggle-agent] BL.20783/BL.21555 -- valida el chequeo AUXILIAR de red: que
scripts/verify_no_network.py corre de punta a punta con la red deshabilitada a nivel de proceso,
sin fugas ocultas en el NUCLEO, y que produce un reporte de runtime. (El criterio de la cadena de
entrega es `make verify-local`/`make play-local`, no este script -- ver su docstring.) Se invoca
como SUBPROCESO (no import directo) para ejercitar EXACTAMENTE el mismo entrypoint que se corre a
mano/en CI -- incluye el bloqueo de socket ANTES del import de arc_agent, que un import directo en
el mismo proceso de pytest no reproduciria fielmente (pytest y sus plugins ya hicieron sus propios
imports antes de este test)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT_ROOT / "scripts" / "verify_no_network.py"


def test_verify_no_network_smoke_run_succeeds_and_reports_runtime() -> None:
    report_path = PROJECT_ROOT / "runtime_reports" / "no_network_smoke.json"
    report_path.unlink(missing_ok=True)

    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    elapsed = time.monotonic() - started

    assert result.returncode == 0, (
        "verify_no_network.py fallo (posible dependencia de red oculta):\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "red deshabilitada" in result.stdout
    assert report_path.exists(), "no se genero el reporte de runtime"

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["gamesPlayed"] == 6
    assert report["elapsedSeconds"] >= 0
    assert elapsed < 60, f"smoke test tardo demasiado ({elapsed:.1f}s) -- revisar Swarm/deadline"


def test_socket_blocking_actually_raises_on_real_network_attempt() -> None:
    """Cinturon y tirantes: prueba que si algo SI intenta abrir un socket real bajo el bloqueo,
    el error explota (no queda silenciado ni absorbido)."""
    code = (
        "import socket\n"
        "import sys\n"
        f"sys.path.insert(0, {str(PROJECT_ROOT / 'scripts')!r})\n"
        "from verify_no_network import NetworkDisabledError, _disable_network\n"
        "_disable_network()\n"
        "try:\n"
        "    socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "    print('LEAK: no se bloqueo')\n"
        "    sys.exit(1)\n"
        "except NetworkDisabledError:\n"
        "    print('BLOCKED_OK')\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=30
    )
    assert "BLOCKED_OK" in result.stdout, result.stdout + result.stderr
