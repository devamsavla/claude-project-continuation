import { createFileRoute } from "@tanstack/react-router";
import { SitePage } from "@/components/site/SitePage";
import { html } from "@/site/pages/instagram";
import { siteHead } from "@/site/head";

export const Route = createFileRoute("/instagram")({
  head: () =>
    siteHead(
      {
        title: "Mindy on Instagram · whatsonyourmind",
        description:
          "Share a reel to Mindy and it becomes a recipe, a place or a plan, with a reminder to actually do it.",
      },
      "home",
    ),
  component: () => <SitePage html={html} interactive={true} />,
});
