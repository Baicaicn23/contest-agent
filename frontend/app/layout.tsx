import type { Metadata, Viewport } from "next";
import { Lora, Inter } from "next/font/google";
import { AppShell } from "@/components/app-shell";
import "./globals.css";

// Latin serif（问候大标题用）与 Latin sans，中文字体在 tailwind 字体栈里显式接力
const lora = Lora({ subsets: ["latin"], variable: "--font-serif" });
const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "Contest Agent",
  description: "盯学院官网 → 识别比赛 → 生成材料/学习路径的比赛情报助手",
};

export const viewport: Viewport = {
  // dvh：iOS Safari 的 100vh 含回缩地址栏，会把 composer 顶出去（TeachX 同款注释）
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className={`${lora.variable} ${inter.variable}`}>
      <body className="font-sans">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
