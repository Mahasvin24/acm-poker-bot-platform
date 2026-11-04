import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "ACM Poker: Humans vs. Bots",
  description:
    "Play-money poker matches where human players and student-built bots compete at the same table.",
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
