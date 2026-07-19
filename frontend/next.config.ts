import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  env: {
    AGENT_HUB_API_URL: process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000',
  },
};

export default nextConfig;
