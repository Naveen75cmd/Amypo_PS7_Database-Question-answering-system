/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    // CPU-only generation on phi3:mini can take 30-40 s on a cold model. The
    // rewrite proxy defaults to 30 s and would answer 500 while the backend is
    // still working, which surfaced in the UI as "Internal Server Error" even
    // though /ask had succeeded. Give the proxy the backend's full budget.
    proxyTimeout: 180_000,
  },
  async rewrites() {
    // Proxy API calls so the browser never needs CORS during local dev.
    return [
      {
        source: "/api/v1/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000"}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
