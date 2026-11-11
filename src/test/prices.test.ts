import { describe, expect, it } from "vitest";
import { EXTRAS, PLANS, FREE_WHATSAPP_REMINDERS_PER_MONTH } from "@/site/prices";

const extra = (start: string) => EXTRAS.find(([n]) => n.startsWith(start))![1];

describe("site prices", () => {
  it("Mindy Plus is ₹99 / £2.99 / $3.49 a month", () => {
    expect([PLANS.plus.INR, PLANS.plus.GBP, PLANS.plus.USD]).toEqual(["₹99", "£2.99", "$3.49"]);
  });
  it("Mindy Care is ₹199 / £4.99 / $5.99 a month", () => {
    expect([PLANS.care.INR, PLANS.care.GBP, PLANS.care.USD]).toEqual(["₹199", "£4.99", "$5.99"]);
  });
  it("album kept forever is ₹149 / £2.99 / $3.99", () => {
    const p = extra("Afterglow Forever");
    expect([p.INR, p.GBP, p.USD]).toEqual(["₹149", "£2.99", "$3.99"]);
  });
  it("holo sleeve is ₹49 / £0.99 / $0.99", () => {
    const p = extra("Holo sleeve");
    expect([p.INR, p.GBP, p.USD]).toEqual(["₹49", "£0.99", "$0.99"]);
  });
  it("league pass is ₹299 / £4.99 / $5.99", () => {
    const p = extra("League pass");
    expect([p.INR, p.GBP, p.USD]).toEqual(["₹299", "£4.99", "$5.99"]);
  });
  it("printed zine is ₹699 / £14 / $18", () => {
    const p = extra("Print your Group Wrapped");
    expect([p.INR, p.GBP, p.USD]).toEqual(["₹699", "£14", "$18"]);
  });
  it("free plan includes 30 WhatsApp reminders a month", () => {
    expect(FREE_WHATSAPP_REMINDERS_PER_MONTH).toBe(30);
  });
});
