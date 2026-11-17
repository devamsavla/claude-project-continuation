import siteCss from "./site.css?url";
import legalCss from "./legal.css?url";
import homeCss from "./home.css?url";

type PageMeta = { title: string; description: string };

/** Per-page head tags, matching the original site's titles and descriptions. */
export function siteHead({ title, description }: PageMeta, kind: "site" | "legal" | "home" = "site") {
  return {
    meta: [
      { title },
      { name: "description", content: description },
      { property: "og:title", content: title },
      { property: "og:description", content: description },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "twitter:title", content: title },
      { name: "twitter:description", content: description },
    ],
    links: [{ rel: "stylesheet", href: kind === "home" ? homeCss : kind === "site" ? siteCss : legalCss }],
  };
}
