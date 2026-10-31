import type { Metadata } from "next";
import "./style.css";

export const metadata: Metadata = {
  title: "OpsDetective | Service monitoring",
  description: "Service monitoring and incident investigation workspace",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
