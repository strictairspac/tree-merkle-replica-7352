import { api } from "../api/workbench.js";
import { errorText, field } from "../components/common/fields.js";
import { empty, pageHeading, section } from "../components/common/panel.js";
import { status } from "../components/common/status.js";
import { table } from "../components/common/table.js";
import { BatchStates } from "../constants/states.js";
import { submit } from "../hooks/submit.js";
import { navigate } from "../router/router.js";
import { el } from "../utils/dom.js";
import { time } from "../utils/format.js";

const EXAMPLE = JSON.stringify([
  {tree: 1259, street: "槐河路", status: "巡检完成", revision: 3},
  {tree: 1260, removed: true},
], null, 2);

function reload(caseId) {
  const target = `sync/${caseId}`;
  if (location.hash.slice(1) === target) window.dispatchEvent(new Event("hashchange"));
  else navigate(target);
}

function touchedText(touched) {
  if (!touched?.length) return "—";
  const shown = touched.slice(0, 8).join("、");
  return touched.length > 8 ? `${shown} 等 ${touched.length} 个` : shown;
}

function outcome(batch) {
  if (batch.state === "applied") return `已切换至 v${batch.applied_version}`;
  if (batch.state === "rejected") return `已退回：${batch.failure}`;
  return `等待 ${batch.segments - batch.received} 个分段`;
}

function openForm(selected, replica) {
  const form = el("form", {class: "sync-form"},
    field("养护截止时点", el("input", {
      name: "epoch", required: true, maxlength: 40, value: selected.payload?.replica_epoch || "",
    }), "须与资料的 replica_epoch 一致。"),
    field("底版", el("input", {
      name: "base_version", type: "number", min: 1, required: true, value: replica.version ?? 1,
    }), `当前副本为 ${replica.version ? `v${replica.version}` : "未建版"}。`),
    field("分段数", el("input", {name: "segments", type: "number", min: 1, max: 64, required: true, value: 2}),
      "分段可乱序到达，收齐后一次性切换。"),
    errorText(), el("button", {type: "submit"}, "开启补传批次"));
  submit(form, async values => {
    await api.openBatch(selected.id, {
      epoch: values.get("epoch").trim(),
      base_version: Number(values.get("base_version")),
      segments: Number(values.get("segments")),
    });
    reload(selected.id);
  });
  return form;
}

function segmentForm(selected, receiving) {
  if (!receiving.length) return empty("没有接收中的补传批次，先开启一个批次。");
  const picker = el("select", {name: "batch"}, receiving.map(batch =>
    el("option", {value: batch.id}, `批次 ${batch.id} · 底版 v${batch.base_version} · 已收 ${batch.received}/${batch.segments}`)));
  const form = el("form", {class: "sync-form"},
    field("补传批次", picker),
    field("分段序号", el("input", {name: "segment", type: "number", min: 1, required: true, value: 1})),
    field("变更内容", el("textarea", {name: "changes", spellcheck: "false", required: true, rows: 7}, EXAMPLE),
      "只交改过的树：{tree, street, status, revision} 或 {tree, removed: true}。"),
    errorText(), el("button", {type: "submit"}, "上传分段"));
  submit(form, async values => {
    let changes;
    try {
      changes = JSON.parse(values.get("changes"));
      if (!Array.isArray(changes)) throw new Error();
    } catch {
      throw new Error("变更内容须为 JSON 数组");
    }
    await api.uploadSegment(selected.id, Number(picker.value), {
      segment: Number(values.get("segment")), changes,
    });
    reload(selected.id);
  });
  return form;
}

export async function syncPage(config, user, route) {
  const cases = await api.cases();
  const selected = cases.find(item => item.id === route.id) ?? cases.at(-1);
  if (!selected) return el("div", {class: "page"},
    pageHeading(config.modules[4], null), empty("先在资料页登记业务资料。"),
    el("a", {href: "#cases"}, config.modules[1]));
  const [replica, batches] = await Promise.all([api.replica(selected.id), api.batches(selected.id)]);
  const operator = user.role === "operator";
  const picker = el("select", {"aria-label": "选择资料", onchange: event => navigate(`sync/${event.target.value}`)},
    cases.map(item => el("option", {value: item.id, selected: item.id === selected.id}, `${item.code} ${item.title}`)));
  return el("div", {class: "page"},
    pageHeading(config.modules[4], `${selected.title} · 补传只交改过的树，收齐后一次性切换`, null),
    picker,
    el("div", {class: "split"},
      section("当前副本", replica.version ?
        el("dl", {class: "metrics"},
          el("div", {}, el("dt", {}, "副本版本"), el("dd", {}, `v${replica.version}`)),
          el("div", {}, el("dt", {}, "养护记录"), el("dd", {}, `${replica.entries} 条`))) :
        empty("尚未建立副本版本。")),
      section("补传批次", batches.length ? table(
        ["批次", "底版", "分段", "状态", "结果", "改动树号", "提交人", "时间"],
        batches.map(batch => [
          batch.id, `v${batch.base_version}`, `${batch.received}/${batch.segments}`,
          status(batch.state, BatchStates), outcome(batch), touchedText(batch.touched),
          batch.actor, time(batch.created_at),
        ]), "补传批次") : empty("还没有补传批次。"))),
    operator ? el("div", {class: "split"},
      section("开启补传批次", openForm(selected, replica)),
      section("上传分段", segmentForm(selected, batches.filter(batch => batch.state === "receiving")))) :
      empty("当前账号可查看补传进度。"));
}
