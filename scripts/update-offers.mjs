#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  createCipheriv,
  createDecipheriv,
  createHash,
  pbkdf2Sync,
  randomBytes
} from "node:crypto";

const ROOT = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const KDF_ITERATIONS = 210000;
const MAX_AI_EVALS = Number(process.env.MAX_AI_EVALS_PER_RUN || 15);

const env = {
  sitePassword: process.env.SITE_PASSWORD || "",
  xBearerToken: process.env.X_BEARER_TOKEN || "",
  openAiKey: process.env.OPENAI_API_KEY || "",
  openAiModel: process.env.OPENAI_MODEL || "gpt-4o-mini",
  alertWebhookUrl: process.env.ALERT_WEBHOOK_URL || "",
  isGithubActions: process.env.GITHUB_ACTIONS === "true"
};

const args = new Set(process.argv.slice(2));

main().catch(error => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});

async function main() {
  if (env.isGithubActions && !env.sitePassword) {
    throw new Error("SITE_PASSWORD is required in GitHub Actions so the public site never publishes raw recruiting data.");
  }

  const schoolsConfig = await readJson("config/schools.json");
  const searchConfig = await readJson("config/search-queries.json");
  const board = await loadBoard(env.sitePassword);
  const beforeIds = new Set(board.athletes.map(item => item.id));
  const now = new Date();

  const newItems = [];
  let scannedPosts = 0;
  let aiCalls = 0;

  if (env.xBearerToken && !args.has("--seed-sample")) {
    const posts = await fetchXPosts(searchConfig);
    scannedPosts = posts.length;
    for (const post of posts) {
      const candidate = await buildCandidate(post, schoolsConfig, aiCalls < MAX_AI_EVALS);
      if (!candidate) continue;
      if (candidate.aiEvaluated) aiCalls += 1;
      mergeCandidate(board, candidate, beforeIds, newItems, now);
    }
  } else {
    console.log("X_BEARER_TOKEN not set. Keeping existing encrypted board and sample rows.");
  }

  markRecent(board, now);
  board.meta = {
    generatedAt: now.toISOString(),
    status: env.xBearerToken ? "Live X scan" : "Awaiting X API token",
    year: 2026,
    queryWindowMinutes: searchConfig.queryWindowMinutes || 35,
    source: "X API recent search",
    scannedPosts,
    newOffers: newItems.length,
    aiCalls
  };

  board.athletes.sort((a, b) => new Date(b.updatedAt || b.lastOfferAt) - new Date(a.updatedAt || a.lastOfferAt));

  if (env.sitePassword) {
    const encrypted = encryptJson(board, env.sitePassword);
    await writeJson("data/athletes.encrypted.json", encrypted);
  } else {
    console.log("SITE_PASSWORD not set locally. Skipped encrypted write.");
  }

  if (newItems.length && env.alertWebhookUrl) {
    await sendAlert(newItems, env.alertWebhookUrl);
  }

  console.log(`Offer agent complete. Posts scanned: ${scannedPosts}. New offers: ${newItems.length}.`);
}

async function fetchXPosts(searchConfig) {
  const queryWindowMinutes = Number(searchConfig.queryWindowMinutes || 35);
  const startTime = new Date(Date.now() - queryWindowMinutes * 60 * 1000).toISOString();
  const allPosts = [];
  const seen = new Set();

  for (const item of searchConfig.queries || []) {
    const posts = await fetchRecentSearch(item.query, startTime);
    for (const post of posts) {
      if (seen.has(post.id)) continue;
      seen.add(post.id);
      allPosts.push({ ...post, queryName: item.name });
    }
  }

  for (const handle of searchConfig.trustedAccounts || []) {
    const query = `from:${handle} ("offer" OR "offered" OR "received an offer") (football OR recruit OR QB OR RB OR WR OR DB OR OL OR DL) -is:retweet lang:en`;
    const posts = await fetchRecentSearch(query, startTime);
    for (const post of posts) {
      if (seen.has(post.id)) continue;
      seen.add(post.id);
      allPosts.push({ ...post, queryName: `trusted-${handle}` });
    }
  }

  return allPosts;
}

