// Prices shown on the site, per currency. Change prices here only.
export type Currency = "INR" | "USD" | "GBP" | "EUR" | "AED" | "BRL";
export type PriceMap = Record<Currency, string>;

export const FREE_WHATSAPP_REMINDERS_PER_MONTH = 30;

export const PLANS: Record<"plus" | "care", PriceMap> = {
  plus: { INR: "₹99", USD: "$3.49", GBP: "£2.99", EUR: "€2.99", AED: "AED 12.99", BRL: "R$14.90" },
  care: { INR: "₹199", USD: "$5.99", GBP: "£4.99", EUR: "€5.49", AED: "AED 21.99", BRL: "R$29.90" },
};

export const EXTRAS: [string, PriceMap][] = [
  [
    "Afterglow Forever: keep one album in full quality",
    { INR: "₹149", USD: "$3.99", GBP: "£2.99", EUR: "€3.49", AED: "AED 14.99", BRL: "R$19.90" },
  ],
  [
    "Your album as a hardback photo book",
    { INR: "₹1,499", USD: "$35", GBP: "£29", EUR: "€32", AED: "AED 129", BRL: "R$179" },
  ],
  [
    "Print your Group Wrapped as a zine",
    { INR: "₹699", USD: "$18", GBP: "£14", EUR: "€16", AED: "AED 65", BRL: "R$89" },
  ],
  [
    "Sticker pack: new Mindy moods and outfits",
    { INR: "₹79", USD: "$1.49", GBP: "£1.49", EUR: "€1.49", AED: "AED 5.49", BRL: "R$7.90" },
  ],
  [
    "Holo sleeve for your rarest card",
    { INR: "₹49", USD: "$0.99", GBP: "£0.99", EUR: "€0.99", AED: "AED 3.69", BRL: "R$4.90" },
  ],
  [
    "League pass: auction night for 10 friends, a season",
    { INR: "₹299", USD: "$5.99", GBP: "£4.99", EUR: "€5.49", AED: "AED 21.99", BRL: "R$29.90" },
  ],
  [
    "Mindy plush toy",
    { INR: "₹999", USD: "$24", GBP: "£19", EUR: "€22", AED: "AED 89", BRL: "R$119" },
  ],
];
