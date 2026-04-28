export default {
  async fetch(request, env) {
    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    if (request.method !== "POST") {
      return jsonResponse({ error: "Method not allowed." }, 405, corsHeaders);
    }

    let payload;
    try {
      payload = await request.json();
    } catch {
      return jsonResponse({ error: "Invalid JSON body." }, 400, corsHeaders);
    }

    const action = (payload.action || "").toLowerCase();
    const email = (payload.email || "").trim().toLowerCase();

    if (!["subscribe", "unsubscribe"].includes(action)) {
      return jsonResponse({ error: "Action must be subscribe or unsubscribe." }, 400, corsHeaders);
    }

    if (!isValidEmail(email)) {
      return jsonResponse({ error: "Enter a valid email address." }, 400, corsHeaders);
    }

    const owner = env.GITHUB_OWNER;
    const repo = env.GITHUB_REPO;
    const branch = env.GITHUB_BRANCH || "main";
    const path = env.SUBSCRIBERS_PATH || "subscribers.txt";
    const token = env.GITHUB_TOKEN;

    if (!owner || !repo || !token) {
      return jsonResponse({ error: "Missing GitHub backend configuration." }, 500, corsHeaders);
    }

    const contentsUrl = `https://api.github.com/repos/${owner}/${repo}/contents/${path}?ref=${branch}`;
    const headers = {
      "Authorization": `Bearer ${token}`,
      "Accept": "application/vnd.github+json",
      "User-Agent": "DailyFeed-Subscriber-Worker",
    };

    const currentResponse = await fetch(contentsUrl, { headers });
    if (!currentResponse.ok) {
      const errorText = await currentResponse.text();
      return jsonResponse({ error: `Failed to read subscribers file: ${errorText}` }, 502, corsHeaders);
    }

    const currentFile = await currentResponse.json();
    const decoded = decodeBase64(currentFile.content || "");
    const subscribers = decoded
      .split("\n")
      .map((line) => line.trim().toLowerCase())
      .filter(Boolean);

    let changed = false;
    if (action === "subscribe" && !subscribers.includes(email)) {
      subscribers.push(email);
      changed = true;
    }

    if (action === "unsubscribe") {
      const nextSubscribers = subscribers.filter((value) => value !== email);
      changed = nextSubscribers.length !== subscribers.length;
      subscribers.length = 0;
      subscribers.push(...nextSubscribers);
    }

    const uniqueSorted = [...new Set(subscribers)].sort();
    const newContent = uniqueSorted.join("\n") + (uniqueSorted.length ? "\n" : "");

    if (!changed) {
      return jsonResponse({ message: `No change needed for ${email}.` }, 200, corsHeaders);
    }

    const updateResponse = await fetch(`https://api.github.com/repos/${owner}/${repo}/contents/${path}`, {
      method: "PUT",
      headers,
      body: JSON.stringify({
        message: `${action === "subscribe" ? "Subscribe" : "Unsubscribe"} ${email}`,
        content: encodeBase64(newContent),
        sha: currentFile.sha,
        branch,
      }),
    });

    if (!updateResponse.ok) {
      const errorText = await updateResponse.text();
      return jsonResponse({ error: `Failed to update subscribers file: ${errorText}` }, 502, corsHeaders);
    }

    return jsonResponse({
      message: action === "subscribe"
        ? `Subscribed ${email}.`
        : `Unsubscribed ${email}.`
    }, 200, corsHeaders);
  },
};

function jsonResponse(payload, status, headers) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
  });
}

function isValidEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

function decodeBase64(input) {
  return Uint8Array.from(atob(input.replace(/\n/g, "")), (char) => char.charCodeAt(0))
    .reduce((text, byte) => text + String.fromCharCode(byte), "");
}

function encodeBase64(input) {
  return btoa(unescape(encodeURIComponent(input)));
}
