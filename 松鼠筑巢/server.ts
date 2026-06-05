import express from "express";
import path from "path";
import { createServer as createViteServer } from "vite";
import { GoogleGenAI, Type } from "@google/genai";

let aiClient: GoogleGenAI | null = null;

function getAiClient(): GoogleGenAI {
  if (!aiClient) {
    const apiKey = process.env.GEMINI_API_KEY;
    if (!apiKey || apiKey === "MY_GEMINI_API_KEY" || apiKey.includes("MY_GEMINI_API_KEY")) {
      console.warn("WARNING: GEMINI_API_KEY is not defined or is placeholder. Using mock AI capabilities.");
    }
    aiClient = new GoogleGenAI({
      apiKey: apiKey || "MOCK_KEY",
      httpOptions: {
        headers: {
          'User-Agent': 'aistudio-build',
        }
      }
    });
  }
  return aiClient;
}

async function startServer() {
  const app = express();
  app.use(express.json());
  const PORT = 3000;

  // --- API Routes ---

  // Endpoint 1: Lightning Ingestion parser
  app.post("/api/lightning", async (req, res) => {
    try {
      const { text } = req.body;
      if (!text || text.trim() === "") {
        return res.status(400).json({ error: "Text is empty." });
      }

      const apiKey = process.env.GEMINI_API_KEY;
      const isMock = !apiKey || apiKey === "MY_GEMINI_API_KEY" || apiKey.includes("MY_GEMINI_API_KEY");

      if (isMock) {
        // Mock classification fallback
        const lower = text.toLowerCase();
        let title = text.slice(0, 15);
        let spaceName = "主厨房";
        let location = "厨房二级柜";
        let remainingPct = 50;
        let count = 1;
        let unit = "个";
        let icon = "package_2";

        if (lower.includes("牛奶") || lower.includes("奶")) {
          title = "鲜牛奶";
          remainingPct = 20;
          unit = "盒";
          icon = "kitchen";
        } else if (lower.includes("工具") || lower.includes("锤") || lower.includes("螺丝")) {
          title = "五金工具";
          spaceName = "车库工具";
          location = "车库工具箱";
          remainingPct = 90;
          unit = "个";
          icon = "construction";
        } else if (lower.includes("药") || lower.includes("维c")) {
          title = "应急药品";
          spaceName = "储藏间";
          location = "药箱";
          remainingPct = 100;
          unit = "瓶";
          icon = "medication";
        } else if (lower.includes("纸") || lower.includes("贴")) {
          title = "办公物品";
          spaceName = "储藏间";
          location = "书架";
          remainingPct = 40;
          unit = "叠";
          icon = "edit_note";
        }

        return res.json({
          items: [{
            title,
            spaceName,
            location,
            remainingPct,
            count,
            unit,
            icon
          }]
        });
      }

      const ai = getAiClient();
      const prompt = `你是一个非常聪明的收纳评估专家，请从用户的以下描述中，帮他梳理出将要录入或者吃掉/消耗（如果描述是吃、用了某些东西，则扣除后剩余低于30%）的物品，并整理成标准JSON数据。
描述: "${text}"

请提取出物品的：
- title: 物品名（精简，例如：全麦面包，圣代，螺丝刀，洗洁精，牛奶等）
- spaceName: 录入空间（只能属于以下三个之一：'主厨房', '储藏间', '车库工具'）
- location: 推荐的存放具体位置描述（例如：物理层架、吧台、二级柜、冷冻室等）
- remainingPct: 预测的当前剩余百分比（整数 0 - 100。如果是带进来的新物品，设在 80-100 之间；如果提到了吃掉/用完了，设在 0-15 之间，如果还剩一点点，设在 15-35 之间）
- count: 数量（整数）
- unit: 单位（例如：瓶、代、件、盒、个）
- icon: 对应的最佳 Material Symbol Icon 标识名称（只能属于以下之一：'bakery_dining', 'construction', 'edit_note', 'local_cafe', 'cleaning_services', 'medication', 'kitchen', 'shelves', 'garage', 'package_2'）`;

      const response = await ai.models.generateContent({
        model: "gemini-3.5-flash",
        contents: prompt,
        config: {
          responseMimeType: "application/json",
          responseSchema: {
            type: Type.OBJECT,
            properties: {
              items: {
                type: Type.ARRAY,
                items: {
                  type: Type.OBJECT,
                  properties: {
                    title: { type: Type.STRING },
                    spaceName: { type: Type.STRING },
                    location: { type: Type.STRING },
                    remainingPct: { type: Type.INTEGER },
                    count: { type: Type.INTEGER },
                    unit: { type: Type.STRING },
                    icon: { type: Type.STRING }
                  },
                  required: ["title", "spaceName", "location", "remainingPct", "count", "unit", "icon"]
                }
              }
            },
            required: ["items"]
          }
        }
      });

      const resultText = response.text || "{}";
      const parsed = JSON.parse(resultText);
      res.json(parsed);
    } catch (error: any) {
      console.error("Gemini Ingestion parsing failed:", error);
      res.status(500).json({ error: error.message || "Failed to parse item" });
    }
  });

  // Endpoint 2: AI Companion Chatbot
  app.post("/api/chat", async (req, res) => {
    try {
      const { chatHistory, currentInventory } = req.body;
      const apiKey = process.env.GEMINI_API_KEY;
      const isMock = !apiKey || apiKey === "MY_GEMINI_API_KEY" || apiKey.includes("MY_GEMINI_API_KEY");

      const conversationStr = chatHistory
        .map((m: any) => `${m.sender === "user" ? "主人" : "小松鼠管家"}: ${m.text}`)
        .join("\n");

      if (isMock) {
        // Mock fallback responses
        const lastMsg = chatHistory[chatHistory.length - 1]?.text || "";
        let text = "小松鼠收到啦！我会全力帮您照看属于我们的筑巢空间。今天也要把家里整理得暖融融、井井有条哦！🐿️";
        let cardData = null;

        if (lastMsg.includes("过期") || lastMsg.includes("保质")) {
          text = "哎呀！小松鼠刚替您检查完，咱们厨房里的 [全麦面包] 已经快接近保质期啦（告急，剩余15%）。咱们应该赶紧把它消灭掉！或者您想要把它加入下一期的备忘清单吗？";
        } else if (lastMsg.includes("螺丝") || lastMsg.includes("工具")) {
          text = "呜哈！找到啦！根据库存记载，您的五金螺丝刀和工具组件，正乖乖躺在【车库- A4搁板】的五金工具箱里哦。当前分类：车库工具。需要我带您过去看看吗？";
          cardData = {
            title: "五金工具套装",
            image: "https://lh3.googleusercontent.com/aida-public/AB6AXuAi0e0pMmh7n9_aGTW81tBycuiOEyAZPQx9amTGNI61Tv6lVT4Cy-EJ7aNh_Jk4aJV3gAJ9c2L6_pM2Rzalf78pA3hiaojD3WUXPGNsCVyMz0RmYHmDvBTj5IYh-9d9FDeB59eiXWLIcQEsNdWQuQqYNdEwJaHhPkIjRymaNmxfiAi0EE30ZVL_HWQS5-YbunGoYMbW_0qHo_2e-l32j1TUiNFhLAEBJmGWkk3iaJlEG3fPm8vwTzK9AOaV_BXT2YvPC4IbCfyP1g5i",
            category: "车库工具",
            quantity: 8,
            spaceName: "车库工具"
          };
        } else if (lastMsg.includes("吃") || lastMsg.includes("吃点什么")) {
          text = "根据咱手头的备用存货，小松鼠强烈推荐今天傍晚来一顿：【番茄牛腩】！🍅 如果您觉得不合胃口，咱也可以随时换一个哦。您看如何？";
        }

        return res.json({ text, cardData });
      }

      const ai = getAiClient();
      const prompt = `你是一个非常可爱、勤劳、专业又活泼的智能家居松鼠管家（名字叫“小松鼠”或“松鼠管家”），主人用智能设备向你呼叫。
你的说话风格非常调皮温柔，多使用“！、～、🐿️”等语气助词和表情包，但对于整理和库存细节极为敏锐。

主人的库存当前有如下物品：
${JSON.stringify(currentInventory)}

最近的对话历史如下：
${conversationStr}

请你给出一个非常符合松鼠管家口味的回答，并评估：
1. 主人是否在请求你识别、录入一些新的实体工具或食材作为新库存？如果是，你可以在回答里确认，并在返回格式中指示我们需要弹出一个行动确认卡，以便方便用户直接在卡片上操作修改。
2. 给出详细的对话文本作为 answers。

请严格根据以下 JSON Schema 返回两个字段：
- replyText: 你的拟人化松鼠管家呼应回答文本（注意符合可爱的松鼠口吻，包含emoji）。
- detectedActionCard: 如果检测到用户提到了想把某些特定物品入库（例如：牛奶、便利贴、应急箱、工具、螺丝刀、洗洁精等），设置这个卡片结构体对象，否则设置为 null。该结构体属性包括：
  * title: 识别出的物品名称 (STRING)
  * category: 分类类别，只能为 "主厨房"、"储藏间"、"车库工具"、"已过期" 等之一 (STRING)
  * quantity: 数量，整数 (INTEGER)
  * spaceName: 空间名，对应为 "主厨房"、"储藏间"、"车库工具" 之一 (STRING)
  * image: 可使用的图片链接 (STRING)，你可以匹配给用户最接近的图片大图：
    - 工具类使用: "https://lh3.googleusercontent.com/aida-public/AB6AXuAi0e0pMmh7n9_aGTW81tBycuiOEyAZPQx9amTGNI61Tv6lVT4Cy-EJ7aNh_Jk4aJV3gAJ9c2L6_pM2Rzalf78pA3hiaojD3WUXPGNsCVyMz0RmYHmDvBTj5IYh-9d9FDeB59eiXWLIcQEsNdWQuQqYNdEwJaHhPkIjRymaNmxfiAi0EE30ZVL_HWQS5-YbunGoYMbW_0qHo_2e-l32j1TUiNFhLAEBJmGWkk3iaJlEG3fPm8vwTzK9AOaV_BXT2YvPC4IbCfyP1g5i"
    - 面包厨房用品使用: "https://lh3.googleusercontent.com/aida-public/AB6AXuBoPhESGTYP3GUAiYTau0y0nZKLASC3CGFMhxU6qITfnldHE95VJYlVKSbB9HvHjiMk6nTcnF8Enc1rOiHQ8QAKqhoXCSsA6pzRXduFt-FYD0RILbD2-IvfqKOnhievROA3aN_3S3Kz48B0-a_9yTfkLi4BjQUP74r_xsX36UBSproGcwzUtZq0QvmSiRuj4TsQi99qAaHcn2jBdzWVEkprytD4ALr6sswRrU4CbrcfkWtJtY0CbAEd-NXwOldf7uNO6S3gCTytsZUJ"`;

      const response = await ai.models.generateContent({
        model: "gemini-3.5-flash",
        contents: prompt,
        config: {
          responseMimeType: "application/json",
          responseSchema: {
            type: Type.OBJECT,
            properties: {
              replyText: { type: Type.STRING },
              detectedActionCard: {
                type: Type.OBJECT,
                properties: {
                  title: { type: Type.STRING },
                  category: { type: Type.STRING },
                  quantity: { type: Type.INTEGER },
                  spaceName: { type: Type.STRING },
                  image: { type: Type.STRING }
                },
                required: ["title", "category", "quantity", "spaceName"]
              }
            },
            required: ["replyText"]
          }
        }
      });

      const resObj = JSON.parse(response.text || "{}");
      res.json({
        text: resObj.replyText,
        cardData: resObj.detectedActionCard || null
      });
    } catch (error: any) {
      console.error("Gemini companion chat failed:", error);
      res.status(500).json({ error: error.message || "Failed to process chat" });
    }
  });

  // Endpoint 3: Recipe recommendation builder
  app.post("/api/recipe", async (req, res) => {
    try {
      const { inventory, excludedRecipeTitle, systemPreferences } = req.body;
      const apiKey = process.env.GEMINI_API_KEY;
      const isMock = !apiKey || apiKey === "MY_GEMINI_API_KEY" || apiKey.includes("MY_GEMINI_API_KEY");

      if (isMock) {
        // Cycle between mock responses
        const recipes = [
          {
            title: "番茄牛腩",
            description: "根据你的冰箱存货，我们发现番茄还剩2个，牛肉需要尽快吃掉。再配上仓库里的洋葱，完美！",
            ingredients: "番茄 2个, 牛腩 300g, 洋葱 1个, 冰糖、生抽适量",
            steps: ["牛腩切块冷水下锅焯水备用", "番茄去皮切块，一部分炒起沙，一部分留着最后成型", "放入牛腩、洋葱、香料，加水大火烧开转小火焖煮1小时", "加入另一半番茄，稍微收汁即可盛出！"]
          },
          {
            title: "香烤坚果面包片",
            description: "发现你的常备全麦面包已经临期了（告急！剩15%），坚果也剩一小把，用来烤酥香面包片非常搭配！",
            ingredients: "全麦面包 2片, 混合坚果 一小把, 黄油脂少量, 蜂蜜适量",
            steps: ["将全麦面包涂抹极少量黄油脂", "混合坚果压碎洒在面包片上", "烤箱预热180度，烤5-8分钟直至面包边缘金黄酥脆", "出炉淋一点点蜂蜜，酥香脆口！"]
          },
          {
            title: "清爽蔬菜沙拉配咖啡",
            description: "早上来点清爽的吧！配合您剩70%的咖啡豆磨一杯暖烘烘的手冲，再把剩下的洗洁精洗净清爽爽的果蔬，元气满满！",
            ingredients: "清爽生菜叶, 番茄、苹果片适量, 现磨咖啡 1杯, 醋汁少许",
            steps: ["果蔬洗净切好装盘", "淋上少许醋汁调味入味", "磨咖啡粉，90℃热水冲泡一杯热气腾腾的黑咖啡", "一口咖啡一口果蔬，开始清爽精致的一天！"]
          }
        ];

        let index = 0;
        if (excludedRecipeTitle) {
          const foundIndex = recipes.findIndex(r => r.title === excludedRecipeTitle);
          if (foundIndex !== -1) {
            index = (foundIndex + 1) % recipes.length;
          }
        }
        return res.json({ recipe: recipes[index] });
      }

      const ai = getAiClient();
      const allergiesStr = systemPreferences?.allergies?.join(",") || "无";
      const lifestyleStr = systemPreferences?.lifestyle || "均衡饮食";

      const prompt = `根据用户目前的厨房库存、忌口过敏史和生活标签，帮用户规划一道健康美味的主推食谱：
物品详情：
${JSON.stringify(inventory)}

过敏与忌口：
${allergiesStr}

生活方式：
${lifestyleStr}

排除的上一个食谱标题（不能和其重复，以便用户“换一个”）：
"${excludedRecipeTitle || ""}"

请结合当前库存有的或者接近临期的食品（如面包、坚果、番茄等），帮用户智能推荐符合其生活偏好的食谱，并严密返回如下格式的JSON：
- title: 食谱完整名字 (STRING)
- description: 食谱简短可爱的说明，指出这是利用了他库存里哪几样快过期/需要消耗的物品 (STRING)
- ingredients: 食材明细（包含用量描述） (STRING)
- steps: 制作简练步骤 (ARRAY of STRING)`;

      const response = await ai.models.generateContent({
        model: "gemini-3.5-flash",
        contents: prompt,
        config: {
          responseMimeType: "application/json",
          responseSchema: {
            type: Type.OBJECT,
            properties: {
              title: { type: Type.STRING },
              description: { type: Type.STRING },
              ingredients: { type: Type.STRING },
              steps: {
                type: Type.ARRAY,
                items: { type: Type.STRING }
              }
            },
            required: ["title", "description", "ingredients", "steps"]
          }
        }
      });

      const parsed = JSON.parse(response.text || "{}");
      res.json({ recipe: parsed });
    } catch (error: any) {
      console.error("Gemini recipe planning failed:", error);
      res.status(500).json({ error: error.message || "Failed to plan recipe" });
    }
  });


  // --- Vite dev server or static build serving backend middleware setup ---

  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://localhost:${PORT}`);
  });
}

startServer();
