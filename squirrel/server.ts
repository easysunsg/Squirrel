import dns from "node:dns";
import path from "node:path";
import express, { type Request, type Response } from "express";
import { createServer as createViteServer } from "vite";

dns.setDefaultResultOrder("ipv4first");

const app = express();
const PORT = Number(process.env.PORT || 3000);
const API_BASE_URL = process.env.SQUIRREL_API_BASE_URL || "http://127.0.0.1:8000";

app.use(express.json({ limit: "20mb" }));

async function proxyJson(req: Request, res: Response, targetPath: string) {
  try {
    const response = await fetch(`${API_BASE_URL}${targetPath}`, {
      method: req.method,
      headers: {
        "Content-Type": "application/json",
      },
      body: req.method === "GET" || req.method === "HEAD" ? undefined : JSON.stringify(req.body),
    });

    const text = await response.text();
    res.status(response.status);
    res.type(response.headers.get("content-type") || "application/json");
    res.send(text);
  } catch (error) {
    console.error(`Proxy request failed for ${targetPath}:`, error);
    res.status(502).json({
      error: "Upstream server request failed",
      target: `${API_BASE_URL}${targetPath}`,
    });
  }
}

app.get("/api/health", async (req, res) => {
  await proxyJson(req, res, "/api/health");
});

app.get("/api/messages", async (req, res) => {
  await proxyJson(req, res, "/api/messages");
});

app.put("/api/messages", async (req, res) => {
  await proxyJson(req, res, "/api/messages");
});

app.delete("/api/messages", async (req, res) => {
  await proxyJson(req, res, "/api/messages");
});

app.post("/api/chat", async (req, res) => {
  await proxyJson(req, res, "/api/chat");
});

app.post("/api/recognize-item", async (req, res) => {
  const locations = Array.isArray(req.body?.locations) ? req.body.locations : [];
  const pool = [
    { name: "苹果", category: "food", quantity: 4, unit: "个", note: "建议冷藏保存", tags: ["水果", "即食"] },
    { name: "感冒药", category: "medicine", quantity: 1, unit: "盒", note: "放在干燥阴凉处", tags: ["常备药"] },
    { name: "充电器", category: "electronics", quantity: 1, unit: "件", note: "避免受潮", tags: ["数码"] },
    { name: "面膜", category: "cosmetics", quantity: 3, unit: "片", note: "注意保质期", tags: ["护肤"] },
  ];
  const item = pool[Math.floor(Math.random() * pool.length)];

  res.json({
    success: true,
    item: {
      ...item,
      location: locations[0] || "默认位置",
      purchaseDate: new Date().toISOString().split("T")[0],
      expiryDate: new Date(Date.now() + 15 * 24 * 60 * 60 * 1000).toISOString().split("T")[0],
      remindDaysBefore: item.category === "food" ? 3 : 7,
    },
    message: "已经识别出一件物品，并生成了一份可直接入库的建议。",
  });
});

async function main() {
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (_req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`[squirrel] web app listening on http://0.0.0.0:${PORT}`);
    console.log(`[squirrel] proxying api requests to ${API_BASE_URL}`);
  });
}

main().catch((error) => {
  console.error("Failed to start squirrel dev server:", error);
  process.exit(1);
});
