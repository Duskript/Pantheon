const crypto = require("crypto");
const jwt = require("/var/lib/ghost/current/node_modules/.pnpm/jsonwebtoken@9.0.2/node_modules/jsonwebtoken");
const kid = "6a514bd8a6ff3f00010c563f";
const secret = "ddbf2baf6a2bf2706fc503ba967520e81bc4abf71ae38d21078b5bb1410d8e62";
const iat = Math.floor(Date.now()/1000);
const token = jwt.sign({iat, exp: iat + 300, aud: "/admin/"}, secret, {algorithm: "HS256", keyid: kid});
console.log("Token:", token.slice(0,30)+"...");

const http = require("http");
const opts = {hostname: "127.0.0.1", port: 2368, path: "/ghost/api/admin/settings/", method: "GET", headers: {"Authorization": "Ghost " + token}};
const req = http.request(opts, (res) => {
  let d = ""; res.on("data", c => d += c);
  res.on("end", () => {
    console.log("Status:", res.statusCode);
    const parsed = JSON.parse(d);
    if (parsed.settings) parsed.settings.filter(s => ["title","accent_color"].includes(s.key)).forEach(s => console.log(s.key + ": " + s.value));
    else console.log("Response:", d.slice(0,200));
  });
});
req.on("error", e => console.log("Error:", e.message));
req.end();
