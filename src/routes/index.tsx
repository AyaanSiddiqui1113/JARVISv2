import { createFileRoute } from "@tanstack/react-router";
import { JarvisChat } from "@/components/JarvisChat";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "J.A.R.V.I.S. — Personal AI Assistant" },
      { name: "description", content: "JARVIS-style AI that controls your computer through a local helper agent." },
      { property: "og:title", content: "J.A.R.V.I.S." },
      { property: "og:description", content: "Your personal AI computer assistant." },
    ],
  }),
  component: Index,
});

function Index() {
  return <JarvisChat />;
}
