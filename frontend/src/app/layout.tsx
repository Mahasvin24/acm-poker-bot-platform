import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "ACM Poker Bot Tournament",
  description:
    "A live, play-money poker tournament where human players and student-built bots compete at the same table.",
  icons: {
    icon: "/acm-logo.png",
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
