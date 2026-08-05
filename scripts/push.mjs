import fs from "node:fs";
import process from "node:process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { PushApi } = require("all-pusher-api");

function argument(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || !process.argv[index + 1]) {
    throw new Error(`缺少参数 ${name}`);
  }
  return process.argv[index + 1];
}

function loadChannels() {
  const raw = process.env.ALL_PUSH_CONFIG || "";
  if (!raw.trim()) throw new Error("缺少 ALL_PUSH_CONFIG");
  const parsed = JSON.parse(raw);
  const channels = Array.isArray(parsed) ? parsed : parsed.channels;
  if (!Array.isArray(channels) || channels.length === 0) {
    throw new Error("ALL_PUSH_CONFIG 必须包含非空渠道数组");
  }
  return channels;
}

function splitLongBlock(block, maxLength) {
  const result = [];
  let rest = block;
  while (rest.length > maxLength) {
    let cut = rest.lastIndexOf("\n", maxLength);
    if (cut < Math.floor(maxLength / 2)) cut = maxLength;
    result.push(rest.slice(0, cut));
    rest = rest.slice(cut).replace(/^\n+/, "");
  }
  if (rest) result.push(rest);
  return result;
}

function splitMessage(message, maxLength) {
  if (!maxLength || message.length <= maxLength) return [message];
  const blocks = message.split(/\n{2,}/).flatMap((block) =>
    block.length > maxLength ? splitLongBlock(block, maxLength) : [block]
  );
  const chunks = [];
  let current = "";
  for (const block of blocks) {
    const candidate = current ? `${current}\n\n${block}` : block;
    if (candidate.length > maxLength && current) {
      chunks.push(current);
      current = block;
    } else {
      current = candidate;
    }
  }
  if (current) chunks.push(current);
  return chunks;
}

function defaultLimit(name, format) {
  if (format === "html") return 0;
  if (["telegrambot", "qqbot"].includes(name.toLowerCase())) return 3500;
  return 12000;
}

function cleanResult(result) {
  return {
    status: Number(result?.status || 0),
    statusText: String(result?.statusText || ""),
    extraMessage:
      typeof result?.extraMessage === "string" ? result.extraMessage : undefined,
  };
}

