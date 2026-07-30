import { expect, test } from "@playwright/test";

test("renders the default room with its window, door, and heat source", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "heat-fvm" })).toBeVisible();
  const svg = page.locator("svg").first();
  await expect(svg).toBeVisible();
  await expect(svg.locator("circle")).toHaveCount(1);
  await expect(svg.locator("rect.fill-sky-400")).toHaveCount(1); // default east window
  await expect(svg.locator("rect.fill-amber-700")).toHaveCount(1); // default south door
});

test("dragging the heat source updates its position", async ({ page }) => {
  await page.goto("/");

  const heatSource = page.locator("svg circle");
  const initialCx = await heatSource.getAttribute("cx");
  const initialCy = await heatSource.getAttribute("cy");

  const box = await heatSource.boundingBox();
  if (!box) throw new Error("heat source circle not found");

  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + 150, box.y - 50, { steps: 10 });
  await page.mouse.up();

  await expect(async () => {
    expect(await heatSource.getAttribute("cx")).not.toBe(initialCx);
    expect(await heatSource.getAttribute("cy")).not.toBe(initialCy);
  }).toPass();
});

test("adding and deleting a window on the north wall", async ({ page }) => {
  await page.goto("/");

  const windowRects = page.locator("svg rect.fill-sky-400");
  const initialCount = await windowRects.count();

  await page.getByRole("button", { name: "+ window" }).first().click();
  await expect(windowRects).toHaveCount(initialCount + 1);

  await page.locator("svg text", { hasText: "×" }).first().click();
  await expect(windowRects).toHaveCount(initialCount);
});
