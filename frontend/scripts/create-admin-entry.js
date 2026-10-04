const fs = require("fs");
const path = require("path");

const buildDir = path.resolve(__dirname, "..", "build");
const source = path.join(buildDir, "index.html");
const standaloneAdminEntry = path.join(buildDir, "admin-login.html");
const adminDir = path.join(buildDir, "admin-login");
const adminDirEntry = path.join(adminDir, "index.html");

if (!fs.existsSync(source)) {
  throw new Error("build/index.html was not found; admin entry could not be created");
}

fs.copyFileSync(source, standaloneAdminEntry);
fs.mkdirSync(adminDir, { recursive: true });
fs.copyFileSync(source, adminDirEntry);

console.log("Created durable admin login entry points: /admin-login.html and /admin-login/");
