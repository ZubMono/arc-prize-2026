/* [arc-agi-runner/crashGuard.test] BL.20775 -- ante crash el scorecard/run se cierra igual
   (GAME_OVER registrado, sin runs huerfanos). process.emit simula la señal sin matar el proceso
   de test (exit() se inyecta mockeado). */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { registerCrashHandlers } from '../crashGuard';

describe('registerCrashHandlers', () => {
  let unregister: (() => void) | undefined;

  afterEach(() => {
    unregister?.();
    unregister = undefined;
    vi.restoreAllMocks();
  });

  it('corre el cleanup y llama exit(130) en SIGINT', async () => {
    const cleanup = vi.fn().mockResolvedValue(undefined);
    const exit = vi.fn();
    unregister = registerCrashHandlers(cleanup, { exit, cleanupTimeoutMs: 100 });
    process.emit('SIGINT');
    await new Promise((r) => setTimeout(r, 10));
    expect(cleanup).toHaveBeenCalledWith('SIGINT');
    expect(exit).toHaveBeenCalledWith(130);
  });

  it('corre el cleanup y llama exit(143) en SIGTERM', async () => {
    const cleanup = vi.fn().mockResolvedValue(undefined);
    const exit = vi.fn();
    unregister = registerCrashHandlers(cleanup, { exit, cleanupTimeoutMs: 100 });
    process.emit('SIGTERM');
    await new Promise((r) => setTimeout(r, 10));
    expect(cleanup).toHaveBeenCalledWith('SIGTERM');
    expect(exit).toHaveBeenCalledWith(143);
  });

  it('en uncaughtException corre cleanup y sale con codigo 1', async () => {
    const cleanup = vi.fn().mockResolvedValue(undefined);
    const exit = vi.fn();
    unregister = registerCrashHandlers(cleanup, { exit, cleanupTimeoutMs: 100 });
    process.emit('uncaughtException', new Error('boom'));
    await new Promise((r) => setTimeout(r, 10));
    expect(cleanup).toHaveBeenCalledWith('uncaughtException');
    expect(exit).toHaveBeenCalledWith(1);
  });

  it('si el cleanup nunca resuelve, igual sale tras el timeout (no cuelga el proceso)', async () => {
    const cleanup = vi.fn(() => new Promise<void>(() => {})); // nunca resuelve
    const exit = vi.fn();
    unregister = registerCrashHandlers(cleanup, { exit, cleanupTimeoutMs: 20 });
    process.emit('SIGINT');
    await new Promise((r) => setTimeout(r, 60));
    expect(exit).toHaveBeenCalledWith(130);
  });

  it('unregister quita los listeners (no reacciona tras desregistrar)', async () => {
    const cleanup = vi.fn().mockResolvedValue(undefined);
    const exit = vi.fn();
    const un = registerCrashHandlers(cleanup, { exit, cleanupTimeoutMs: 100 });
    un();
    process.emit('SIGINT');
    await new Promise((r) => setTimeout(r, 10));
    expect(cleanup).not.toHaveBeenCalled();
  });
});
