为了全面测试我们刚刚重构的 LangGraph 智能体拓扑结构及底层 State 锁机制，我们需要设计一套**高覆盖率的测试用例集（Test Suite）**。

以下为你穷举日常生活中最典型的 **7 大类真实话术场景**。这些用例不仅包含用户输入，还明确了“前置系统状态”**、**“预期的 LangGraph 节点内部流转路径”**以及**“期望的最终系统答复”，你可以直接把它们录入自动化测试脚本（如 pytest）或进行手动冒烟测试。

---

### 一、 常规原子变动场景（无冲突、无歧义）

#### 测试用例 1.1：干净的单品新增入库

* **用户操作人**：老公 (`user_husband`)
* **输入话术**：“买了两盒草莓，放进冰箱冷藏层了。”
* **前置系统状态**：无同款物品冲突。
* **预期流转路径**：`__start__` $\rightarrow$ `input_router` $\rightarrow$ `intent_classifier (add)` $\rightarrow$ `conflict_batch_resolver (pass)` $\rightarrow$ `mutation_executor` $\rightarrow$ `post_process` $\rightarrow$ `__end__`
* **期望的最终答复**：“登记成功！已帮您将 2.0 件 **草莓** 录入系统的冰箱冷藏层中。”
* **期望的底层状态变化**：`mutation_logs` 产生一条 `delta: +2` 的日志，Markdown 看板增量同步成功。

#### 测试用例 1.2：精准的指定消耗

* **用户操作人**：老婆 (`user_wife`)
* **输入话术**：“特仑苏纯牛奶被我喝了一盒。”
* **前置系统状态**：厨房二级柜登记有“特仑苏纯牛奶” 12 盒。
* **预期流转路径**：`__start__` $\rightarrow$ `input_router` $\rightarrow$ `intent_classifier (consume)` $\rightarrow$ `conflict_batch_resolver (精确匹配单个SKU)` $\rightarrow$ `mutation_executor` $\rightarrow$ `post_process` $\rightarrow$ `__end__`
* **期望的最终答复**：“好滴老婆，管家已帮您自动扣减了 **特仑苏纯牛奶 250ml** 1盒。目前二级柜还剩 11 盒哦。”

---

### 二、 核心 FIFO（先进先出）算法测试场景

#### 测试用例 2.1：模糊口语消耗，触发临期批次自动锁定

* **用户操作人**：老公 (`user_husband`)
* **输入话术**：“冰箱里的鲜奶我喝了一瓶。”
* **前置系统状态**：冰箱冷藏层里有两批同款鲜奶：
1. `Instance_A` (周一买的，剩 1 天过期，数量 1)
2. `Instance_B` (周二买的，剩 2 天过期，数量 1)


* **预期流转路径**：`__start__` $\rightarrow$ `input_router` $\rightarrow$ `intent_classifier (consume)` $\rightarrow$ `conflict_batch_resolver (运行FIFO，升序排列，锁定 Instance_A)` $\rightarrow$ `mutation_executor` $\rightarrow$ `post_process` $\rightarrow$ `__end__`
* **期望的最终答复**：“好滴老公，管家已帮您自动扣减了剩余保质期最短的那批 **山姆全脂鲜奶 2L**（周一买的那瓶）。冰箱里还有一瓶周二买的，可以优先考虑过两天喝掉哦。”
* **核心校验点**：物理数据库中被扣减数量的必须是 `Instance_A` 的 ID，且 `current_context_item` 自动锁死为该鲜奶。

---

### 三、 名称歧义与多候选消除场景（多轮对话）

#### 测试用例 3.1：第一轮 —— 名字多义性拦截，推送候选集

* **用户操作人**：老公 (`user_husband`)
* **输入话术**：“牛奶喝完了一盒。”
* **前置系统状态**：家里目前同时存有：`[1] 山姆全脂鲜奶 (冰箱)`、`[2] 特仑苏纯牛奶 (二级柜)`。
* **预期流转路径**：`__start__` $\rightarrow$ `input_router` $\rightarrow$ `intent_classifier (consume)` $\rightarrow$ `conflict_batch_resolver (发现 len(unique_skus) > 1，中断执行，改写 mode 为 pending_selection)` $\rightarrow$ `post_process` $\rightarrow$ `__end__`
* **期望的最终答复**：
  “咱们家目前有好几种‘牛奶’呢：
  [1] 山姆全脂鲜奶 2L (在厨房冰箱冷藏层)
  [2] 特仑苏纯牛奶 250ml (在厨房厨房二级柜)
  请问您喝的是哪一种？（请输入对应序号）”
* **核心校验点**：图结束时，全局状态的 `interaction_mode` 必须变为 `"pending_selection"`，`pending_item_selection` 存入这两个候选单品的数据，底层的物理写操作未发生。

#### 测试用例 3.2：第二轮 —— 用户输入序号，状态机自控接管执行

* **用户操作人**：老公 (`user_husband`)
* **输入话术**：“1”  *(或口语化的“第一个”、“山姆的那个”)*
* **前置系统状态**：`interaction_mode = "pending_selection"`，候选集存在。
* **预期流转路径**：`__start__` $\rightarrow$ `input_router (检测到 pending，强制合流)` $\rightarrow$ `Pending Confirmation Handler (解析序号 1，匹配 Instance_A)` $\rightarrow$ `mutation_executor` $\rightarrow$ `post_process` $\rightarrow$ `__end__`
* **期望的最终答复**：“收到！已经为您扣减了冰箱里的 **山姆全脂鲜奶 2L** 1盒。系统交互已恢复正常。”
* **核心校验点**：`interaction_mode` 自动洗回 `"normal"`，挂起数据全部清空。

