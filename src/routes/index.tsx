import { createFileRoute } from "@tanstack/react-router";
import { SitePage } from "@/components/site/SitePage";
import { html } from "@/site/pages/index";
import { siteHead } from "@/site/head";

export const Route = createFileRoute("/")({
  head: () =>
    siteHead(
      {
        title: "whatsonyourmind",
        description:
          "Just text Mindy on WhatsApp: save anything, find it in plain words, get reminders in any time zone. Then the free Mindy app for friends, plans and games.",
      },
      "site",
    ),
  component: () => <SitePage html={html} interactive={true} />,
});