async function fetchRecentSearch(query, startTime) {
  const url = new URL("https://api.x.com/2/tweets/search/recent");
  url.searchParams.set("query", query);
  url.searchParams.set("start_time", startTime);
  url.searchParams.set("max_results", "50");
  url.searchParams.set("tweet.fields", "created_at,author_id,entities,public_metrics,lang");
  url.searchParams.set("expansions", "author_id");
  url.searchParams.set("user.fields", "name,username,verified");

  const response = await fetch(url, {
    headers: {
      authorization: `Bearer ${env.xBearerToken}`
    }
  });

  if (response.status === 429) {
    console.warn("X rate limit reached. The next scheduled run will continue.");
    return [];
  }

  if (!response.ok) {
    const body = await response.text();
    console.warn(`X search failed (${response.status}): ${body.slice(0, 300)}`);
    return [];
  }

  const payload = await response.json();
  const users = new Map((payload.includes?.users || []).map(user => [user.id, user]));
  return (payload.data || []).map(tweet => ({
    ...tweet,
    author: users.get(tweet.author_id) || null
  }));
}

async function buildCandidate(post, schoolsConfig, allowAi) {
  if (!isOfferText(post.text)) return null;

  const heuristic = extractHeuristic(post, schoolsConfig);
  let ai = null;
  let aiEvaluated = false;

  if (env.openAiKey && allowAi) {
    ai = await extractWithOpenAI(post).catch(error => {
      console.warn(`OpenAI extraction skipped for ${post.id}: ${error.message}`);
      return null;
    });
    aiEvaluated = Boolean(ai);
  }

  const merged = compactObject({
    ...heuristic,
    ...compactObject(ai || {}),
    xPostId: post.id,
    xUrl: `https://x.com/${post.author?.username || "i"}/status/${post.id}`,
    sourceText: post.text,
    lastOfferAt: post.created_at || new Date().toISOString()
  });

  merged.offerSchools = unique([...asArray(heuristic.offerSchools), ...asArray(ai?.offerSchools)]);
  merged.links = unique([
    ...asArray(heuristic.links),
    ...asArray(ai?.links),
    ai?.hudlUrl,
    ai?.ucReportUrl
  ]);
  merged.hudlUrl = merged.hudlUrl || firstMatchingUrl(merged.links, /hudl\.com/i);
  merged.ucReportUrl = merged.ucReportUrl || firstMatchingUrl(merged.links, /(ucreport|uc\.report|uc-report)/i);
  merged.name = cleanName(merged.name || post.author?.name || "Unknown Recruit");
  merged.position = normalizePosition(merged.position);
  merged.state = normalizeState(merged.state, schoolsConfig);

  if (!merged.gradYear && !merged.offerSchools.length) return null;

  merged.categories = categorize(merged, schoolsConfig);
  merged.hiddenGemScore = scoreHiddenGem(merged, schoolsConfig);
  if (merged.hiddenGemScore >= 70 && !merged.categories.includes("hidden")) {
    merged.categories.push("hidden");
  }
  if (!merged.categories.length) merged.categories.push("watch");
  merged.confidence = confidenceScore(merged);
  merged.brief = normalizeBrief(merged.brief) || buildRuleBrief(merged, schoolsConfig);
  merged.signals = buildSignals(merged, post.queryName);
  merged.id = `x-${post.id}`;
  merged.aiEvaluated = aiEvaluated;

  return merged;
}

function isOfferText(text = "") {
  return /(\boffer(ed)?\b|received an offer|earned an offer|blessed to receive|honored to receive)/i.test(text);
}

