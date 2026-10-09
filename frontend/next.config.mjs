/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    // `pg` loads `pg-native` optionally at runtime; bundling it makes webpack chase that
    // require. Left to Node instead, which is also what keeps its connection pool one pool.
    serverComponentsExternalPackages: ['pg'],
  },
};

export default nextConfig;
