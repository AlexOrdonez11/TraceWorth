import type { Cost } from "./types";

export const money = (cost: Cost) =>
  `${cost.amount} ${cost.currency} · ${cost.cost_basis}${cost.partial ? " · partial" : ""}`;
