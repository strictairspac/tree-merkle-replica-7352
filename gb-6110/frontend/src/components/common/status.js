import { States } from "../../constants/states.js";
import { el } from "../../utils/dom.js";

export function status(value, labels = States) {
  return el("span", {class: `status state-${value}`, "data-state": value}, labels[value] || value);
}
