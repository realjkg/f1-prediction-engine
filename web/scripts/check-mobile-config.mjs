// Fail closed: a real mobile package must never point at localhost or a Vite
// development server. The backend is the containerized HTTPS API ingress.
const value = process.env.VITE_F1E_API_BASE_URL?.trim();
if (!value) {
  console.error("Set VITE_F1E_API_BASE_URL to the public HTTPS API origin before a mobile build.");
  process.exit(1);
}
let url;
try {
  url = new URL(value);
} catch {
  console.error("VITE_F1E_API_BASE_URL must be an absolute URL.");
  process.exit(1);
}
if (
  url.protocol !== "https:" ||
  url.username ||
  url.password ||
  url.pathname !== "/" ||
  url.search ||
  url.hash ||
  ["localhost", "127.0.0.1", "0.0.0.0", "10.0.2.2"].includes(url.hostname)
) {
  console.error("Mobile API origin must use a public HTTPS hostname with no path, user info or query.");
  process.exit(1);
}
console.log(`Mobile backend origin verified: ${url.origin}`);
