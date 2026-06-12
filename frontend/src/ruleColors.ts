export const RULE_COLOR: Record<string, string> = {
  public: "#16a34a",
  audience: "#0d9488",
  attribute_gate: "#7c3aed",
  private: "#6b7280",
};
export const colorFor = (ruleType: string) => RULE_COLOR[ruleType] ?? "#6b7280";
