import { createFileRoute } from "@tanstack/react-router";
import { SitePage } from "@/components/site/SitePage";
import { html } from "@/site/pages/instagram";
import { siteHead } from "@/site/head";

export const Route = createFileRoute("/instagram")({
  head: () =>
    siteHead(
      {
        title: "Mindy on Instagram",
        description:
          "Share any reel or post to @whatsonyourmind. Recipes become shopping lists, places become plans.",
      },
      "site",
    ),
  component: () => <SitePage html={html} interactive={true} />,
});
