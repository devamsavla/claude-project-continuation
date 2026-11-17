import { useEffect } from "react";
import { initSite } from "@/site/site-init";
import { initHome } from "@/site/home-init";

/**
 * Renders one page of the original whatsonyourmind.online markup and wires up its
 * interactive parts (reminder demo, notification vibes, prices, sign-up form) after mount.
 */
export function SitePage({ html, interactive = true }: { html: string; interactive?: boolean }) {
  useEffect(() => {
    if (interactive) {
      initSite();
      initHome();
    }
  }, [html, interactive]);

  return <div className="site-root" dangerouslySetInnerHTML={{ __html: html }} />;
}
