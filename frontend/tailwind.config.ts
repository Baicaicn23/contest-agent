import type { Config } from "tailwindcss";

/**
 * M11 迁移：主题令牌沿用 TeachX 的 shadcn 风格语义变量
 * （--primary/--muted/--ring…），只保留 snow 一套（纯白 + 蓝accent，
 * Codex/ChatGPT 风格 chrome）。变量定义见 app/globals.css。
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        // Latin serif（Lora 由 next/font 提供）后显式接中文宋体——
        // Latin 字体不含汉字，不配对会出现中英文散装混排（TeachX 同款注释）
        serif: ["var(--font-serif)", "Songti SC", "STSong", "Noto Serif SC", "SimSun", "Georgia", "serif"],
        sans: ["var(--font-sans)", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "system-ui", "sans-serif"],
      },
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        card: "var(--card)",
        popover: "var(--popover)",
        primary: "var(--primary)",
        "primary-foreground": "var(--primary-foreground)",
        secondary: "var(--secondary)",
        "secondary-foreground": "var(--secondary-foreground)",
        muted: "var(--muted)",
        "muted-foreground": "var(--muted-foreground)",
        accent: "var(--accent)",
        destructive: "var(--destructive)",
        border: "var(--border)",
        ring: "var(--ring)",
      },
    },
  },
  plugins: [],
};
export default config;
