const MODELS = [
  "gemini-2.5-flash",
  "gemini-flash-latest",
  "gemini-3.8-flash",
  "gemini-flash-lite-latest",
  "gemini-pro-latest"
];

exports.handler = async (event) => {
  // CORS Headers
  const headers = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Content-Type": "application/json"
  };

  if (event.httpMethod === "OPTIONS") {
    return { statusCode: 200, headers, body: "" };
  }

  if (event.httpMethod !== "POST") {
    return { statusCode: 405, headers, body: JSON.stringify({ reply: "Method Not Allowed" }) };
  }

  const apiKey = (process.env.GEMINI_API_KEY || "").trim().replace(/^['"]|['"]$/g, "");
  if (!apiKey) {
    return {
      statusCode: 500,
      headers,
      body: JSON.stringify({ reply: "GEMINI_API_KEY is not configured in Netlify Environment Variables." })
    };
  }

  let body;
  try {
    body = JSON.parse(event.body || "{}");
  } catch (e) {
    return { statusCode: 400, headers, body: JSON.stringify({ reply: "Invalid JSON request." }) };
  }

  const userMessage = body.message;
  if (!userMessage) {
    return { statusCode: 400, headers, body: JSON.stringify({ reply: "Please provide a message." }) };
  }

  const lang = body.lang || "en";
  let systemInstruction = "You are Saarthi, a friendly AI health assistant helper for rural communities in India. " +
    "Help the user understand basic symptoms, common remedies, and hygiene tips in simple language. " +
    "Be empathetic and direct. " +
    "CRITICAL: Always start or include a clear medical disclaimer explaining that you are an AI " +
    "and not a real doctor, and suggest visiting a healthcare provider if symptoms are severe.";

  if (lang === "hi") {
    systemInstruction += " CRITICAL: Write your entire response in Hindi (हिन्दी) only.";
  } else {
    systemInstruction += " CRITICAL: Write your response in English.";
  }

  const payload = {
    system_instruction: {
      parts: [{ text: systemInstruction }]
    },
    contents: [
      {
        parts: [{ text: userMessage }]
      }
    ]
  };

  let lastError = null;
  for (const model of MODELS) {
    try {
      const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error?.message || `HTTP ${res.status}`);
      }

      const replyText = data.candidates?.[0]?.content?.parts?.[0]?.text;
      if (replyText) {
        return {
          statusCode: 200,
          headers,
          body: JSON.stringify({ reply: replyText })
        };
      }
    } catch (err) {
      console.warn(`Model ${model} failed:`, err.message);
      lastError = err;
    }
  }

  return {
    statusCode: 500,
    headers,
    body: JSON.stringify({
      reply: "Saarthi is temporarily busy. Please try again in a few moments."
    })
  };
};
