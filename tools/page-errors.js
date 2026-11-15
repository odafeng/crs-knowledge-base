// A cancelled cross-document fade is reported by Chromium without a script stack.
// Keep exact messages narrow so a real application error cannot be hidden by a prefix match.
const CANCELLED_TRANSITIONS = new Set([
  'Transition was aborted because of invalid state',
  'Transition was aborted because of invalid state. ViewTransition opt-in disabled',
]);

function isCancelledViewTransition(error) {
  const hasScriptStack = (error.stack || '').split('\n').slice(1).some(line => line.trim());
  return CANCELLED_TRANSITIONS.has(error.message) && !hasScriptStack;
}

module.exports = { isCancelledViewTransition };
