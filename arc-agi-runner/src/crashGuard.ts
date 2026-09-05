/* [arc-agi-runner/crashGuard] BL.20775 -- garantiza que ante un crash (SIGINT/SIGTERM/excepcion no
   capturada/rejection no manejado) la corrida activa se cierra igual: sin runs huerfanos en
   'running' y sin scorecard abierto en el lado de ARC. `cleanup` es inyectado por index.ts (sabe
   cual es la corrida/scorecard activos en ese momento). */

export type CrashCleanupFn = (reason: string) => Promise<void>;

export interface RegisterCrashHandlersOptions {
  /** Inyectable para tests -- default: process.exit real. */
  exit?: (code: number) => void;
  /** Tope de espera del cleanup antes de salir de todas formas (nunca cuelga el proceso). */
  cleanupTimeoutMs?: number;
}

const DEFAULT_CLEANUP_TIMEOUT_MS = 5000;

/** Registra los handlers de crash. Devuelve una funcion `unregister` para tests/shutdown limpio. */
export function registerCrashHandlers(
  cleanup: CrashCleanupFn,
  opts: RegisterCrashHandlersOptions = {},
): () => void {
  const exit = opts.exit ?? ((code: number) => process.exit(code));
  const cleanupTimeoutMs = opts.cleanupTimeoutMs ?? DEFAULT_CLEANUP_TIMEOUT_MS;

  async function runCleanupAndExit(reason: string, code: number): Promise<void> {
    const timeout = new Promise<void>((resolve) => {
      setTimeout(resolve, cleanupTimeoutMs).unref?.();
    });
    try {
      await Promise.race([cleanup(reason), timeout]);
    } catch (err) {
      console.error(`[arc-agi-runner/crashGuard] cleanup fallo (${reason}):`, err);
    }
    exit(code);
  }

  const onSigint = (): void => {
    void runCleanupAndExit('SIGINT', 130);
  };
  const onSigterm = (): void => {
    void runCleanupAndExit('SIGTERM', 143);
  };
  const onUncaught = (err: unknown): void => {
    console.error('[arc-agi-runner/crashGuard] uncaughtException:', err);
    void runCleanupAndExit('uncaughtException', 1);
  };
  const onUnhandled = (err: unknown): void => {
    console.error('[arc-agi-runner/crashGuard] unhandledRejection:', err);
    void runCleanupAndExit('unhandledRejection', 1);
  };

  process.once('SIGINT', onSigint);
  process.once('SIGTERM', onSigterm);
  process.once('uncaughtException', onUncaught);
  process.once('unhandledRejection', onUnhandled);

  return function unregister(): void {
    process.removeListener('SIGINT', onSigint);
    process.removeListener('SIGTERM', onSigterm);
    process.removeListener('uncaughtException', onUncaught);
    process.removeListener('unhandledRejection', onUnhandled);
  };
}
