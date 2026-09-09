import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "./",
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // 不压缩代码，方便排查线上报错时的堆栈
    minify: false,
    rollupOptions: {
      output: {
        // 产物文件名不带内容哈希，保证每次构建文件名稳定，日志中的堆栈可对比
        entryFileNames: "assets/[name].js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name][extname]",
      },
    },
  },
});
