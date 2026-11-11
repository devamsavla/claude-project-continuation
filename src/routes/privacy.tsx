import { createFileRoute } from "@tanstack/react-router";
import { SitePage } from "@/components/site/SitePage";
import { html } from "@/site/pages/privacy";
import { siteHead } from "@/site/head";

export const Route = createFileRoute("/privacy")({
  head: () =>
    siteHead(
      {
        title: "Privacy · whatsonyourmind",
        description:
          "How whatsonyourmind and Mindy handle your data on WhatsApp, Instagram and the Mindy app.",
      },
      "legal",
    ),
  component: () => <SitePage html={html} interactive={false} />,
});
