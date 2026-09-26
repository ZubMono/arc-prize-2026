/* [arc-agi-runner/mongoClient.test] BL.20775 -- factory Mongo AUTO-CONTENIDA (no importa
   packages/mongo -- aislamiento critico del proyecto). Siempre maxPoolSize (R1). */
import { afterEach, describe, expect, it, vi } from 'vitest';

const connectMock = vi.fn();

vi.mock('mongodb', () => ({
  MongoClient: { connect: (...args: unknown[]) => connectMock(...args) },
}));

describe('getArcRunnerMongoClient', () => {
  afterEach(async () => {
    vi.clearAllMocks();
    const { _resetArcRunnerMongoSingletons } = await import('../mongoClient');
    _resetArcRunnerMongoSingletons();
  });

  it('siempre pasa maxPoolSize a MongoClient.connect (default 3)', async () => {
    connectMock.mockResolvedValue({ id: 'client-1' });
    const { getArcRunnerMongoClient } = await import('../mongoClient');
    await getArcRunnerMongoClient('mongodb://localhost:27017/x');
    expect(connectMock).toHaveBeenCalledTimes(1);
    const [uri, opts] = connectMock.mock.calls[0];
    expect(uri).toBe('mongodb://localhost:27017/x');
    expect(opts.maxPoolSize).toBe(3);
  });

  it('respeta maxPoolSize explicito', async () => {
    connectMock.mockResolvedValue({ id: 'client-1' });
    const { getArcRunnerMongoClient } = await import('../mongoClient');
    await getArcRunnerMongoClient('mongodb://localhost:27017/x', { maxPoolSize: 7 });
    const [, opts] = connectMock.mock.calls[0];
    expect(opts.maxPoolSize).toBe(7);
  });

  it('reusa el singleton por URI (no reconecta)', async () => {
    connectMock.mockResolvedValue({ id: 'client-1' });
    const { getArcRunnerMongoClient } = await import('../mongoClient');
    const a = await getArcRunnerMongoClient('mongodb://localhost:27017/x');
    const b = await getArcRunnerMongoClient('mongodb://localhost:27017/x');
    expect(a).toBe(b);
    expect(connectMock).toHaveBeenCalledTimes(1);
  });

  it('closeArcRunnerMongoClient cierra y limpia el singleton', async () => {
    const closeMock = vi.fn().mockResolvedValue(undefined);
    connectMock.mockResolvedValue({ id: 'client-1', close: closeMock });
    const { getArcRunnerMongoClient, closeArcRunnerMongoClient } = await import('../mongoClient');
    await getArcRunnerMongoClient('mongodb://localhost:27017/x');
    await closeArcRunnerMongoClient('mongodb://localhost:27017/x');
    expect(closeMock).toHaveBeenCalledTimes(1);
    connectMock.mockResolvedValue({ id: 'client-2' });
    await getArcRunnerMongoClient('mongodb://localhost:27017/x');
    expect(connectMock).toHaveBeenCalledTimes(2);
  });
});
