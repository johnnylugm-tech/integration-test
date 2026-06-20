# Claude Code Workflow Tool — Playbook

> 整合官方開發手冊 (https://code.claude.com/docs/en/workflows) 與
> integration-test 專案四輪迭代 (v1 → v4) 踩過的所有坑。
>
> **撰寫日期**: 2026-06-20 · **基於 Claude Code v2.1.183**
> **對象**: 開發者 (寫 workflow script) + 維運者 (監看 / 調試 workflow run)
> **專案上下文**: harness-methodology v2.12 Phase 1 Requirements workflow

---

## 1. 什麼是 Workflow(快速對齊)

| 物件 | 誰持有計畫 | 中間結果 | 中斷恢復 | 規模 |
|------|----------|---------|---------|------|
| **Subagent** | Claude 每輪決策 | 進入主對話 context | 整輪重來 | 每輪幾個 |
| **Skill** | Claude 依照指示 | 進入主對話 context | 重來 | 同 subagent |
| **Agent team** | Lead agent 監看 peer | 共享 task list | Peer 持續跑 | 一群長期 |
| **Workflow** | **Script 本身** | **Script 變數** | **同 session 內 resume** | **數十到數百個 agents** |

**Workflow = 把 plan 寫成 code**。Script 持有 loop、branching、中間結果;主對話 context 只看到最後答案。

**決策何時用 workflow**(滿足任一):
- 任務需要比單一對話能協調更多的 agents
- 想要 orchestration 寫成可讀、可重跑的 script
- 想套用可重複的 quality pattern(例: 對抗式 review、多角度草稿、獨立交叉查證)

**不要用 workflow**(滿足任一):
- 任務可在主對話 1-2 輪解決
- 結果只是探索性單一答案(不需要 adversarial review)
- 任務需要 mid-run 的人為決策 → 拆成多個小 workflow(因為 runtime 無 mid-run user input)

---

## 2. 檔案位置與啟動方式

### 存放位置(由近到遠)

| 路徑 | 範圍 | 適用 |
|------|------|------|
| `./<cwd>/.claude/workflows/<name>.js` | 該 package | 套件層級 workflow |
| `./<repo>/.claude/workflows/<name>.js` | 該 repo | 專案層級 (建議放這裡) |
| `~/.claude/workflows/<name>.js` | 全域個人 | 個人跨專案用 |

**Monorepo 行為** (v2.1.178+): 從 cwd 沿路往上找最近的 `.claude/workflows/`;若多個 `.claude/` 都定義同名 workflow,執行最近的那個。

**衝突規則**: Project workflow 優先於 Personal workflow(同名時)。

### 啟動方式

```bash
# 1. Slash command (最常用)
> /my-workflow-name arg1 arg2

# 2. /workflows view → 按 Enter → 選 saved workflow
> /workflows

# 3. 透過 ultracode 自動觸發
> ultracode: audit every API endpoint under src/routes/ for missing auth checks
> /effort ultracode    # 全 session 自動用 workflow

# 4. Programmatic(Agent 內)
Workflow({ script: "..." })              # inline script
Workflow({ scriptPath: "/abs/path.js" }) # 絕對路徑 (推薦)
Workflow({ name: "phase1-requirements" })# 用 name (有 cache 風險,見 §6.5)
Workflow({ scriptPath, resumeFromRunId: "wf_xxx" })  # resume
```

---

## 3. Script 結構 — meta 物件

### 必要欄位

```javascript
export const meta = {
  name: 'phase1-requirements',              // 必填,識別用
  description: 'Phase 1 Requirements ...',  // 必填,出現在 /workflows list
  whenToUse: 'optional; 顯示在 workflow list', // optional
  phases: [                                 // optional,顯示在 progress view
    { title: 'Preflight' },
    { title: 'Sub-Task 1/4 — SRS.md' },
    ...
  ],
}
```

### meta 規則(Validator hard errors)

| 規則 | 違規 → 結果 |
|------|-----------|
| 必須 FIRST statement | `ERROR: export const meta must be the FIRST statement` |
| 必須是純 literal | `ERROR: meta contains a spread`, `ERROR: meta contains a template literal`, `ERROR: meta appears to contain a function call` |
| 不能用 `__proto__` / `constructor` / `prototype` 當 key | `ERROR: meta uses reserved key` |
| 必須含 `name` 欄位 | `ERROR: meta is missing a name field` |
| 必須含 `description` 欄位 | `ERROR: meta is missing a description field` |

**正確範例**:
```javascript
export const meta = {
  name: 'my-workflow',
  description: 'Does X then Y',
  phases: [{ title: 'Phase 1' }, { title: 'Phase 2' }],
}
```

**錯誤範例**(會被 validator 擋):
```javascript
const prefix = 'my-'
export const meta = { name: prefix + 'workflow', ... }  // ❌ 函式呼叫
export const meta = { name: 'my-workflow', desc: `template` } // ❌ template literal
export const meta = { name: 'my-workflow', __proto__: {} }   // ❌ reserved key
```

---

## 4. Script 語法限制 — 什麼不能用

### Hard errors (validator + runtime 都會擋)

| 違規 | 原因 | 解法 |
|------|------|------|
| `Date.now()` | 破壞 resume(時間漂移) | 由 args 傳入 timestamp,或 workflow 回傳後再 stamp |
| `Math.random()` | 破壞 resume | 由 args 傳入 seed,或用 prompt 加 index 區分 |
| `new Date()` 無參數 | 同上 | 同上 |
| 檔案大小 > 524288 bytes (512 KB) | runtime 拒絕解析 | 拆 workflow 或縮減 prompt |

### Warnings (validator 警告 + runtime 直接 throw)

| 違規 | Runtime 行為 | 解法 |
|------|-------------|------|
| `import('node:fs')` / `await import()` | **runtime 直接 throw** | 用 `agent()` 委派檔案 I/O |
| `fs.*` / `path.*` / `process.*` / `require()` | runtime 直接 throw | 同上 |
| `import ... from ...` (靜態) | runtime 直接 throw | 同上 |

> **v1 踩坑**: shipped workflow 用了 `const fs = await import('node:fs')`。
> Validator 只 warn,runtime 直接 throw — 因為 script 沒有 Node API 存取權。
> **正確解法**: 從 script 移除所有 host API;檔案讀寫交給 agent()。

### 語言限制

- ✅ **純 JavaScript** (不用 TypeScript,type annotation 會 parse error)
- ✅ 無 `import()` / `require()`
- ❌ TypeScript 型別註記(會被 parser 拒絕)
- ❌ `node:fs` / `node:path` 等 Node 模組

### Runtime 限制 (runtime 的額外約束,validator 抓不到)

| 約束 | 影響 |
|------|------|
| 無 mid-run user input | 唯一能 pause 的是 agent permission prompt;要在 stage 之間人工 sign-off → 拆成多個 workflow |
| 無 fs / shell access from script | 所有 I/O 透過 agent() |
| ≤ 16 concurrent agents (CPU cores - 2 取小) | 超過會 queue |
| ≤ 1000 agents total per run | runaway backstop |
| ≤ 4096 items per parallel/pipeline 呼叫 | 超過是顯式 error |

---

## 5. Script API — agent / parallel / pipeline / phase / log

### 5.1 `agent(prompt, opts)`

```javascript
const result = await agent(prompt, {
  label: 'a1-srs-r1',           // 顯示在 progress view
  phase: 'Sub-Task 1/4',        // 分組到 phase box
  agentType: 'general-purpose', // 'general-purpose' | 'Explore' | 'Plan' | 自訂
  model: 'haiku',               // 覆寫 session model (cheaper reviewers 用 haiku)
  effort: 'medium',             // 'low' | 'medium' | 'high' | 'xhigh' | 'max'
  schema: SCHEMA,               // JSON Schema → 強制 agent 呼叫 StructuredOutput tool
  isolation: 'worktree',        // 給 agent 獨立 git worktree (expensive!)
})
```

**回傳值**:
- 沒 `schema:` → 字串 (agent 最終訊息)
- 有 `schema:` → 已驗證的 object (runtime 幫你 JSON.parse + AJV validate)

### 5.2 `schema:` 行為 — **踩坑重點**

- `schema:` 強制 subagent 呼叫 `StructuredOutput` tool
- Agent 必須以 tool call 形式回 JSON,**不能用 plain text**
- 若 agent 回 text, runtime 會 retry 2 次 → 仍失敗 → **整個 workflow fail**

> **v2 踩坑**: workflow 用 `schema: B_SCHEMA` 給 B-review agent。
> 一個 B-review agent 多次返回 JSON-as-text,runtime throw:
> `agent({schema}): subagent completed without calling StructuredOutput (after 2 in-conversation nudges)`
> 整個 workflow 直接 fail。

> **v3 正確解法**: 移除 `schema:`,改用 balanced-brace JSON parser 自己解析 agent 回的 plain text:

```javascript
function balancedJsonAt(text, start) {
  if (text[start] !== '{' && text[start] !== '[') return null
  let depth = 0, inStr = false, esc = false
  for (let i = start; i < text.length; i++) {
    const c = text[i]
    if (esc) { esc = false; continue }
    if (c === '\\') { esc = true; continue }
    if (c === '"') { inStr = !inStr; continue }
    if (inStr) continue
    if (c === '{' || c === '[') depth++
    else if (c === '}' || c === ']') {
      depth--; if (depth === 0) return text.slice(start, i + 1)
    }
  }
  return null
}

function extractLastJson(text) {
  let last = null
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '{' || text[i] === '[') {
      const block = balancedJsonAt(text, i)
      if (block) {
        try { last = JSON.parse(block); i += block.length - 1 } catch {}
      }
    }
  }
  return last
}
```

### 5.3 Schema 必須是 top-level const(踩坑)

> **v2 踩坑**: 在 `agent(prompt, { schema: { type:'object', properties:{...} } })` 裡
> 直接放複雜 inline schema 物件 → runtime parse error: `Unexpected token (330:62)`。

> **正確**: schema 必須是 top-level const:

```javascript
const B_SCHEMA = {
  type: 'object',
  properties: {
    review_status: { type: 'string', enum: ['APPROVE', 'REJECT'] },
    reason: { type: 'string' },
    citations: { type: 'array', items: { type: 'string' } },
    gaps: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { type: 'string', enum: ['low', 'medium', 'high'] },
          message: { type: 'string' },
          fr_id: { type: ['string', 'null'] },
        },
        required: ['severity', 'message', 'fr_id'],
        additionalProperties: false,
      },
    },
  },
  required: ['review_status', 'reason', 'citations', 'gaps'],
  additionalProperties: false,
}
```

### 5.4 `parallel(thunks)` vs `pipeline(items, ...stages)`

| 函式 | 語義 | 用法 |
|------|------|------|
| `parallel([t1, t2, ...])` | 所有 thunks 並行,**barrier**:全部完成才回 | 需要 dedup 全部結果、early-exit |
| `pipeline(items, stage1, stage2, ...)` | 每個 item 跑完所有 stages,**stage 間不 barrier** | item 獨立任務串接 |

> **Pipeline by default** — Workflow tool 文件原文:
> "Only reach for a barrier (parallel between stages) when you genuinely need ALL prior-stage results together."

```javascript
// ✅ Pipeline(預設): 3 個 FR 各自 A→B→C,不互相等待
const results = await pipeline(
  frIds,
  fr => agent(`Author ${fr}`, { label: `a-${fr}`, phase: 'Author' }),
  rev => agent(`Review`, { label: `b-${rev.frId}`, phase: 'Review' }),
  fix => agent(`Fix`, { label: `c-${fix.frId}`, phase: 'Fix' }),
)

// ❌ Barrier (不必要): 全部 A 完才跑任何 B
const aResults = await parallel(frIds.map(fr => () => agent(`Author ${fr}`)))
const bResults = await parallel(aResults.map(a => () => agent(`Review ${a.frId}`)))
```

### 5.5 `phase(title)` 與 `log(message)`

```javascript
phase('Sub-Task 1/4 — SRS.md')   // 開始一個 phase box,後續 agent() 歸到這 box
log('SRS.md: Agent A + Agent B') // 顯示一行 narrator 訊息
```

### 5.6 `workflow(nameOrRef, args)` — 巢狀 workflow(只能一層)

```javascript
const result = await workflow('sub-helper', { some: 'input' })
```

- Nesting depth 限制 1 (workflow() 內不能再 workflow())
- 與 parent 共享 concurrency cap + agent counter + token budget

### 5.7 `args` 全域變數

- 由 `Workflow({ args: ... })` 傳入
- 可能是 string (JSON-encoded) 或 object (structured)
- **Workflow tool 文件說**: "Claude passes the list as structured data, so the script can call array and object methods on `args` directly without parsing it first"

> **踩坑**: 透過某些 Agent tool format 呼叫 `Workflow({ scriptPath: ... })` 時,**args 完全沒傳過去**
> (silently undefined)。解法:在 script 內設 default fallback:

```javascript
const DEFAULT_REPO = '/Users/johnny/projects/integration-test'
let REPO = DEFAULT_REPO
if (args && typeof args === 'object' && typeof args.repo === 'string') {
  REPO = args.repo
}
```

### 5.8 `budget` 物件(token budget tracking)

```javascript
while (budget.total && budget.remaining() > 50_000) {
  const result = await agent("Find bugs", { schema: BUG_SCHEMA })
  bugs.push(...result.bugs)
}
log(`${bugs.length} found, ${Math.round(budget.remaining()/1000)}k remaining`)
```

- `budget.total` = `null` 表示沒設 target
- `budget.spent()` = 整個 turn 主 loop + 所有 workflows 累計
- `budget.remaining()` = `Math.max(0, total - spent())` 或 `Infinity`(沒 target)

---

## 6. 啟動與管理 Workflow

### 6.1 三種 launch 方式

```javascript
Workflow({ script: "..." })                    // inline,debugging
Workflow({ scriptPath: "/abs/path.js" })      // 絕對路徑(推薦)
Workflow({ name: "phase1-requirements" })     // 用 name,從 .claude/workflows/ 找
```

### 6.2 /workflows view 控制

| Key | 動作 |
|-----|------|
| `↑` / `↓` | 選 phase 或 agent |
| `Enter` / `→` | 鑽進去看 prompt + tool calls + result |
| `Esc` | 退出 |
| `j` / `k` | 細節 overflow 時捲動 |
| `p` | pause / resume |
| `x` | 停選定 agent;若焦點在 run 則停整個 workflow |
| `r` | 重啟選定 agent |
| `s` | 存成可重用的 command |

### 6.3 Resume

```javascript
// Pause 後,workflow 內已完成 agent() 回傳 cached result;未跑的才 live 重跑
Workflow({ scriptPath, resumeFromRunId: "wf_xxx" })
```

- **限制**: 必須同 session;離開 Claude Code → 下個 session 從頭跑
- 為了 cache 命中,**script 不能改**;改了只 cache 到第一個改動的 agent() call

### 6.4 Permission prompt

| Permission mode | 啟動時是否問 |
|-----------------|-------------|
| Default / accept edits | 每次都問 (除非已 "don't ask again") |
| Auto | 第一次問,Yes 後記住;ultracode on 時跳過 |
| Bypass permissions / `claude -p` / Agent SDK | 從不問,直接跑 |

Subagent 永遠跑在 `acceptEdits` 模式,繼承你的 tool allowlist;檔案 edit 自動批准。

### 6.5 Name resolver cache bug(踩坑)

> **v2 踩坑**: shipped workflow 檔案已修改(27,123 bytes 新版),
> 但 runtime persisted 還是舊版(19,085 bytes 預先 snapshot)。
> 用 `Workflow({ name: 'phase1-requirements' })` 啟動 → 跑的還是舊版。

> **正確解法**: 用絕對路徑 `scriptPath:` 跳過 name resolver cache。

### 6.6 停不掉舊 run(踩坑)

Agent 工具**無法**直接停 workflow run。只能:
1. 請 user 在 `/workflows` view 按 `x`
2. 或讓 workflow 自己跑到出錯/完成

---

## 7. 子 Agent 與 Tool 行為

### 7.1 Agent 怎麼選 tool

`agentType` 影響可用 tool:
- `general-purpose` — 預設,全部工具
- `Explore` — read-only 搜尋(不可寫)
- `Plan` — read-only 設計規劃

**自訂 agent type** 透過 `subagent_type` (e.g. `Explore`, `code-reviewer`)。

### 7.2 Stateless agent sandbox(踩坑)

B-review agent **無 file access**。`Read` tool 也可能 hallucinate(見 §8.2)。

> **正確解法**: 將需要 review 的完整內容 **embed 在 prompt 內**,絕對不要只給路徑:

```javascript
function buildBPrompt(role, docs, checklist) {
  let p = 'You are ' + role + '.\n'
  p += 'You have NO access to any files — all context is provided below.\n\n'
  for (const [label, content] of docs) {
    p += '=== [' + label + '] ===\n' + content + '\n\n'
  }
  p += 'Review checklist:\n' + checklist + '\n\n'
  p += 'Return JSON only.'
  return p
}
```

### 7.3 Do-not 列表 — 防止 agent over-reach(踩坑)

> **v2 踩坑**: 一個 preflight agent 拿到含完整 P1 plan 的 prompt,
> general-purpose agent 判定「我可以全部做完」,3 分鐘做完整個 P1。

> **正確解法**: 每個 agent prompt 加明確的 **SCOPE RULES (DO NOT)**:

```javascript
const A_SCOPE_RULES = '\n\nSCOPE RULES (you MUST obey):\n'
  + '- DO NOT write any deliverable OTHER than the one specified in step 2.\n'
  + '- DO NOT run git commit, git push, advance-phase, push-checkpoint, or any phase-transition command.\n'
  + '- DO NOT run constitution-check, peer-review, or any quality-gate command.\n'
  + '- DO NOT spawn other agents or do the work of downstream sub-tasks.\n'
  + '- ONLY do steps 1-4 above. Return the JSON when done.\n'
```

---

## 8. 反覆踩過的真實坑(必讀)

### 8.1 P1 ❌ `import('node:fs')` 讓 shipped workflow 起不來

**症狀**: `import() is not available in workflow scripts`

**根因**: Script 想讀檔,寫了 `const fs = await import('node:fs')`。Validator 只 warn,runtime 直接 throw。

**正確解法**: Script 不做 I/O,改叫 `agent()` 帶 Bash tool:

```javascript
const fileContent = await agent(
  'Use Bash to run: cat /abs/path/file.md\n'
  + 'Return the EXACT stdout as your final message. No commentary.',
  { label: 'load-file', agentType: 'general-purpose' }
)
```

### 8.2 P2 ❌ Read tool 會 hallucinate 檔案內容

**症狀**: Brief loader agent 用 Read tool 讀 `PROJECT_BRIEF.md`,
回傳內容卻是 CLAUDE.md / memory 裡的描述(完全不同檔)。

**根因**: LLM agent 的 Read tool 拿到路徑後會用訓練資料「猜」內容;若同目錄有其他檔案,可能混淆。

**正確解法**: 用 Bash `cat` 取絕對位元組 — stdout 唯一通道就是檔案內容,LLM 無法替換:

```javascript
const brief = await agent(
  'Use ONLY the Bash tool. Run EXACTLY: cat ' + REPO + '/PROJECT_BRIEF.md\n'
  + 'Do NOT use Read tool. Return EXACT stdout.',
  { label: 'load-brief', agentType: 'general-purpose' }
)
// + defensive validation: 必須以 "# Project Brief" 開頭 + 長度 >=50
```

### 8.3 P3 ❌ B-review reject loop 沒 revise step → 無限循環

**症狀**: B-agent 一直 REJECT SRS,理由幾乎相同 (placeholder、NFR count)。
A 已經從 on-disk 讀檔返回正確內容,B 的高 severity gaps 是 reviewer 對「完整性」的過度解讀。Loop 跑滿 5 輪還沒收斂。

**正確解法**:
1. Loop 滿 `MAX_B_ROUNDS` 時 **ESCALATE**(return error),不要再 continue
2. A agent 在 round > 1 必須 review previous B-2 review JSON 並**套用 HIGH severity 修正**(surgical Edit,不是 rewrite)

### 8.4 P4 ❌ `schema:` 讓 B-review agent fail

**症狀**: `agent({schema}): subagent completed without calling StructuredOutput (after 2 in-conversation nudges)`
整個 workflow 直接 fail。

**根因**: `schema:` 強制 subagent 呼叫 StructuredOutput tool,不能用 plain text。
某些 B-review agent 偏偏就回 plain-text JSON。

**正確解法**: 移除 `schema:`,用 §5.2 的 balanced-brace parser 自己 parse。

### 8.5 P5 ❌ Schema 必須 top-level const

**症狀**: `Script parse error: Unexpected token (330:62)`

**根因**: Inline 複雜 schema 物件 → runtime parser 拒絕。

**正確解法**: 把所有 schema 提到 top-level `const`,如 §5.3 範例。

### 8.6 P6 ❌ Name resolver 給 stale cache

**症狀**: 改完 workflow 檔,launch 卻跑舊版。

**正確解法**: 用 `scriptPath: '/abs/path.js'` 而非 `name: 'xxx'`。

### 8.7 P7 ❌ Inline schema 改物件後忘了改 schema 物件定義

**症狀**: 改 `schema:` 物件失敗,runtime 報 unexpected token 但 line number 指錯位置。

**正確解法**: §5.3 — top-level const。

### 8.8 P8 ❌ args 不會自動 fallback,workflow 立即 fail

**症狀**: 透過 Agent 工具呼叫 `Workflow({ scriptPath: ... })` 完全沒帶 args → script 內 `args === undefined` → 立即 return error。

**正確解法**: §5.7 — script 內設 `DEFAULT_XXX` fallback。

### 8.9 P9 ❌ Agent 回「BAD JSON shape」繼續 retry 浪費 token

**症狀**: Round 1 agent 返回 invalid JSON (沒 `files[0].content`),script 只 log + continue,跑完整輪才 escalate。

**正確解法**: Parse failure 立即 hard error return,不要 retry(重試不會自己修好):

```javascript
try {
  a = parseAgentJson(aResult, 'A-r' + round)
} catch (e) {
  return { error: 'A parse failed (round ' + round + ')', detail: e.message }
}
```

### 8.10 P10 ❌ 兩個 workflow run 競爭同一組 deliverables

**症狀**: 舊 v2 run 還在跑、新的 v3 又 launch → 兩 run 互相覆寫同一個 SRS.md,內容不一致。

**正確解法**: User 必須手動 `/workflows` view 按 `x` 停舊 run。Agent 工具沒 API 可停 workflow。

---

## 9. 設計模式 — 從四輪迭代萃取

### 9.1 HybridWorkflow(HR-04)

- Agent A 負責 author(寫 deliverable)
- Agent B 負責 review(評 A 的產出)
- **絕不自己 role-play A 或 B**(orchestrator 只看 result)

### 9.2 STATELESS B-review sandbox

- B 無 file access → 必須 embed 完整 doc 內容在 prompt
- 這是「force function」:迫使 B 不依賴外部狀態,review 可重現

### 9.3 A self-check pattern

- Round 1: A 先 `test -f <deliverable>`,如果存在就 Read + return JSON(快速通過)
- Round > 1: A 先 review previous B-2 review JSON,套用 HIGH severity 修正,surgical Edit
- 避免 A 每次都 overwrite 整個檔案(surgical 才不會破壞既有合約)

### 9.4 B-2 loop logic(HR-12 + phase1_plan.md B-2)

```
APPROVE + all gaps low          → break (continue to next sub-task)
APPROVE + any med/high gap      → A fixes → re-dispatch B (round 2)
REJECT                           → A fixes → re-dispatch B
MAX_B_ROUNDS (5) without resolve → ESCALATE (hard return error, not silent break)
```

### 9.5 Bash cat > Read tool for content loading

```javascript
// ✅ Reliable: bash cat (stdout = exact bytes)
const content = await agent(`Use ONLY Bash. Run: cat ${PATH}. Return stdout verbatim.`, opts)

// ❌ Unreliable: Read tool (LLM may hallucinate)
const content = await agent(`Use Read tool on ${PATH}. Return content.`, opts)
```

### 9.6 模型選擇(cost optimization)

```javascript
{ agentType: 'general-purpose' }              // 預設,用 session model
{ model: 'haiku' }                            // 6x 便宜,給 B-review 用
{ model: 'haiku', effort: 'low' }             // 更省
```

### 9.7 Preflight agent 要 super narrow

> 不給 preflight agent 看完整 P1 plan;只給「跑 3 個 bash 命令並回報」。
> 這樣它不會自行決定「既然能跑完,就全做完吧」。

### 9.8 Push + Advance 拆兩階段(per phase1_plan.md)

```javascript
phase('Push');     // push-checkpoint --phase 1 (retry until success, no --no-verify)
phase('Advance');  // advance-phase --completed 1 + verify HANDOVER.md
```

Push 沒成功就不 advance;Advance 失敗就保留 P1 狀態由人工介入。

### 9.9 Subagent prompt 結構樣板

```
You are <ROLE>. Your task: <ONE-LINE TASK>.
You have NO access to any files — all context is provided below.

=== [DOC 1: <LABEL>] ===
<content>

=== [DOC 2: <LABEL>] ===
<content>

<CHECKLIST_OR_INSTRUCTIONS>

SCOPE RULES (you MUST obey):
- DO NOT <bad action 1>
- DO NOT <bad action 2>
- ONLY do <good action 1> through <good action N>.

Return JSON only:
{...schema...}
```

---

## 10. 監看與調試

### 10.1 找到 run 狀態

```
/workflows    # 列出所有 run,選一個鑽進去看
```

每個 run:
- Phase box(顯示 agent count + token total + elapsed time)
- Agent detail: prompt、recent tool calls、result

### 10.2 Transcript 路徑

每個 run 的 script + 每個 agent 的逐字 transcript 寫到:

```
~/.claude/projects/<session-hash>/subagents/workflows/<run-id>/
  journal.jsonl                           # script 的 started/result 事件
  agent-<uuid>.jsonl                      # 該 agent 的完整 message log
  agent-<uuid>.meta.json                  # {agentType: 'general-purpose'}
```

讀 journal 找失敗根因:

```bash
JOURNAL=~/.claude/projects/<session>/subagents/workflows/wf_xxx/journal.jsonl
grep '"type":"result"' $JOURNAL | python3 -c "
import json, sys
for line in sys.stdin:
    d = json.loads(line)
    r = d.get('result', {})
    print(f\"{d['agentId'][:12]}: status={r.get('review_status') or r.get('status')} gaps={len(r.get('gaps') or [])}\")
"
```

### 10.3 用 validator 預檢 script

```bash
# /tmp/validate-workflow.mjs 是 ray-amjad/claude-code-workflow-creator 官方 validator 副本
node /tmp/validate-workflow.mjs /abs/path/workflow.js

# 輸出:
# ok — phase1-requirements.js passes (36539 bytes)
# 3 error(s) in xxx.js — fix before running.
```

### 10.4 Token 估算(節錄自 v4 經驗)

| Phase | Agents | Tokens |
|-------|--------|--------|
| Preflight | 1 | 15-25k |
| Brief loader | 1 | 5k |
| 4 × (A-read + B-review) | 8 | 40k |
| Constitution check | 1 | 5-10k |
| Peer review | 1 | 8-12k |
| Push + Advance | 2 | 30-50k |
| **小計(順利 1 輪)** | **14** | **~100-150k** |

若 B 反覆 REJECT,每多一輪 +30k。設 budget cap 避免失控。

---

## 11. Turn off / Disable

若不想用 workflow:

| 方式 | 範圍 | 持續 |
|------|------|------|
| `/config` → 關閉 "Dynamic workflows" | 個人 | 永久 |
| `~/.claude/settings.json` 加 `"disableWorkflows": true` | 個人 | 永久 |
| 環境變數 `CLAUDE_CODE_DISABLE_WORKFLOWS=1` | 該啟動 | session |

關閉後 `/deep-research` 不可用、`ultracode` 關鍵字無效。

---

## 12. 速查表

| 我想做... | 做法 |
|----------|------|
| 寫新 workflow | 1. 寫 `.claude/workflows/<name>.js` (export const meta 第一行)<br>2. `node /tmp/validate-workflow.mjs <path>`<br>3. `Workflow({ scriptPath: '/abs/path' })` |
| 改 workflow | `Workflow({ scriptPath, resumeFromRunId: 'wf_old' })` cache 命中已完成部分 |
| 停 workflow | 請 user 在 `/workflows` view 按 `x` |
| 監看 | `/workflows` |
| B-review | stateless prompt,完整 embed 文件 |
| 讀檔 | Bash cat (不用 Read tool) |
| 解析 agent JSON | balanced-brace parser(若用 schema: 風險見 §5.2/§8.4) |
| 省 token | B-review 用 `model: 'haiku'` |
| 防 over-reach | 加 SCOPE RULES (DO NOT) |
| Parse failure | 立即 hard error,不要 retry |

---

## 附錄 A: integration-test 真實案例時序

| 版本 | 症狀 | 根因 | 修法 |
|------|------|------|------|
| **v1** shipped | `import() is not available in workflow scripts` | `const fs = await import('node:fs')` 想要 fs I/O | 全移除,改叫 agent() |
| **v1** shipped | `Script parse error: Unexpected token (330:62)` | inline schema 太複雜 | schema 提到 top-level const |
| **v2** | general-purpose preflight agent 3 分鐘做完 P1 | prompt 包含完整 P1 plan | 加 SCOPE RULES DO-NOT |
| **v2** run | name resolver cache 給舊版 | shipped file 已 cp 但 runtime persisted 預先 snapshot | `Workflow({ scriptPath })` 取代 `name` |
| **v2** run | `subagent completed without calling StructuredOutput` | `schema:` 強制 tool call,某 agent 回 text | 移除 `schema:`,改 balanced-brace parser |
| **v3** run | B-review 無限 REJECT(>3 輪) | Brief loader agent 用 Read tool 讀 PROJECT_BRIEF.md,回傳 hallucinated 內容(來自 CLAUDE.md / memory) | 改 Bash `cat` + 加 defensive validation |
| **v4** run | (進行中) | — | — |

## 附錄 B: 官方/社群資源

- 官方手冊: https://code.claude.com/docs/en/workflows
- 文件索引: https://code.claude.com/docs/llms.txt
- Validator 來源: https://github.com/ray-amjad/claude-code-workflow-creator (main/scripts/validate-workflow.mjs)
- Subagent 文件: https://code.claude.com/docs/en/sub-agents
- 設定文件: https://code.claude.com/docs/en/settings
- 權限模式: https://code.claude.com/docs/en/permission-modes
