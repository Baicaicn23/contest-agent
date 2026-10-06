import type { NextConfig } from "next";

// 静态导出：`next build` 产出纯静态文件到 out/，由 FastAPI（uv run sai serve）
// 单端口托管——与 TeachX 的 next start（Node 常驻）不同，我们的部署模型没有
// Node 服务，因此放弃 SSR，全部客户端组件。代价与对策：
//   - 无 [sessionId] 动态路由段（导出不预生成会 404）→ 会话用 /chat?session=N 查询参数
//   - next/image 优化不可用 → images.unoptimized
const nextConfig: NextConfig = {
  output: "export",
  // 尾斜杠导出（/chat/ → chat/index.html）：FastAPI StaticFiles(html=True)
  // 只认目录 index，不认 chat.html，这样 /chat 会自动 307 到 /chat/
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
