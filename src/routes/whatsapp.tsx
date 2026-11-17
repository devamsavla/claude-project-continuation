import { createFileRoute } from "@tanstack/react-router";
import { SitePage } from "@/components/site/SitePage";
import { html } from "@/site/pages/whatsapp";
import { siteHead } from "@/site/head";

export const Route = createFileRoute("/whatsapp")({
  head: () =>
    siteHead(
      {
        title: "Mindy on WhatsApp · whatsonyourmind",
        description:
          "Mindy lives in WhatsApp. Say it in your own words or a voice note: ask a friend for money back, set reminders, check scams, look after family.",
      },
      "home",
    ),
  component: () => <SitePage html={html} interactive={true} />,
});
