import { createFileRoute } from "@tanstack/react-router";
import { JarvisChat } from "@/components/JarvisChat";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "NEXUS — Neural Executive eXchange Utility System" },
      { name: "description", content: "NEXUS OS — an AI assistant that controls your computer, browser and NEXUS devices through a local helper agent." },
      { property: "og:title", content: "NEXUS — Neural Executive eXchange Utility System" },
      { property: "og:description", content: "NEXUS OS — your personal AI computer assistant and device control hub." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: Index,
});

function Index() {
  return <JarvisChat />;
}
