import type { Metadata } from "next";

import { DemoPreviewTable } from "@/features/table/demo-preview";

export const metadata: Metadata = {
  title: "Table Preview | ACM Poker",
  description: "A static preview of the poker table controls.",
};

export default function TablePreviewPage() {
  return <DemoPreviewTable />;
}
