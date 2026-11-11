import { createFileRoute } from "@tanstack/react-router";
import { SitePage } from "@/components/site/SitePage";
import { html } from "@/site/pages/terms";
import { siteHead } from "@/site/head";

export const Route = createFileRoute("/terms")({
  head: () =>
    siteHead(
      {
        title: "Terms · whatsonyourmind",
        description:
          "The terms for using whatsonyourmind, Mindy on WhatsApp and Instagram, and the Mindy app.",
      },
      "legal",
    ),
  component: () => <SitePage html={html} interactive={false} />,
});
