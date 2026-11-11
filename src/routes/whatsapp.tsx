import { createFileRoute } from "@tanstack/react-router";
import { SitePage } from "@/components/site/SitePage";
import { html } from "@/site/pages/whatsapp";
import { siteHead } from "@/site/head";

export const Route = createFileRoute("/whatsapp")({
  head: () =>
    siteHead(
      {
        title: "Mindy on WhatsApp",
        description:
          "Save Mindy's number and send anything. Reminders, lists, birthdays and a memory that never forgets, right inside WhatsApp.",
      },
      "site",
    ),
  component: () => <SitePage html={html} interactive={true} />,
});
