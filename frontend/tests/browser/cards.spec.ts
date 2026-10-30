import { expect, test } from "@playwright/test";

for (const width of [375, 1280])
  for (const dark of [false, true])
    test(`responsive ${width} ${dark ? "dark" : "light"}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.goto("/");
      if (dark) await page.locator("body").evaluate((body) => body.classList.add("dark"));
      await expect(page.getByRole("heading", { name: "Home climate" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Your zones" })).toBeVisible();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
      await page.addScriptTag({ url: "/axe.min.js" });
      const violations = await page.evaluate(async () => {
        const axe = (
          window as unknown as { axe: { run(): Promise<{ violations: { id: string }[] }> } }
        ).axe;
        return (await axe.run()).violations.map((issue) => issue.id);
      });
      expect(violations).toEqual([]);
    });
test("keyboard controls, pending state and rejection", async ({ page }) => {
  await page.goto("/");
  const increase = page.getByRole("button", { name: "Increase target temperature", exact: true });
  await expect(increase).toBeVisible();
  await increase.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("actronair-neo-climate-card")).toContainText("24.5");
  await page.evaluate(() => {
    (window as unknown as { failNext: boolean }).failNext = true;
  });
  await increase.click();
  await expect(page.getByRole("alert")).toContainText("could not be sent");
  await page.getByRole("button", { name: "Dismiss error" }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
});
test("unavailable controls and reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.evaluate(() => {
    const win = window as unknown as {
      hass: { states: Record<string, { state: string }> };
      refresh(): void;
    };
    const state = win.hass.states["climate.system"];
    if (state) state.state = "unavailable";
    win.refresh();
  });
  await expect(
    page.getByRole("button", { name: "Increase target temperature", exact: true }),
  ).toBeDisabled();
  await expect(page.getByRole("button", { name: "Turn off Bedroom", exact: true })).toBeDisabled();
});
