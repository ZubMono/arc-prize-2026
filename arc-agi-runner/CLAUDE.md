# arc-agi-runner — Reglas para Claude Code

## Proposito

Agente baseline que juega los juegos publicos de ARC-AGI-3 (https://three.arcprize.org) contra la
API oficial y persiste scorecards/steps en la coleccion Mongo `prometheusEvaluationRuns`
(BL.20774, epica BL.20770 -- Benchmark Vivo de Prometheus / ARC Prize 2026). Sub-BL BL.20775
(wave 1, MVP): valida el pipeline end-to-end (API, persistencia, timeouts, dead-letter, crash
safety) con un agente que elige acciones al azar (semillado) entre las disponibles -- NO hace
percepcion de grilla ni planificacion. Eso es una wave posterior del harness de aprendizaje real
(ver `discuss-context BL.20770`).

## Aislamiento critico — AUTO-CONTENIDO, sin dependencias del monorepo privado

Este proyecto **NO importa `packages/*`** (ni via `workspace:*` ni via paths de tsconfig). Si se
se compite por el ARC Prize 2026 se abre bajo licencia de dominio publico (MIT-0 o CC0, NO CC-BY:
la regla exige "a permissive public domain license" y CC-BY exige atribucion -- ver BL.21045), y el
core privado del monorepo no puede quedar acoplado. Consecuencias concretas:

- `src/mongoClient.ts` reimplementa el patron singleton + `maxPoolSize` obligatorio de
  `packages/mongo::getMongoClient` de forma independiente (no lo importa).
- `src/types.ts` tiene un **mirror manual** del contrato de escritura de
  `packages/api/prometheusEvaluationRuns/types.ts` (BL.20774) y `src/index.ts` reimplementa
  `archivePolicy.ts::computeRunExpiryDate` (formula trivial: fecha + dias en ms). Si el schema
  privado cambia, actualizar estos dos archivos a mano -- es un limite de contrato deliberado, no
  la regla de "fuente unica" del resto del repo (aca hay DOS lados de una frontera de licencia).
- `vitest.config.ts` no importa `../../vitest.shared` -- config propia, calcada a mano.
- El SDK oficial Python `arc_agi` (subproceso pineado) fue evaluado y descartado a favor de
  hablarle DIRECTO a la API HTTP (`src/arcApiClient.ts`): el SDK es un wrapper delgado sobre la
  MISMA API REST, asi que ir por HTTP es funcionalmente equivalente, evita acoplar el runtime Node
  a un venv Python pineado (peor para portabilidad y para abrir el codigo) y es mas facil de
  testear con mocks.

## Stack

- Runtime: Node.js 24, TypeScript, sin servidor HTTP -- proceso batch (`tsx src/index.ts`).
- HTTP: `fetch` nativo + `AbortSignal.timeout` (nunca sin timeout). Cookie jar manual en
  `arcApiClient.ts` (la API usa cookies `AWSALB*` para rutear al mismo backend por sesion).
- Persistencia: `mongodb` driver nativo, sin capa `packages/api` (ver aislamiento arriba).
- Tests: Vitest, red y Mongo siempre mockeados/inyectados -- ver "Testing" abajo.

## Variables de entorno

Ver `.env.example`. Obligatorias: `ARC_API_KEY` (humano: signup en
https://three.arcprize.org/api-keys, NO generable en sesion), `MONGO_URL`. El resto tiene default
razonable (`src/config.ts::loadConfig`). `ARC_RUNNER_GAME_IDS` (CSV, solo `main()`) limita el
batch a un subset de juegos -- util para pruebas manuales sin jugar los 25 juegos publicos.
`ARC_REPLAY_CAPTURE=0` apaga la captura del corpus de replay (default: encendida, BL.21557).

## Diseno — timeouts, idempotencia, crash-safety, dead-letter

- **Timeout duro por juego: 30 min** (`ARC_GAME_TIMEOUT_MS`) -- vigilado en `gameRunner.ts` via un
  deadline inyectable (`now()`), chequeado en cada vuelta del loop de acciones.
- **Timeout duro por step: 60s** (`ARC_STEP_TIMEOUT_MS`) -- vive en `arcApiClient.ts`
  (`AbortSignal.timeout` por llamada HTTP), independiente del deadline del juego.
- **Idempotencia por runId**: `runId = modelId:gameId:runBatchId` (`ARC_RUN_BATCH_ID`, default
  fecha UTC del dia). `evaluationRunStore.isAlreadyCompleted()` hace skip si ya existe un run con
  `status:'completed'` para ese runId -- reintentar el mismo dia no duplica ni re-juega.
- **Crash-safety**: `crashGuard.ts` engancha SIGINT/SIGTERM/uncaughtException/unhandledRejection.
  `index.ts::runBatch` mantiene el run "activo" (el juego en curso) y, ante crash, lo cierra como
  `status:'failed'` (GAME_OVER logico, nunca queda huerfano en `'running'`) y cierra el scorecard
  de ARC (`POST /api/scorecard/close`) antes de salir. Tope de espera del cleanup: 5s (nunca
  cuelga el proceso indefinidamente).
- **Dead-letter tras 3 fallas de API consecutivas** (`ARC_MAX_API_FAILURES`,
  `deadLetterTracker.ts`): un juego que acumula 3 fallas seguidas de la API se marca
  `status:'failed'` con el error de la ultima falla y el runner sigue con el SIGUIENTE juego --
  nunca se cuelga reintentando uno solo indefinidamente.
- **GAME_OVER "normal" (el agente pierde) NO es una falla**: `status:'completed'`,
  `result.success:false`. Solo timeout/dead-letter/error de API mapean a `status:'failed'`.
- **Score con CREDITO PARCIAL (BL.21557)**: `result.score` es ENTERO = nivel maximo alcanzado
  (`levels_completed` de los frames, `levelProgress.ts`), NO el 0/1 de BL.20775. Una victoria nunca
  puntua menos que 1. Es la metrica del leaderboard oficial (el submission.parquet del gateway trae
  `score` entero) y la de seleccion offline: `rankRunsByLevelProgress` ordena dos versiones del
  agente aunque ninguna gane. Los contadores van tambien POR STEP, para ubicar el salto de nivel.
- **Corpus de replay (BL.21557)**: modo captura ENCENDIDO por default (`ARC_REPLAY_CAPTURE=0` lo
  apaga). Persiste un doc por paso en `arcReplayFrames` con {x, y, availableActions, diff RLE
  pre/post, niveles}. Diffs, no grillas: 500 pasos medidos = 218 KB BSON (techo duro 1MB por
  partida, la captura se corta sola al agotarlo). Codec en `replayRleDiff.ts` (fuente unica; el
  schema privado especifica el formato, no lo reimplementa). La captura NUNCA tumba la partida.
- **replayMetadata**: `seed` (PRNG del agente, `prng.ts::generateSeed`, semilla NUEVA por corrida
  pero persistida para reproducir la MISMA secuencia de decisiones en un replay) + `envVersion`
  (`config.ts::RUNNER_ENV_VERSION`, versiona el CONTRATO de esta integracion, no el juego de ARC).

## Donde clickear — ranker de coordenada (BL.21560)

`pickClickTarget` (uniforme sobre el decil superior de "borde de color") murio: ahora deciden
`clickFeatures.ts` (features por celda derivadas de `grid.ts` + `findComponents`) y `clickMemory.ts`
(prior lineal + plantillas y ANTI-plantillas de parche 3x3 + memoria por `(firma, x, y)`).
Medido contra la API oficial: ft09-0d8bbf25 (el juego con el que se ajusto) **9,2% -> 100%** (32 de
346 -> 32 de 32) y lp85-305b61c3, que NO esta en el corpus, **4,2% -> 16,5%** (13 de 313 -> 13 de
79). Los mismos clicks productivos con 4-10x menos acciones, que es lo que puntua ARC.
Sin anti-plantillas y con el prior sin regularizar, lp85 acertaba **0 de 499**: el prior de un solo
juego mandaba a barrer la cenefa decorativa. La evidencia del episodio pesa mas que el prior a
proposito (+-6 contra |2,3| como maximo).

`clickPriors.ts` es **GENERADO** por `arc-agi3-kaggle-agent/scripts/fit_click_priors.py` (los mismos
numeros que `arc_agent/priors.py`): NO editarlo a mano. El corpus con el que se ajusta sale de
`arcReplayFrames` via `scripts/exportClickCorpus.ts` -> `__fixtures__/clickRealFrames.json`, que es
tambien el fixture de los tests de efecto.

## API oficial ARC-AGI-3 (resumen -- fuente: docs.arcprize.org)

Base `https://three.arcprize.org`. Header `X-API-Key` en TODA request. `GET /api/games` lista los
juegos publicos. `POST /api/scorecard/open` (body opcional `{source_url,tags,opaque}`) ->
`{card_id}`; `POST /api/scorecard/close` (`{card_id}`) cierra y agrega estadisticas. Comandos
`POST /api/cmd/{RESET|ACTION1..7}` (`{game_id, card_id?, guid?, x?, y?, reasoning?}`) -> frame
`{game_id, guid, frame (grillas 64x64, indices 0-15), state (NOT_FINISHED|NOT_STARTED|WIN|
GAME_OVER), available_actions}`. Rate limit: 600 rpm, backoff exponencial en 429.

## Correr

```bash
pnpm --filter @invierte/arc-agi-runner test    # vitest, todo mockeado
pnpm --filter @invierte/arc-agi-runner dev      # batch real -- requiere ARC_API_KEY + MONGO_URL
ARC_RUNNER_GAME_IDS=ls20-016295f7601e pnpm --filter @invierte/arc-agi-runner dev  # 1 solo juego
```

## Testing

Cero red y cero Mongo reales en tests: `arcApiClient` recibe `fetchImpl` inyectado,
`evaluationRunStore`/`gameRunner`/`index::runBatch` reciben `client`/`store` fake por parametro.
`mongoClient.test.ts` mockea el modulo `mongodb` entero (`vi.mock`). El test de crash de
`index.test.ts` usa `vi.waitFor` (nunca `setTimeout` fijo) para esperar que el mock haya sido
invocado antes de emitir la señal -- evita flakiness por orden de microtasks.

## Extension futura (fuera de alcance de este BL, ver discuss-context BL.20770)

Percepcion real de la grilla + politica no aleatoria, entornos propios en `arcEnvironments`,
harness de auto-mejora, submission a ARC Prize 2026 -- waves W2/W3/W4 del epico BL.20770.