function asStringList(value) {
  if (Array.isArray(value)) {
    return value.flatMap((item) => asStringList(item));
  }
  if (typeof value !== "string") return [];
  return value
    .split(/[;,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function getEmailApiConfig(channel) {
  const config = channel.config && typeof channel.config === "object"
    ? channel.config
    : {};
  const sender = config.sender && typeof config.sender === "object"
    ? config.sender
    : {};
  const recipients = config.to ?? config.recipients ?? config.recipient;
  const provider = String(
    channel.provider || config.provider || channel.name || ""
  ).toLowerCase();
  return {
    provider,
    apiKey: String(config.api_key || config.apiKey || "").trim(),
    fromEmail: String(
      config.from_email || config.fromEmail || sender.email || ""
    ).trim(),
    fromName: String(
      config.from_name || config.fromName || sender.name || ""
    ).trim(),
    to: asStringList(recipients),
    endpoint: String(config.endpoint || "").trim(),
  };
}

async function sendEmailApi(channel, payload) {
  const config = getEmailApiConfig(channel);
  if (!config.apiKey) throw new Error("邮件 API 缺少 api_key");
  if (!config.fromEmail) throw new Error("邮件 API 缺少 from_email");
  if (!config.to.length) throw new Error("邮件 API 缺少收件人 to");

  const from = config.fromName
    ? `${config.fromName} <${config.fromEmail}>`
    : config.fromEmail;
  const subject = String(payload.title || "财经日报");
  const html = String(payload.html || payload.text || "");
  const text = String(payload.text || "");
  let url;
  let body;
  let headers = { "Content-Type": "application/json" };

  if (config.provider === "resend") {
    url = config.endpoint || "https://api.resend.com/emails";
    headers.Authorization = `Bearer ${config.apiKey}`;
    body = { from, to: config.to, subject, html, text };
  } else if (config.provider === "brevo" || config.provider === "sendinblue") {
    url = config.endpoint || "https://api.brevo.com/v3/smtp/email";
    headers["api-key"] = config.apiKey;
    body = {
      sender: { email: config.fromEmail, ...(config.fromName ? { name: config.fromName } : {}) },
      to: config.to.map((email) => ({ email })),
      subject,
      htmlContent: html,
      textContent: text,
    };
  } else {
    throw new Error(`不支持的邮件 API provider: ${config.provider || "空"}`);
  }

  const response = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  const responseText = await response.text();
  if (!response.ok) {
    let detail = responseText;
    try {
      const parsed = JSON.parse(responseText);
      detail = parsed.message || parsed.error || parsed.name || responseText;
    } catch {
      // Keep the plain response for providers that do not return JSON.
    }
    return {
      status: response.status,
      statusText: `邮件 API ${response.status}: ${String(detail).slice(0, 500)}`,
    };
  }
  return {
    status: response.status,
    statusText: "Success",
    extraMessage: responseText.slice(0, 1000),
  };
}

async function sendChannel(channel, payload) {
  const id = String(channel.id || "");
  const name = String(channel.name || "");
  const format = ["text", "markdown", "html"].includes(channel.format)
    ? channel.format
    : "markdown";
  if (!id || !name || typeof channel.config !== "object") {
    return { id, status: "failed", error: "渠道缺少 id/name/config" };
  }

  const body = String(payload[format] || payload.text || "");
  const configuredLimit = Number(channel.max_length);
  const maxLength = Number.isFinite(configuredLimit)
    ? configuredLimit
    : defaultLimit(name, format);
  const parts = splitMessage(body, maxLength);
  const previous = new Set((payload.completed_parts?.[id] || []).map(Number));
  const completed = new Set([...previous].filter((index) => index < parts.length));
  const details = [];

  for (let index = 0; index < parts.length; index += 1) {
    if (completed.has(index)) continue;
    const title =
      parts.length > 1 ? `${payload.title} (${index + 1}/${parts.length})` : payload.title;
    let result;
    if (["resend", "brevo", "sendinblue"].includes(name.toLowerCase()) || channel.provider) {
      result = await sendEmailApi(channel, { ...payload, title, [format]: parts[index] });
    } else {
      const api = new PushApi([{ name, config: channel.config }]);
      const response = await api.send({ message: parts[index], title, type: format });
      result = cleanResult(response[0]?.result);
    }
    details.push({ index, ...result });
    if (result.status >= 200 && result.status < 300) {
      completed.add(index);
    } else {
      return {
        id,
        name,
        status: "failed",
        error: result.statusText || `status ${result.status}`,
        completed_parts: [...completed].sort((a, b) => a - b),
        parts_total: parts.length,
        details,
      };
    }
  }

  return {
    id,
    name,
    status: "success",
    completed_parts: [...completed].sort((a, b) => a - b),
    parts_total: parts.length,
    details,
  };
}

async function main() {
  const payloadPath = argument("--payload");
  const resultPath = argument("--result");
  const payload = JSON.parse(fs.readFileSync(payloadPath, "utf8"));
  const targets = new Set(payload.target_ids || []);
  const channels = loadChannels().filter((channel) => targets.has(String(channel.id)));
  const results = [];
  for (const channel of channels) {
    try {
      results.push(await sendChannel(channel, payload));
    } catch (error) {
      results.push({
        id: String(channel.id || ""),
        name: String(channel.name || ""),
        status: "failed",
        error: error instanceof Error ? error.message : String(error),
        completed_parts: payload.completed_parts?.[String(channel.id)] || [],
        parts_total: 0,
      });
    }
  }
  fs.writeFileSync(resultPath, JSON.stringify(results, null, 2), "utf8");
  for (const result of results) {
    console.log(`${result.id}: ${result.status}`);
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : String(error));
  process.exitCode = 1;
});
