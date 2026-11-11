import { createFileRoute } from "@tanstack/react-router";
import { SitePage } from "@/components/site/SitePage";
import { html } from "@/site/pages/app";
import { siteHead } from "@/site/head";

export const Route = createFileRoute("/app")({
  head: () =>
    siteHead(
      {
        title: "The Mindy app",
        description:
          "Who's free now, chats with Mindy inside, watch parties, hand cricket, reminders and saves. Free in your browser; sign in with WhatsApp.",
      },
      "site",
    ),
  component: () => <SitePage html={html} interactive={true} />,
});
