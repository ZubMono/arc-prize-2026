# arc-agi3-kaggle-agent — Reglas para Claude Code

## Proposito

Agente competidor para el track ARC-AGI-3 del ARC Prize 2026 (Kaggle), sub-BL BL.20783 (wave 4 de
la epica BL.20770 -- ver `discuss-context BL.20770`). Implementa la interfaz del framework oficial
`ARC-AGI-3-Agents` (`is_done` / `choose_action`).

**Restriccion dura del notebook Kaggle: SIN INTERNET y <= 9 horas de runtime.** El agente NO puede
llamar APIs de LLM en inferencia -- es 100% auto-contenido ("program synthesis / busqueda /
heuristicas"). La otra opcion del alcance, "modelo open-source con pesos empaquetados", se
descarto: exige GPU + empaquetado dentro del presupuesto de 9h/sin-red, mientras que una politica
de exploracion + memoria de estados se audita y se testea sin GPU. Ver `arc_agent/policy.py`.

## Aislamiento critico — AUTO-CONTENIDO, sin monorepo ni paquete oficial

Igual que `projects/arc-agi-runner/` (BL.20775): **no importa `packages/*`** (el repo se abre bajo
licencia de dominio publico -- MIT-0 o CC0, NO CC-BY: el ARC Prize exige "a permissive public
domain license" y CC-BY exige atribucion, BL.21045). Y ademas **tampoco instala el paquete pip
oficial `ARC-AGI-3-Agents`**: el notebook corre SIN INTERNET en evaluacion. Consecuencias:

- `arc_agent/types.py` y `arc_agent/agent.py` son un **mirror manual** del contrato oficial
  (`FrameData`, `GameAction`, `GameState`, `Agent.is_done`/`choose_action`) -- si el framework real
  cambia su firma, se actualizan A MANO. Mismo limite deliberado que `arc-agi-runner/src/types.ts`
  frente a `packages/api/prometheusEvaluationRuns`: dos mirrors independientes del MISMO contrato
  upstream, en dos lenguajes, para dos contextos (runner Node online vs. agente Python offline).
- `arc_agent/prng.py` usa `random.Random` de la stdlib en vez de portar `mulberry32` -- mismo
  PRINCIPIO de reproducibilidad que `prng.ts`, otra implementacion.
- **Cero dependencias de terceros en runtime** (`pyproject.toml`, `dependencies = []`). `pytest` es
  solo de DESARROLLO (`requirements-dev.txt`) y nunca viaja al entregable.

## Estructura

- `arc_agent/`: paquete fuente. `types.py` (mirror del contrato) - `prng.py` - `policy.py`
  (exploracion + memoria de estados + coordenada + recompensa por nivel) - `banderas.py` (palancas)
  - `world_model/` (sintesis DSL, mascara de volatilidad, y `relaciones_no_locales.py`: causa a
    distancia confirmada 3-de-4 CONTRA LA TASA BASE del destino, consumida por
    `policy._explotar_submeta`, BL.21704 -- filtros y nulo circular en su docstring) -
    `kaggle_adapter.py` (unico modulo que habla `arcengine`). `agent.py`, `prometheus_agent.py`,
    `swarm.py`, `runner.py`, `runtime_report.py` y `local_harness.py` son SOLO del repo: NO viajan,
    ver `MODULOS_EXCLUIDOS`.
- `submission/build_agent.py`: inlinea `arc_agent/*.py` (menos `MODULOS_EXCLUIDOS`) en UN solo
  `agent/my_agent.py` self-contained. `make agente` tras CUALQUIER cambio en `arc_agent/`, y
  `make notebook` para el kernel; el generado NO se edita a mano.

## Senal densa — recompensa extrinseca por nivel (BL.21557)

`FrameData` traia `levels_completed`/`win_levels` desde BL.20783 y la politica no los miraba:
exploraba con recompensa puramente INTRINSECA, asi que una accion que hacia SUBIR DE NIVEL valia lo
mismo que una que no hacia nada. Ahora, cuando el contador sube, la accion que lo produjo desde ESE
estado pasa al frente del ranking por `LEVEL_REWARD_PRIORITY_USES` visitas y deja de poder marcarse
no-op. El credito SE AGOTA a proposito (fijarlo seria el lockout que BL.21518 desarmo del lado de
los no-ops) y se aplica DESPUES del barajado, como particion estable: si consumiera numeros del
`rng`, un mismo seed dejaria de reproducir la misma partida. `runtime_report` lleva `totalScore`
(`run_score`, espejo de `computeRunScore` del runner TS): dos batches con 0 victorias producian
antes el MISMO reporte. Es la metrica del premio -- el `submission.parquet` del gateway trae
columna `score` ENTERA, con credito parcial.

## Donde clickear — ranker de coordenada + priors.py (BL.21560)

ACTION6 ya no elige una celda de "borde de color" al azar. `click_targeting.py` puntua CADA celda
con features de `world_model/grid.py` y pesos ajustados OFFLINE, guarda como plantilla el parche
3x3 de todo click con efecto, recuerda por `(firma, x, y)` lo ya probado y descarta la CLASE entera
de un parche que fallo dos veces (anti-plantilla). Medido contra la API oficial: ft09-0d8bbf25
**9,2% -> 100%** (32 de 346 clicks productivos) y lp85-305b61c3, que NO esta en el corpus,
**4,2% -> 16,5%**: los MISMOS aciertos gastando 4-10x menos acciones, que es lo que puntua ARC
(penaliza cada accion de mas). La cobertura TRANSVERSAL al estado la agrega BL.21702 (ver abajo).

Las anti-plantillas y la regularizacion (L2=0.01) no son cosmetica: con L2=1e-3 y sin ellas, el
prior de UN solo juego mandaba a lp85 a la cenefa y acertaba **0 de 499**. Un prior es una
sugerencia; la evidencia del episodio manda.

`arc_agent/priors.py` es **GENERADO** (`scripts/fit_click_priors.py`, regresion logistica contra
`arc-agi-runner/src/worldModel/__fixtures__/clickRealFrames.json`) -- NO editarlo a mano; emite los
MISMOS numeros a `clickPriors.ts`. `build_agent.py` **FALLA el build** si alguna clave tiene forma
de game_id o de firma de 32 bits: los juegos de evaluacion son otros. `ordenAcciones` se aplica SOLO
en la primera decision (`prior_de_arranque`): como desempate permanente colapsaba la exploracion.

## El entregable REAL (BL.21554/BL.21555)

Lo que Kaggle ve es UN `agent/my_agent.py` con clase `MyAgent(agents.agent.Agent)` y tipos de
`arcengine` (`arcprize/ARC-AGI-3-Kaggle-Starter`). Plan:
`notes/features/arc-prize-2026-milestone2-linea-de-trabajo.md`.

Token de Kaggle: fuente unica en el env cifrado (`node scripts/kaggle-cli.cjs <args>`,
`notes/infrastructure/kaggle-token-fuente-unica.md`). Submitear: SOLO por
`node scripts/kaggle/submitear.cjs --proyecto arc-agi3-kaggle-agent --version <n> --mensaje "<t>"`
(GATE-KAGGLE-SUBMIT, BL.21725; `--solo-preflight` mide sin gastar cuota). El guard 31 bloquea
`competitions submit` a mano: es irreversible y la cuota REAL es 1/dia, no las 5 del README. El
veredicto se lee de `competitions submissions`, NUNCA del exit code (miente: el submit exitoso
55606792 imprimio "0 submissions remaining today").

## Palancas de exploracion apagables — `arc_agent/banderas.py` (BL.21702)

Las cuatro palancas de BL.21702 y el RESET voluntario entran **cada una con su interruptor**:
`ARC_AGENT_BANDERAS=ninguna` · `todas` · `todas,-palanca` · `ninguna,+palanca`. El gate lo expone
como `--banderas` y lo anota en su JSON; sin variable rige `BANDERAS_POR_DEFECTO`: **lo que se
entrega lo decide el gate, no la intencion**.

**Y hacia falta.** El paquete completo EMPATO contra la linea base (12 → 12 niveles, 25 juegos, 200
pasos, 3 semillas). El barrido leave-one-out (`scripts/ablacion_de_palancas.py`) mostro que ese cero
NO es "no pasa nada": son **dos efectos reales de signo opuesto que se cancelan** --
`macroCambioInformativo` **+2**, `memoriaTransversalDeClicks` **−2**, las otras tres **0**. Es el
diagnostico que BL.21594 no pudo hacer por medir el paquete entero.

- `memoriaTransversalDeClicks` — cobertura transversal al estado (antes `(firma,x,y)` la vaciaba
  con cada firma nueva: 5 celdas en 138 clicks). Off-policy sobre ft09 gana (232 → 293 productivos)
  pero **en lazo cerrado RESTA dos niveles**: donde la celda productiva ya estaba identificada,
  repartir clicks la abandona.
- `mascaraDeAccionUnica` — `VOLATILITY_MIN_DISTINCT_ACTIONS=2` volvia la mascara imposible en los
  SEIS juegos de un solo boton (ft09, lp85, r11l, s5i5, tn36, vc33).
- `macroCambioInformativo` — `MacroCommitment` amplificaba x8 cualquier accion que moviera un
  pixel (sb26: ACTION5 82,8%). Ahora exige que el estado al que llega sea nuevo. **+2**.
- `warmupDeClicksSeguidos` — dc22 se queda en la PANTALLA DE TITULO, que ANIMA: el libro
  re-tanteaba las flechas entre clicks y nunca gastaba los 9 (8 ACTION6 en 151 acciones). Ahora el
  re-tanteo se difiere hasta agotar el presupuesto de clicks.
- `resetPorCongelamiento` — RESET voluntario, **refutado por medicion** (el involuntario ya se
  dispara solo y no destraba nada). Condiciones y contraejemplos: `arc_agent/estado_congelado.py`.

## Gate de merge y valvula de submission — SIEMPRE el harness real (BL.21744)

`make gate-base` y despues `make gate` (`scripts/gate_de_merge.py`): `arc_agi` +
`environment_files` offline, 3 semillas fijas, sale con 1 si los NIVELES TOTALES no suben. RECHAZA
comparar contra una base de otra configuracion — incluida una base SIN bloque `config`, que antes
pasaba y daba APROBADO con el agente sin tocar: `nivelesTotales` es una suma que crece con juegos,
pasos y semillas, asi que un lazo rapido (`--pasos 60`) solo se compara contra otro igual. Costo
MEDIDO ~36 min de CPU por corrida y **son DOS** si no tenes base valida; medilo con
`--reportar-costo`, no a ojo (el reloj se va x20 con load 50).

**`scripts/medir_lazo_cerrado.py` NO es gate de merge NI decide submissions** — lo avisa por
`--help` y por pantalla, no solo en su docstring: simula el mapeo de acciones, no los puzzles, y su
metrica valida es `accionesEnBotonesMuertos`. La valvula semanal de Kaggle tambien mide con el
harness real (`scripts/lib/arcKaggleBanco.cjs`) y una referencia de otro instrumento no habilita
'mejora-medida' (`protocoloMedicion`).

Geometria en `tests/support/geometria_de_mundos.py`; guard BFS en
`tests/test_bl21744_alcanzabilidad_de_niveles.py`: corre en pre-commit al tocar el banco
(GATE-ARC-ALCANZABILIDAD), su oraculo solo ve el FRAME (`entorno._ox` aprobaba mundos irresolubles)
y FALLA CERRADO — en worktree usa el `.venv` del principal; fail-open unico y ruidoso: `ARC_ALCANZABILIDAD_BYPASS="<motivo 10+>"` (BL.21790).

## Testing — `cd projects/arc-agi3-kaggle-agent && .venv/bin/python -m pytest -q` (sin red ni Mongo)

**Test obligatorio de red deshabilitada** (`.venv/bin/python scripts/verify_no_network.py`): bloquea
`socket.socket`/`create_connection`/`getaddrinfo` a nivel de PROCESO **antes** de importar
`arc_agent` (atrapa fugas en tiempo de import) y corre 6 juegos vs. `local_harness.py`. Bloqueo de
socket y no `unshare -n` por portabilidad: funciona igual en Kaggle, CI y local sin privilegios.
`tests/test_no_network_smoke.py` lo corre como subproceso y prueba que el bloqueo SI explota.

Fuera de alcance (`discuss-context BL.20770`): modelo con pesos empaquetados y entornos propios.
