const MODELS = [
  "gemini-2.5-flash",
  "gemini-flash-latest",
  "gemini-3.8-flash",
  "gemini-flash-lite-latest",
  "gemini-pro-latest"
];

exports.handler = async (event) => {
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
    return { statusCode: 405, headers, body: JSON.stringify({ summary: "Method Not Allowed" }) };
  }

  const apiKey = (process.env.GEMINI_API_KEY || "").trim().replace(/^['"]|['"]$/g, "");
  if (!apiKey) {
    return {
      statusCode: 500,
      headers,
      body: JSON.stringify({
        summary: "GEMINI_API_KEY Missing",
        advice: "Please set the GEMINI_API_KEY environment variable in your Netlify site settings."
      })
    };
  }

  let body;
  try {
    body = JSON.parse(event.body || "{}");
  } catch (e) {
    return {
      statusCode: 400,
      headers,
      body: JSON.stringify({ summary: "Invalid request", advice: "Please provide file data." })
    };
  }

  const { fileData, fileName, mimeType: rawMime, lang = "en" } = body;
  if (!fileData) {
    return {
      statusCode: 400,
      headers,
      body: JSON.stringify({ summary: "No file provided", advice: "Please select a file to analyze." })
    };
  }

  // Strip data: prefix if present (e.g., data:application/pdf;base64,...)
  let base64Clean = fileData;
  let inferredMime = rawMime || "application/pdf";
  if (fileData.includes(",")) {
    const parts = fileData.split(",");
    base64Clean = parts[1];
    const mimeMatch = parts[0].match(/:(.*?);/);
    if (mimeMatch) inferredMime = mimeMatch[1];
  }

  if (fileName) {
    const fn = fileName.toLowerCase();
    if (fn.endsWith(".pdf")) inferredMime = "application/pdf";
    else if (fn.endsWith(".jpg") || fn.endsWith(".jpeg")) inferredMime = "image/jpeg";
    else if (fn.endsWith(".png")) inferredMime = "image/png";
  }

  let prompt = "Analyze this medical report image or document. Explain the values and findings in extremely simple, " +
    "educational, and rural-friendly language. Avoid complex jargon or explain it if used. " +
    "Highlight critical values (e.g. high/low hemoglobin, high blood sugar, etc.) in a friendly way. " +
    "Return your analysis structured in two clear parts:\n" +
    "1. Summary of the report.\n" +
    "2. Simple educational advice and suggested next steps (e.g., whether to see a general practitioner or specialist).";

  if (lang === "hi") {
    prompt += " CRITICAL: You must write your entire response (both summary and advice) in Hindi (हिन्दी) only.";
  } else {
    prompt += " CRITICAL: Write your entire response in English.";
  }

  const payload = {
    contents: [
      {
        parts: [
          {
            inline_data: {
              mime_type: inferredMime,
              data: base64Clean
            }
          },
          {
            text: prompt
          }
        ]
      }
    ],
    safety_settings: [
      { category: "HARM_CATEGORY_HARASSMENT", threshold: "BLOCK_NONE" },
      { category: "HARM_CATEGORY_HATE_SPEECH", threshold: "BLOCK_NONE" },
      { category: "HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold: "BLOCK_NONE" },
      { category: "HARM_CATEGORY_DANGEROUS_CONTENT", threshold: "BLOCK_NONE" }
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

      const textOutput = data.candidates?.[0]?.content?.parts?.[0]?.text;
      if (textOutput) {
        let summary = textOutput;
        let advice = (lang === "hi")
          ? "कृपया इन परिणामों की नैदानिक जांच के लिए अपने डॉक्टर से परामर्श लें।"
          : "Please share these results with your healthcare provider for clinical evaluation.";

        const splitPattern = /(?:\n|\A)\s*[-*_\s]*\s*(?:#{1,4}\s*)?(?:2[\.\)]\s*|part\s*2[:\.\-]?\s*|सलाह|सुझाव|advice\b)[^\n]*\n/i;
        const match = textOutput.match(splitPattern);
        if (match) {
          summary = textOutput.substring(0, match.index).trim();
          advice = textOutput.substring(match.index + match[0].length).trim();
          summary = summary.replace(/(?:\n|\A)\s*[-*_\s]*\s*(?:#{1,4}\s*)?(?:1[\.\)]\s*|part\s*1[:\.\-]?\s*|summary\b|सारांश\b)[^\n]*\n/gi, '').trim();
          summary = summary.replace(/[\r\n]+\s*---+\s*$/, '').trim();
        }

        return {
          statusCode: 200,
          headers,
          body: JSON.stringify({ summary, advice })
        };
      }
    } catch (err) {
      console.warn(`Model ${model} failed in analyze-report:`, err.message);
      lastError = err;
    }
  }

  return {
    statusCode: 500,
    headers,
    body: JSON.stringify({
      summary: "Analysis failed",
      advice: lastError ? lastError.message : "Unable to analyze report. Please try again."
    })
  };
};
