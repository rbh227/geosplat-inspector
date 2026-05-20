import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GeoSplat Inspector",
  description: "Browser-based viewer for Gaussian splats with an LLM agent that navigates the scene.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
