#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createDecipheriv, pbkdf2Sync } from "node:crypto";

const ROOT = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const password = process.env.SITE_PASSWORD || "";

main().catch(error => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});

async function main() {
  let board;
  if (password) {
    const encrypted = await readJson("data/athletes.encrypted.json");
    board = decryptJson(encrypted, password);
  } else {
    board = await readJson("data/athletes.sample.json");
  }

  if (!board.meta || !Array.isArray(board.athletes)) {
    throw new Error("Board must contain meta and athletes.");
  }

  const ids = new Set();
  for (const item of board.athletes) {
    if (!item.id) throw new Error("Every athlete row needs an id.");
    if (ids.has(item.id)) throw new Error(`Duplicate athlete id: ${item.id}`);
    ids.add(item.id);
    if (!Array.isArray(item.categories)) throw new Error(`${item.id} needs categories.`);
    if (item.gradYear && !/^\d{4}$/.test(String(item.gradYear))) throw new Error(`${item.id} has invalid gradYear.`);
    if (item.xUrl && !/^https:\/\/(x|twitter)\.com\//i.test(item.xUrl)) throw new Error(`${item.id} has invalid X URL.`);
  }

  console.log(`Data validation passed for ${board.athletes.length} offer rows.`);
}

async function readJson(relativePath) {
  return JSON.parse(await fs.readFile(path.join(ROOT, relativePath), "utf8"));
}

function decryptJson(payload, sitePassword) {
  if (!payload || payload.version !== 1 || payload.ciphertext === "placeholder") {
    throw new Error("Encrypted board has not been generated yet.");
  }
  const salt = Buffer.from(payload.salt, "base64");
  const iv = Buffer.from(payload.iv, "base64");
  const sealed = Buffer.from(payload.ciphertext, "base64");
  const encrypted = sealed.subarray(0, -16);
  const tag = sealed.subarray(-16);
  const key = pbkdf2Sync(sitePassword, salt, Number(payload.iterations || 210000), 32, "sha256");
  const decipher = createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAuthTag(tag);
  const decrypted = Buffer.concat([decipher.update(encrypted), decipher.final()]);
  return JSON.parse(decrypted.toString("utf8"));
}

