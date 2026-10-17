// Offline transaction model for failure-injection tests only.
// The operator performs privileged nft commands using the reviewed host binary.
export function installTransaction(ops) {
  if (ops.tableExists()) throw new Error("TEST_TABLE_ALREADY_EXISTS");
  ops.syntaxCheck();
  let applied = false;
  let recorded = false;
  try {
    ops.apply();
    applied = true;
    ops.onApplied?.();
    if (!ops.tableExists()) throw new Error("TEST_TABLE_NOT_VISIBLE_AFTER_APPLY");
    ops.record();
    recorded = true;
  } finally {
    if (applied && !recorded && ops.tableExists()) ops.remove();
  }
}

export function rollbackTransaction(ops) {
  if (!ops.tableExists()) throw new Error("TEST_TABLE_ABSENT_REVIEW_REQUIRED");
  ops.remove();
  if (ops.tableExists()) throw new Error("TEST_TABLE_STILL_PRESENT");
  ops.clearRecord();
}