function extractHeuristic(post, schoolsConfig) {
  const text = post.text || "";
  const links = extractLinks(post);
  const state = detectState(text, schoolsConfig);
  const offerSchools = detectOfferSchools(text, schoolsConfig);
  const heightInches = parseHeight(text);
  const weightPounds = parseWeight(text);
  const gradYear = parseGradYear(text);
  const position = parsePosition(text);

  return compactObject({
    name: guessName(text, post.author?.name),
    gradYear,
    position,
    heightInches,
    weightPounds,
    city: "",
    state,
    highSchool: parseHighSchool(text),
    offerSchools,
    links,
    hudlUrl: firstMatchingUrl(links, /hudl\.com/i),
    ucReportUrl: firstMatchingUrl(links, /(ucreport|uc\.report|uc-report)/i)
  });
}

async function extractWithOpenAI(post) {
  const prompt = [
    "Extract a college football recruiting offer announcement from this X post.",
    "Return JSON only. Use null for unknown values.",
    "Fields: name, gradYear, position, heightInches, weightPounds, city, state, highSchool, offerSchools, hudlUrl, ucReportUrl, links, brief.",
    "brief must contain strengths and weaknesses arrays. Keep the evaluation cautious and based only on the post text.",
    `Post author: ${post.author?.name || ""} @${post.author?.username || ""}`,
    `Post text: ${post.text}`
  ].join("\n");

  const response = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.openAiKey}`,
      "content-type": "application/json"
    },
    body: JSON.stringify({
      model: env.openAiModel,
      temperature: 0.1,
      response_format: { type: "json_object" },
      messages: [
        {
          role: "system",
          content: "You extract structured recruiting data. Do not invent facts."
        },
        {
          role: "user",
          content: prompt
        }
      ]
    })
  });

  if (!response.ok) {
    throw new Error(`OpenAI API ${response.status}`);
  }

  const payload = await response.json();
  const content = payload.choices?.[0]?.message?.content;
  if (!content) return null;
  return JSON.parse(content);
}

function mergeCandidate(board, candidate, beforeIds, newItems, now) {
  const index = board.athletes.findIndex(item => item.id === candidate.id);
  const existing = index >= 0 ? board.athletes[index] : null;
  const merged = {
    ...existing,
    ...candidate,
    firstSeenAt: existing?.firstSeenAt || now.toISOString(),
    updatedAt: now.toISOString()
  };

  if (index >= 0) {
    board.athletes[index] = merged;
  } else {
    board.athletes.push(merged);
  }

  if (!beforeIds.has(candidate.id)) {
    newItems.push(merged);
  }
}

function markRecent(board, now) {
  const recentMs = 24 * 60 * 60 * 1000;
  for (const item of board.athletes) {
    const updated = new Date(item.updatedAt || item.lastOfferAt || 0);
    item.isNew = now - updated < recentMs;
  }
}

function categorize(candidate, schoolsConfig) {
  const detected = schoolMatches(candidate.offerSchools || [], schoolsConfig);
  const buckets = new Set(detected.map(item => item.bucket));
  const categories = [];
  const inFootprint = Boolean(candidate.state && schoolsConfig.footprintStates[candidate.state]);

  if (buckets.has("SEC")) categories.push("sec");
  if (!buckets.has("SEC") && buckets.has("P4")) categories.push("p4");
  if (buckets.has("G6") && inFootprint) categories.push("g6-footprint");

  return categories;
}

function scoreHiddenGem(candidate, schoolsConfig) {
  const profile = schoolsConfig.positionProfiles[candidate.position] || schoolsConfig.positionProfiles.ATH;
  let score = 20;

  if (candidate.heightInches && profile.heightInches) {
    const delta = candidate.heightInches - profile.heightInches;
    if (delta >= 1) score += 25;
    else if (delta >= 0) score += 20;
    else if (delta >= -1) score += 12;
  }

  if (candidate.weightPounds && profile.weightPounds) {
    const delta = candidate.weightPounds - profile.weightPounds;
    if (delta >= 0) score += 16;
    else if (delta >= -15) score += 10;
    else if (delta >= -25) score += 5;
  }

  if (candidate.state && schoolsConfig.footprintStates[candidate.state]) score += 15;
  if (candidate.gradYear && Number(candidate.gradYear) >= 2028) score += 8;

  const text = candidate.sourceText || "";
  if (/(all-state|all state|state champion|track|10\.[0-9]|verified|laser|multi-sport|multi sport)/i.test(text)) {
    score += 10;
  }

  const buckets = new Set(schoolMatches(candidate.offerSchools || [], schoolsConfig).map(item => item.bucket));
  if (buckets.has("G6") && !buckets.has("P4") && !buckets.has("SEC")) score += 10;
  if (buckets.has("SEC")) score -= 8;

  return Math.max(0, Math.min(99, Math.round(score)));
}

function buildRuleBrief(candidate, schoolsConfig) {
  const profile = schoolsConfig.positionProfiles[candidate.position] || schoolsConfig.positionProfiles.ATH;
  const strengths = [];
  const weaknesses = [];

  if (candidate.heightInches && profile.heightInches && candidate.heightInches >= profile.heightInches) {
    strengths.push(`Meets or exceeds the frame target for ${candidate.position || "his position"}.`);
  }
  if (candidate.state && schoolsConfig.footprintStates[candidate.state]) {
    strengths.push("Inside the Tennessee footprint, which makes follow-up and relationship mapping easier.");
  }
  if ((candidate.offerSchools || []).length) {
    strengths.push(`Offer activity from ${candidate.offerSchools.join(", ")} confirms active college interest.`);
  }
  if (!candidate.hudlUrl) {
    weaknesses.push("Hudl link was not found in the announcement and should be pulled manually.");
  }
  if (!candidate.ucReportUrl) {
    weaknesses.push("UC Report link was not found automatically.");
  }
  if (!candidate.heightInches || !candidate.weightPounds) {
    weaknesses.push("Verified height and weight are incomplete.");
  }
  if (!weaknesses.length) {
    weaknesses.push("Needs staff film review before any recruiting priority is assigned.");
  }

  return {
    strengths: strengths.length ? strengths : ["Offer announcement is relevant enough for staff review."],
    weaknesses
  };
}

function confidenceScore(candidate) {
  let score = 35;
  if (candidate.xUrl) score += 15;
  if (candidate.offerSchools?.length) score += 20;
  if (candidate.gradYear) score += 10;
  if (candidate.position) score += 8;
  if (candidate.state) score += 6;
  if (candidate.hudlUrl) score += 4;
  if (candidate.ucReportUrl) score += 2;
  return Math.min(99, score);
}

function buildSignals(candidate, queryName) {
  return unique([
    queryName,
    candidate.state ? "footprint-check" : "",
    candidate.hudlUrl ? "hudl" : "",
    candidate.ucReportUrl ? "uc-report" : "",
    ...(candidate.categories || [])
  ].filter(Boolean));
}

function detectOfferSchools(text, schoolsConfig) {
  const matches = [];
  const aliases = [];
  for (const school of schoolsConfig.schools) {
    aliases.push({ value: school.name, school });
    for (const alias of school.aliases || []) aliases.push({ value: alias, school });
  }
  aliases.sort((a, b) => b.value.length - a.value.length);

  for (const entry of aliases) {
    const pattern = new RegExp(`(^|[^a-z0-9])${escapeRegExp(entry.value)}([^a-z0-9]|$)`, "i");
    if (pattern.test(text)) matches.push(entry.school.name);
  }

  return unique(matches);
}

function schoolMatches(names, schoolsConfig) {
  const byName = new Map(schoolsConfig.schools.map(school => [school.name.toLowerCase(), school]));
  const matches = [];
  for (const name of names || []) {
    const direct = byName.get(String(name).toLowerCase());
    if (direct) matches.push(direct);
  }
  return matches;
}

function detectState(text, schoolsConfig) {
  for (const [abbr, name] of Object.entries(schoolsConfig.footprintStates)) {
    const full = new RegExp(`\\b${escapeRegExp(name)}\\b`, "i");
    if (full.test(text)) return abbr;
  }

  const safeAbbr = Object.keys(schoolsConfig.footprintStates).filter(abbr => !["IN"].includes(abbr));
  for (const abbr of safeAbbr) {
    const pattern = new RegExp(`(^|[\\s,/#])${abbr}($|[\\s,./#])`, "i");
    if (pattern.test(text)) return abbr;
  }
  return "";
}

