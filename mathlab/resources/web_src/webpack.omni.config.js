const path = require("path");

// OmniBar 命令栏的独立打包配置（不依赖 Monaco，保持足够轻量）
module.exports = {
  mode: "production",
  // 固定 context 为配置所在目录，避免依赖运行时的当前工作目录
  context: __dirname,
  entry: path.resolve(__dirname, "omni_bar.ts"),
  output: {
    // 输出到 resources/dist，与 monaco.html 的引用路径保持一致
    path: path.resolve(__dirname, "../dist"),
    filename: "omni_bar.bundle.js",
  },
  module: {
    rules: [
      { test: /\.ts$/, use: "ts-loader", exclude: /node_modules/ },
    ],
  },
  resolve: { extensions: [".ts", ".js"] },
};
