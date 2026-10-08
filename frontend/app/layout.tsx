import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Pantry — Something good from what you've got",
  description: "Turn your ingredients into a recipe with thoughtful pairings, reviewed substitutions and a little kitchen inspiration.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