function normalizeState(value, schoolsConfig) {
  if (!value) return "";
  const raw = String(value).trim();
  const upper = raw.toUpperCase();
  if (schoolsConfig.footprintStates[upper]) return upper;
  for (const [abbr, name] of Object.entries(schoolsConfig.footprintStates)) {
    if (name.toLowerCase() === raw.toLowerCase()) return abbr;
  }
  return upper.length === 2 ? upper : "";
}

function parseGradYear(text) {
  const classMatch = text.match(/\b(?:class of|c\/o|co|class)\s*['`]?(\d{2}|20\d{2})\b/i);
  if (classMatch) {
    const value = classMatch[1].length === 2 ? `20${classMatch[1]}` : classMatch[1];
    return Number(value);
  }
  const yearMatch = text.match(/\b(2026|2027|2028|2029|2030|2031)\b/);
  return yearMatch ? Number(yearMatch[1]) : null;
}

function parsePosition(text) {
  const positions = ["EDGE", "ATH", "QB", "RB", "WR", "TE", "OT", "OG", "OL", "DL", "DE", "DT", "LB", "CB", "DB", "S", "K", "P"];
  for (const pos of positions) {
    const pattern = new RegExp(`\\b${pos}\\b`, "i");
    if (pattern.test(text)) return normalizePosition(pos);
  }
  return "";
}

function normalizePosition(value) {
  if (!value) return "";
  const pos = String(value).toUpperCase().trim();
  if (["OT", "OG", "C"].includes(pos)) return "OL";
  if (["DE", "DT"].includes(pos)) return "DL";
  if (["FS", "SS"].includes(pos)) return "S";
  return pos;
}

function parseHeight(text) {
  const match = text.match(/\b([5-7])\s*(?:'|`|-|ft)\s*(\d{1,2})\b/i);
  if (!match) return null;
  const feet = Number(match[1]);
  const inches = Number(match[2]);
  if (inches > 11) return null;
  return feet * 12 + inches;
}

function parseWeight(text) {
  const match = text.match(/\b([1-3]\d{2})\s*(?:lbs?|pounds?)\b/i);
  return match ? Number(match[1]) : null;
}

function parseHighSchool(text) {
  const match = text.match(/\b([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})\s+(?:High School|HS)\b/);
  return match ? `${match[1]} High School` : "";
}

function guessName(text, authorName = "") {
  const byCongrats = text.match(/\b(?:congrats|congratulations)\s+(?:to\s+)?([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,2})\b/);
  if (byCongrats) return byCongrats[1];

  const cleanAuthor = String(authorName || "")
    .replace(/\b(?:QB|RB|WR|TE|OL|DL|LB|DB|ATH|EDGE)\b/gi, "")
    .replace(/\b(?:2026|2027|2028|2029|2030|2031)\b/g, "")
    .replace(/[|,@#].*$/, "")
    .trim();

  return cleanAuthor || "";
}

function cleanName(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .replace(/\b(?:football|recruiting|recruit)\b/gi, "")
    .trim()
    .slice(0, 80);
}

function extractLinks(post) {
  const links = [];
  for (const url of post.entities?.urls || []) {
    links.push(url.expanded_url || url.unwound_url || url.url);
  }
  const textLinks = String(post.text || "").match(/https?:\/\/\S+/g) || [];
  links.push(...textLinks.map(link => link.replace(/[),.]+$/, "")));
  return unique(links);
}

function firstMatchingUrl(links, pattern) {
  return (links || []).find(link => pattern.test(link)) || "";
}

function normalizeBrief(brief) {
  if (!brief) return null;
  const strengths = asArray(brief.strengths).filter(Boolean).slice(0, 3);
  const weaknesses = asArray(brief.weaknesses).filter(Boolean).slice(0, 3);
  if (!strengths.length && !weaknesses.length) return null;
  return { strengths, weaknesses };
}

async function sendAlert(items, webhookUrl) {
  const lines = items.slice(0, 10).map(item => {
    const schools = (item.offerSchools || ["Unknown school"]).join(", ");
    return `${item.name || "Unknown Recruit"} ${item.gradYear || "TBD"} ${item.position || ""} - ${schools} - ${item.xUrl}`;
  });
  const text = [`New offer alerts: ${items.length}`, ...lines].join("\n");
  const response = await fetch(webhookUrl, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ content: text, text })
  });
  if (!response.ok) {
    console.warn(`Alert webhook failed with status ${response.status}`);
  }
}

async function loadBoard(password) {
  const encrypted = await readJsonMaybe("data/athletes.encrypted.json");
  if (password && encrypted && encrypted.ciphertext !== "placeholder") {
    return decryptJson(encrypted, password);
  }
  const sample = await readJson("data/athletes.sample.json");
  return structuredClone(sample);
}

function encryptJson(value, password) {
  const salt = randomBytes(16);
  const iv = randomBytes(12);
  const key = pbkdf2Sync(password, salt, KDF_ITERATIONS, 32, "sha256");
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const encrypted = Buffer.concat([cipher.update(JSON.stringify(value), "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return {
    version: 1,
    algorithm: "AES-256-GCM",
    kdf: "PBKDF2-SHA256",
    iterations: KDF_ITERATIONS,
    salt: salt.toString("base64"),
    iv: iv.toString("base64"),
    ciphertext: Buffer.concat([encrypted, tag]).toString("base64"),
    updatedAt: new Date().toISOString()
  };
}

function decryptJson(payload, password) {
  if (!payload || payload.version !== 1 || !payload.ciphertext) {
    throw new Error("Encrypted board is missing or unsupported.");
  }
  const salt = Buffer.from(payload.salt, "base64");
  const iv = Buffer.from(payload.iv, "base64");
  const sealed = Buffer.from(payload.ciphertext, "base64");
  const encrypted = sealed.subarray(0, -16);
  const tag = sealed.subarray(-16);
  const key = pbkdf2Sync(password, salt, Number(payload.iterations || KDF_ITERATIONS), 32, "sha256");
  const decipher = createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAuthTag(tag);
  const decrypted = Buffer.concat([decipher.update(encrypted), decipher.final()]);
  return JSON.parse(decrypted.toString("utf8"));
}

async function readJson(relativePath) {
  return JSON.parse(await fs.readFile(path.join(ROOT, relativePath), "utf8"));
}

async function readJsonMaybe(relativePath) {
  try {
    return await readJson(relativePath);
  } catch {
    return null;
  }
}

async function writeJson(relativePath, value) {
  const target = path.join(ROOT, relativePath);
  await fs.mkdir(path.dirname(target), { recursive: true });
  await fs.writeFile(target, `${JSON.stringify(value, null, 2)}\n`);
}

function compactObject(value) {
  return Object.fromEntries(
    Object.entries(value || {}).filter(([, entry]) => {
      if (entry === null || entry === undefined || entry === "") return false;
      if (Array.isArray(entry) && entry.length === 0) return false;
      return true;
    })
  );
}

function unique(values) {
  return [...new Set((values || []).map(value => String(value).trim()).filter(Boolean))];
}

function asArray(value) {
  if (Array.isArray(value)) return value;
  if (value === null || value === undefined || value === "") return [];
  return [value];
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
