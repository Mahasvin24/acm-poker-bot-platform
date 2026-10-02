import type { Metadata, Viewport } from "next";
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

export const viewport: Viewport = {
  themeColor: "#f6f0e5",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main-content">Skip to Content</a>
        {children}
      </body>
    </html>
  );
}
