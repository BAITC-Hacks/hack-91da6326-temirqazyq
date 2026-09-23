import { expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import { ErrorBox } from "@/components/common";
import { actionUnavailable, validationHint } from "@/lib/feedback";

test("an unexpected diagnostic passed to a shared notice never reaches the page", () => {
  render(
    <ErrorBox text="unexpected private diagnostics 0x31 from internal service" />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent(actionUnavailable);
  expect(document.body.textContent).not.toContain("private diagnostics");
});

test("actionable selection guidance is local copy and does not echo diagnostic payloads", () => {
  const guidance = validationHint({
    code: "CATEGORY_LIMIT",
    message: "private engine traceback, category_counts.social=3",
  });
  render(<p>{guidance}</p>);
  expect(
    screen.getByText("Выберите не больше двух мер из одной категории."),
  ).toBeVisible();
  expect(document.body.textContent).not.toMatch(/traceback|category_counts/);
});
