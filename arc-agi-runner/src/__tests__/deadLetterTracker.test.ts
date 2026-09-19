/* [arc-agi-runner/deadLetterTracker.test] BL.20775 -- dead-letter tras N fallas consecutivas de API. */
import { describe, expect, it } from 'vitest';

import { createDeadLetterTracker } from '../deadLetterTracker';

describe('createDeadLetterTracker', () => {
  it('no esta dead-lettered al crearse', () => {
    const t = createDeadLetterTracker(3);
    expect(t.isDeadLettered()).toBe(false);
    expect(t.failureCount()).toBe(0);
  });

  it('marca dead-letter tras alcanzar el maximo de fallas consecutivas', () => {
    const t = createDeadLetterTracker(3);
    expect(t.recordFailure()).toBe(false);
    expect(t.recordFailure()).toBe(false);
    expect(t.recordFailure()).toBe(true);
    expect(t.isDeadLettered()).toBe(true);
    expect(t.failureCount()).toBe(3);
  });

  it('recordSuccess reinicia el contador de fallas', () => {
    const t = createDeadLetterTracker(3);
    t.recordFailure();
    t.recordFailure();
    t.recordSuccess();
    expect(t.failureCount()).toBe(0);
    expect(t.isDeadLettered()).toBe(false);
    t.recordFailure();
    expect(t.isDeadLettered()).toBe(false);
  });

  it('una vez dead-lettered, permanece dead-lettered aunque llegue un exito', () => {
    const t = createDeadLetterTracker(1);
    t.recordFailure();
    expect(t.isDeadLettered()).toBe(true);
    t.recordSuccess();
    expect(t.isDeadLettered()).toBe(true);
  });
});
