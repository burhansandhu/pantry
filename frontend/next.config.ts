import type { NextConfig } from "next";
const config: NextConfig = {
  devIndicators: false,
  async rewrites() {
    // Vercel routes /api directly to the Python service. Next proxies it only
    // during local development so the browser always uses its current origin.
    if (process.env.NODE_ENV !== "development") return [];
    const backend = process.env.API_PROXY_URL || "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};
export default config;
