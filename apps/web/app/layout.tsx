import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/components/AuthContext";
import { DisclaimerBanner } from "@/components/DisclaimerBanner";
import { HeaderNav } from "@/components/HeaderNav";

export const metadata: Metadata = {
  title: "RADAR AI — Brain CT Research Workspace",
  description: "Research prototype for brain CT review assistance. Not for clinical use.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="id">
      <body>
        <AuthProvider>
          <a href="#main-content" className="skip-link">Skip to main content</a>
          <DisclaimerBanner />
          <HeaderNav />
          <main id="main-content" className="main-container">{children}</main>
          <footer className="app-footer">Research and demonstration prototype only. Not for clinical use.</footer>
        </AuthProvider>
      </body>
    </html>
  );
}
