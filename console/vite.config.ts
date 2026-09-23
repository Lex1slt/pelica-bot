import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 开发模式：控制台.bat 以固定端口+token 启动网关并注入本进程环境
const gwPort = process.env.PELICA_GATEWAY_PORT || "8765";
const gwToken = process.env.PELICA_GATEWAY_TOKEN || "";

const serverConfig = gwToken
  ? {
      port: 5179,
      strictPort: true,
      proxy: {
        "/api": {
          target: `http://127.0.0.1:${gwPort}`,
          changeOrigin: true,
          ws: true,
          configure(proxy) {
            proxy.on("proxyReq", (proxyReq) => {
              if (gwToken) proxyReq.setHeader("Authorization", `Bearer ${gwToken}`);
            });
          },
        },
      },
    }
  : { port: 5179, strictPort: true };

export default defineConfig({
  plugins: [react(), tailwindcss()],
  clearScreen: false,
  // 开发模式把网关 token 编进前端（浏览器 WS 无法走代理注入头）
  define: {
    __GW_TOKEN__: JSON.stringify(gwToken),
  },
  server: serverConfig,
  build: {
    target: "chrome110",
    sourcemap: false,
  },
});
