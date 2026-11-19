import { createFileRoute } from "@tanstack/react-router";
import { SitePage } from "@/components/site/SitePage";
import { html } from "@/site/pages/index";
import { siteHead } from "@/site/head";

export const Route = createFileRoute("/")({
  head: () =>
    siteHead(
      {
        title: "whatsonyourmind · Your Mindy talks to their Mindy",
        description:
          "Everyone gets their own Mindy on WhatsApp. Your Mindy talks to their Mindy, so you never have to chase money, plans or your mum yourself. 48 things to try, one tap each.",
      },
      "home",
    ),
  component: () => <SitePage html={html} interactive={true} />,
});
