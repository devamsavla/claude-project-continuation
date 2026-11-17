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
          "The free Mindy app: your people, your brain, your family tree, money and clipboard. Opens from WhatsApp, already signed in.",
      },
      "home",
    ),
  component: () => <SitePage html={html} interactive={true} />,
});
