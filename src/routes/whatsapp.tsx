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
          "Mindy lives in WhatsApp. Say it in your own words or a voice note, or type mind to see all 48 things it can do: money back from friends, reminders, scam checks, family care.",
      },
      "home",
    ),
  component: () => <SitePage html={html} interactive={true} />,
});
