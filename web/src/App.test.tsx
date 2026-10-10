import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import App from "./App";

const TAB_LABELS = ["Race", "Models", "Evidence", "Brief", "Observability", "Settings"];

describe("App shell", () => {
  // Explicit cleanup: RTL's auto-cleanup needs global lifecycle hooks, and the
  // vitest config keeps globals off.
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    window.location.hash = "";
  });

  it("renders the six-tab bottom navigation with the round picker as the default route", () => {
    render(<App />);
    const tabs = within(screen.getByRole("navigation")).getAllByRole("button");
    expect(tabs.map((tab) => tab.textContent)).toEqual(TAB_LABELS);
    expect(screen.getByRole("heading", { name: "Pick a round" })).toBeTruthy();
  });

  it("switches panels when a tab is pressed", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Models" }));
    expect(screen.getByRole("heading", { name: "Model Gauntlet" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Pick a round" })).toBeNull();
  });

  it("carries the advisory evidence-basis banner", () => {
    render(<App />);
    expect(screen.getAllByText(/ADVISORY ONLY/).length).toBeGreaterThan(0);
  });
});
