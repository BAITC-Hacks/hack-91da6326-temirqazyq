import type { Metadata } from "next";
import "./globals.css";
import "./workspace.css";

export const metadata: Metadata = {
  title: "Akim AI — Аким на 5 часов",
  description:
    "Пять решений. Один город. Симулятор городской политики Астаны и лаборатория сценариев.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
