const { test } = require('node:test');
const assert = require('node:assert/strict');
const { isCancelledViewTransition } = require('./page-errors');

test('recognizes the native, stackless transition cancellation observed in Chromium', () => {
  for (const message of [
    'Transition was aborted because of invalid state',
    'Transition was aborted because of invalid state. ViewTransition opt-in disabled',
  ]) {
    assert.equal(isCancelledViewTransition({ message, stack: `Error: ${message}` }), true);
  }
});

test('keeps application errors even when they use the same message', () => {
  const error = new Error('Transition was aborted because of invalid state');
  assert.equal(isCancelledViewTransition(error), false);
});

test('keeps unrelated errors and messages merely starting with the cancellation text', () => {
  for (const message of [
    'Cannot read properties of undefined',
    'Transition was aborted because of invalid state: application failed',
    'Transition was aborted because of invalid state. Unknown browser failure',
  ]) {
    assert.equal(isCancelledViewTransition({ message, stack: `Error: ${message}` }), false);
  }
});
