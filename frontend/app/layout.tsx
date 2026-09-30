import type { Metadata } from "next";
import "./globals.css";
import NavBar from "../components/NavBar";
import { Providers } from "../components/Providers";

export const metadata: Metadata = {
  title: {
    default: "Adaptive Knowledge Graph",
    template: "%s | Adaptive Knowledge Graph",
  },
  description:
    "Open-source, local-first adaptive learning demo: a knowledge graph, hybrid retrieval and a local LLM answer questions and generate quizzes over OpenStax textbooks.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="font-sans">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-gray-900 focus:shadow-lg"
        >
          Skip to main content
        </a>
        <Providers>
          <NavBar />
          {children}
        </Providers>
      </body>
    </html>
  );
}
