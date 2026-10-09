/* [arc-agi-runner/arcApiClient.test] BL.20775 -- cliente HTTP contra la API oficial de ARC-AGI-3
   (three.arcprize.org). fetch mockeado -- sin red real en tests. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createArcApiClient } from '../arcApiClient';

function jsonResponse(body: unknown, init: { status?: number; setCookie?: string[] } = {}) {
  const headers = new Headers();
  for (const c of init.setCookie ?? []) headers.append('set-cookie', c);
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers,
  });
}

describe('createArcApiClient', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
  });

  function client() {
    return createArcApiClient({
      apiKey: 'k-123',
      baseUrl: 'https://three.arcprize.org',
      stepTimeoutMs: 5000,
      fetchImpl: fetchMock as unknown as typeof fetch,
    });
  }

  it('listGames hace GET /api/games con header X-API-Key', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse([{ game_id: 'ls20-016295f7601e', title: 'LS20' }]),
    );
    const games = await client().listGames();
    expect(games).toEqual([{ game_id: 'ls20-016295f7601e', title: 'LS20' }]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('https://three.arcprize.org/api/games');
    expect(init.method).toBe('GET');
    expect(init.headers['X-API-Key']).toBe('k-123');
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it('openScorecard hace POST /api/scorecard/open y devuelve card_id', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ card_id: 'card-abc' }));
    const cardId = await client().openScorecard({ tags: ['t1'] });
    expect(cardId).toBe('card-abc');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('https://three.arcprize.org/api/scorecard/open');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ tags: ['t1'] });
  });

  it('closeScorecard hace POST /api/scorecard/close con card_id', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ card_id: 'card-abc', score: 42 }));
    const result = await client().closeScorecard('card-abc');
    expect(result.score).toBe(42);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('https://three.arcprize.org/api/scorecard/close');
    expect(JSON.parse(init.body)).toEqual({ card_id: 'card-abc' });
  });

  it('sendCommand hace POST /api/cmd/{action} con el body dado', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        game_id: 'ls20-016295f7601e',
        guid: 'guid-1',
        frame: [],
        state: 'NOT_FINISHED',
        levels_completed: 0,
        win_levels: 0,
        available_actions: [1, 2],
      }),
    );
    const c = client();
    const frame = await c.sendCommand('RESET', {
      game_id: 'ls20-016295f7601e',
      card_id: 'card-abc',
    });
    expect(frame.state).toBe('NOT_FINISHED');
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe('https://three.arcprize.org/api/cmd/RESET');
  });

  it('propaga y reusa cookies de sesion (AWSALB*) entre llamadas', async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(
          {
            game_id: 'g1',
            guid: 'guid-1',
            frame: [],
            state: 'NOT_FINISHED',
            levels_completed: 0,
            win_levels: 0,
            available_actions: [1],
          },
          { setCookie: ['AWSALB=xyz; Path=/'] },
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          game_id: 'g1',
          guid: 'guid-1',
          frame: [],
          state: 'WIN',
          levels_completed: 1,
          win_levels: 1,
          available_actions: [],
        }),
      );
    const c = client();
    await c.sendCommand('RESET', { game_id: 'g1', card_id: 'card-abc' });
    await c.sendCommand('ACTION1', { game_id: 'g1', guid: 'guid-1' });
    const [, secondInit] = fetchMock.mock.calls[1];
    expect(secondInit.headers['Cookie']).toContain('AWSALB=xyz');
  });

  it('lanza un error descriptivo en respuestas no-2xx', async () => {
    fetchMock.mockResolvedValueOnce(new Response('unauthorized', { status: 401 }));
    await expect(client().listGames()).rejects.toThrow(/HTTP 401/);
  });
});
