/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  eslint: {
    // Lint runs as its own step (`npm run lint`) so a build in a constrained
    // environment still produces output rather than failing on style.
    ignoreDuringBuilds: true,
  },

  env: {
    // Public at build time; embedded so `process.env` lookups in client code
    // resolve. Changing this requires a rebuild, not just a restart.
    NEXT_PUBLIC_API_URL:
      process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1",
    // Optional override for the basemap style URL. Empty means the built-in
    // default (OpenFreeMap over OpenStreetMap data) — see src/lib/basemap.ts.
    // Must be an https style URL MapLibre can load; `mapbox://…` is rejected.
    NEXT_PUBLIC_MAP_STYLE: process.env.NEXT_PUBLIC_MAP_STYLE ?? "",
  },

  experimental: {
    // maplibre-gl is only ever imported inside a dynamic import in the map
    // component; keeping it external stops the server build from parsing a
    // large prebuilt bundle it will never execute.
    serverComponentsExternalPackages: ["maplibre-gl"],
  },

  async rewrites() {
    // Proxying the API through the Next server means the browser sees one
    // origin, so no CORS preflight and no API host is baked into the bundle.
    // Set `API_PROXY=false` to talk to the backend directly instead.
    if (process.env.API_PROXY === "false") return [];
    const backend = process.env.BACKEND_ORIGIN ?? "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;