import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("stylesheet structure", () => {
  it("has balanced braces, so no media query swallows the rules after it", () => {
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "");
    let depth = 0;
    for (const char of css) {
      if (char === "{") depth += 1;
      if (char === "}") depth -= 1;
      expect(depth).toBeGreaterThanOrEqual(0);
    }
    expect(depth).toBe(0);
  });

  it("never nests the laptop layout inside another at-rule", () => {
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "");
    let depth = 0;
    for (const line of css.split("\n")) {
      if (line.startsWith("@media")) expect(depth).toBe(0);
      depth += (line.match(/{/g) ?? []).length - (line.match(/}/g) ?? []).length;
    }
  });
});
