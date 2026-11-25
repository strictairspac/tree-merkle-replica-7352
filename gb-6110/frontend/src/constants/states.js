export const States = Object.freeze({
  queued: "等待执行", done: "已完成", failed: "执行失败",
});

export const BatchStates = Object.freeze({
  receiving: "接收中", applied: "已切换", rejected: "已退回",
});

export const Actions = Object.freeze({
  create_case: "登记资料", enqueue: "提交执行", done: "执行完成", failed: "执行失败", review: "复核签署",
  open_batch: "开启补传", apply_batch: "补传切换", reject_batch: "补传退回",
});
