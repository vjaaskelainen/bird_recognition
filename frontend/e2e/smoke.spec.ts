import { expect, test } from "@playwright/test";

test("sign in, list, confirm, correct, skip and undo", async ({ page }) => {
  await page.goto("/videos");
  await expect(page).toHaveURL(/\/sign-in\?return=/);

  await page.getByLabel("API key").fill("wrong");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toBeVisible();

  await page.getByLabel("API key").fill("secret");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/videos/);
  await expect(page.getByTestId("video-row")).toHaveCount(3);
  await expect(page.getByText("Local · privacy-screened crops")).toBeVisible();

  await page.goto("/review");
  await expect(page.getByTestId("contact-sheet")).toBeVisible();
  await expect(page.getByText("a.mp4").first()).toBeVisible();

  await page.getByTestId("action-confirm").click();
  await expect(page.getByText("b.mp4").first()).toBeVisible();

  await page.getByTestId("action-undo").click();
  await expect(page.getByText("a.mp4").first()).toBeVisible();

  await page.getByTestId("action-skip").click();
  await expect(page.getByText("b.mp4").first()).toBeVisible();

  await page.getByTestId("action-correct").click();
  await page.getByRole("button", { name: "Save correction" }).click();
  await expect(page.getByText("c.mp4").first()).toBeVisible();
});