---

### 四、 家庭成员并发协同与囤货拦截场景

#### 测试用例 4.1：老公重复买物资，系统触发“防败家”拦截

* **用户操作人**：老公 (`user_husband`)
* **输入话术**：“老婆，我刚在楼下又提了一箱山姆全脂鲜奶回来，入库一下。”
* **前置系统状态**：2小时前，老婆刚在手机端上传了网购同一款山姆鲜奶的订单小票并已成功入库。
* **预期流转路径**：`__start__` $\rightarrow$ `input_router` $\rightarrow$ `intent_classifier (add)` $\rightarrow$ `conflict_batch_resolver (触发近期同款购买审计，中断执行，锁定事务)` $\rightarrow$ `post_process` $\rightarrow$ `__end__`
* **期望的最终答复**：“先等一下哦老公！系统发现 **老婆** 在 120 分钟前刚刚通过【美团外卖截图】买了一箱‘山姆全脂鲜奶 2L’。您确定还要重复坚持入库吗？（您可以对我说‘确认入库’或‘算了’）”
* **核心校验点**：事务被挂起。如果没有这个拦截，家庭库存会无端翻倍，造成食物浪费。

---

### 五、 跨轮次时空感知与记忆继承（根治健忘症场景）

#### 测试用例 5.1：多轮上下文无主语延续（生成菜谱）

* **前置会话（第一轮）**：用户问哪些快过期，Agent 答复：“主厨房/厨房二级柜里的全麦面包还有2天过期。”（此时 `current_context_item` 锁定了全麦面包和二级柜位置）。
* **本轮输入话术**：“帮我生成菜单。” *(注意：句中没有任何主语和位置)*
* **预期流转路径**：`__start__` $\rightarrow$ `input_router` $\rightarrow$ `intent_classifier (recipe)` $\rightarrow$ `query_and_recipe_handler (检测到无主语，成功继承记忆锁，向 LLM 注入位置强约束)` $\rightarrow$ `post_process` $\rightarrow$ `__end__`
* **期望的最终答复**：“收到！针对**厨房二级柜**里这几片快过期的**全麦面包**，考虑到现在快到中午了，我为您设计了 2 种极速消耗方案：……”
* **核心校验点**：答复中**绝对不能**出现“发现您**冰箱**里有全麦面包吗”等瞎编的字眼，必须完美咬合“厨房二级柜”。

---

### 六、 强中断与状态逃逸场景（Escape Mechanism）

#### 测试用例 6.1：在引导多选一或确认拦截时，用户突然反悔

* **用户操作人**：老公 (`user_husband`)
* **输入话术**：“算了，不要了。” *(或“取消”、“退出”)*
* **前置系统状态**：当前系统正处于测试用例 3.1 或 4.1 留下的 `interaction_mode = "pending_selection"` 挂起锁定状态。
* **预期流转路径**：`__start__` $\rightarrow$ `input_router (在入口 Node 命中 Escape 词网，直接洗白状态，提前强行路由出图)` $\rightarrow$ `post_process` $\rightarrow$ `__end__`
* **期望的最终答复**：“好滴老公，已经帮您取消了刚才的操作。咱们重新开始，您想处理点什么物资？”
* **核心校验点**：整个过程不经过 `Intent Classifier` 大模型和业务决策节点，用最低的延迟和确定性的逻辑打破状态死锁，防止用户被卡死。

---

### 七、 纯只读空间/时效查询场景

#### 测试用例 7.1：资产空间溯源查询

* **用户操作人**：老婆 (`user_wife`)
* **输入话术**：“老公，你买的那包全麦面包被你塞到哪里去了？”
* **前置系统状态**：全麦面包存放在“主厨房/厨房二级柜”。
* **预期流转路径**：`__start__` $\rightarrow$ `input_router` $\rightarrow$ `intent_classifier (location_query)` $\rightarrow$ `query_and_recipe_handler` $\rightarrow$ `post_process` $\rightarrow$ `__end__`
* **期望的最终答复**：“查了一下系统的空间拓扑树，老公买的那包 **全麦面包** 目前就放在【主厨房/厨房二级柜】哦，需要我现在帮您清点一下剩余数量吗？”

#### 测试用例 7.2：全合拢后处理审计回溯（家庭关心话术）

* **用户操作人**：老婆 (`user_wife`)
* **输入话术**：“我冰箱里的那瓶山姆鲜奶怎么不见了？”
* **前置系统状态**：2小时前，老公通过口语消耗（用例2.1）触发 FIFO 把这瓶牛奶喝掉并清空了。
* **预期流转路径**：`__start__` $\rightarrow$ `input_router` $\rightarrow$ `intent_classifier (audit_query)` $\rightarrow$ `query_and_recipe_handler (调取 mutation_logs 历史)` $\rightarrow$ `post_process` $\rightarrow$ `__end__`
* **期望的最终答复**：“老婆先别着急，系统审计日志显示：**老公** 在今天下午 17:05 分的时候，刚刚把冰箱里那瓶临期的 **山姆全脂鲜奶 2L** 喝掉啦。目前家里没有鲜奶库存了，需要我帮您加入外卖购物清单吗？”