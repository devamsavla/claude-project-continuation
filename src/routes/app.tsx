import { createFileRoute } from "@tanstack/react-router";
import { SitePage } from "@/components/site/SitePage";
import { html } from "@/site/pages/app";
import { siteHead } from "@/site/head";

export const Route = createFileRoute("/app")({
  head: () =>
    siteHead(
      {
        title: "The Mindy app · whatsonyourmind",
        description:
          "The free Mindy app opens on your mind: 48 things Mindy can do, lit as you use them, with one-tap tries, your people, money and family. Opens from WhatsApp, already signed in.",
      },
      "home",
    ),
  component: () => <SitePage html={html} interactive={true} />,
});
