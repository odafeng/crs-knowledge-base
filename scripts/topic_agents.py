"""Topic-specific sub-agent prompts for classifying and contextualizing new papers.

Each topic agent has deep domain knowledge (existing papers, trial evolution,
treatment landscape) so it can explain WHY a new finding matters in context.
"""

import json
import os

from config import CONTENT_DATABASE_ENV, load_kb_data

# ---------------------------------------------------------------------------
# Load existing papers from PostgreSQL (when configured) or local data/papers.json
# ---------------------------------------------------------------------------


def _format_kb_context(data: dict) -> tuple[dict[str, str], dict[str, str]]:
    """Format topic papers and metrics as JSON strings for system prompt injection."""
    papers_by_topic: dict[str, str] = {}
    metrics_by_topic: dict[str, str] = {}
    for topic, topic_data in data.items():
        papers = topic_data.get("papers", [])
        if papers:
            papers_by_topic[topic] = json.dumps(papers, indent=2, ensure_ascii=False)
        metrics = topic_data.get("metrics")
        if metrics:
            metrics_by_topic[topic] = json.dumps(metrics, indent=2, ensure_ascii=False)
    return papers_by_topic, metrics_by_topic


def _load_papers_json() -> tuple[dict[str, str], dict[str, str]]:
    """Load papers context from PostgreSQL (if configured) or local data/papers.json."""
    return _format_kb_context(load_kb_data())


_PAPERS_JS, _METRICS_JS = _load_papers_json()
_LOADED_DB_URL: str | None = os.environ.get(CONTENT_DATABASE_ENV)


def _current_kb_context() -> tuple[dict[str, str], dict[str, str]]:
    """Reload KB context if GUTHUB_CONTENT_DATABASE_URL changed after module import."""
    global _PAPERS_JS, _METRICS_JS, _LOADED_DB_URL
    current_url = os.environ.get(CONTENT_DATABASE_ENV)
    if current_url != _LOADED_DB_URL:
        _PAPERS_JS, _METRICS_JS = _load_papers_json()
        _LOADED_DB_URL = current_url
    return _PAPERS_JS, _METRICS_JS


# ---------------------------------------------------------------------------
# Topic-specific system prompts
# ---------------------------------------------------------------------------

_TOPIC_CONTEXTS = {
    "mCRC-BRAF-V600E": """## BRAF V600E mCRC 治療演進
- BEACON (2019–2021): 確立二線 encorafenib+cetuximab (EC) doublet 為標準
- BREAKWATER (NEJM/Nat Med 2025): 一線 EC+mFOLFOX6，mOS 30.3 vs 15.1 mo（HR 0.49），已成一線標準；另已收錄 ctDNA dynamics、subsequent therapy 及 Cohort 3 EC+FOLFIRI（ASCO GI 2026）
- NCCN Colon Cancer v3.2026 已納入最新一線與後線建議
- 關鍵問題：最佳化療骨幹選擇（FOLFOX vs FOLFIRI）、biomarker-driven sequencing、抗藥機制、術前／輔助期角色

值得注意的里程碑類型：
- BREAKWATER Cohort 3 或更長期存活／生物標記追蹤
- 非 EC 的新世代 BRAF 抑制劑或合併方案（如 paradox breaker、MEK/ERK 組合）
- BRAF V600E 在 neoadjuvant 或 perioperative 場景的前瞻性數據
- ctDNA-guided 治療決策與抗藥後接續治療""",
    "mCRC-KRAS-G12C": """## KRAS G12C mCRC 治療演進
- CodeBreaK 101/300 (NEJM 2023; 最終 OS 分析 JCO 2025): sotorasib+panitumumab 確認 Phase 3 PFS 獲益（HR 0.49）
- KRYSTAL-1 (NEJM 2022; 擴大世代 Cancer Discov 2024): adagrasib+cetuximab ORR 46%，獲 FDA 加速核准
- Divarasib+cetuximab (Nat Med 2023): 早期數據 ORR 62.5%，待 Phase 3 確認
- Ifebemtinib (FAK 抑制劑) + garsorasib (Lancet Oncol 2026): 探索抗藥克服與合併策略
- 關鍵問題：OS 獲益確認、一線與化療合併（如 CodeBreaK 301 / KRYSTAL-10）、抗藥機制與新一代抑制劑

值得注意的里程碑類型：
- KRYSTAL-10 或一線 KRAS G12C + anti-EGFR + 化療 Phase 3 RCT
- Divarasib / garsorasib / 新一代共價或非共價（ON-state / pan-KRAS）抑制劑 Phase 2/3
- 克服抗藥的合併療法（FAK、SHP2、SOS1 抑制劑）
- 跨突變 pan-KRAS / KRAS G12D 臨床突破""",
    "mCRC-MSI-H": """## MSI-H/dMMR CRC 治療演進
- KEYNOTE-177 (NEJM 2020; OS Lancet Oncol 2022): pembrolizumab 確立一線標準（PFS HR 0.60）
- CheckMate 142 & 8HW: nivolumab+ipilimumab 雙免疫在一線與後線展現優異 PFS 與持久反應
- NICHE / NICHE-2 (NEJM 2024; 5 年追蹤 Lancet 2026): dMMR 結腸癌術前雙免疫，111 例中位追蹤 58.7 個月 3 年 DFS 與 5 年 OS 皆為 100%
- Dostarlimab pilot (NEJM 2022) → AZUR-1 (Ann Oncol 2026): 全球 Phase 2（154 例 dMMR 直腸癌）76% 達 cCR12/pCR，2026-10 獲 FDA 加速核准
- UNICORN (Nat Med 2026): 術前 botensilimab ± balstilimab 探索可切除 pMMR 結腸癌免疫反應
- 關鍵問題：免手術（watch-and-wait）長期安全性、雙免疫 vs 單免疫 OS 比較、pMMR 免疫治療突破與輔助免疫角色

值得注意的里程碑類型：
- CheckMate 8HW 長期 OS 與各線別雙免疫 vs 單免疫頭對頭數據
- AZUR-1 / dostarlimab 與其他 dMMR 直腸癌免手術策略的長期追蹤與擴展族群
- 輔助免疫治療（如 ATOMIC）或可切除期 dMMR 結腸癌隨機試驗
- pMMR/MSS 結直腸癌具臨床意義的免疫治療突破（如 botensilimab/balstilimab、雙抗、細胞治療）""",
    "mCRC-HER2": """## HER2+ mCRC 治療演進
- MyPathway (2019) / TRIUMPH (2021): pertuzumab+trastuzumab 奠定標靶與 ctDNA 篩選概念
- DESTINY-CRC01/02 (Lancet Oncol 2021/2024): T-DXd 確認 5.4 mg/kg 為最佳劑量（ORR 45%），且對 RAS mutant + HER2+ 仍有效
- MOUNTAINEER (Lancet Oncol 2023): tucatinib+trastuzumab 獲首個 FDA 核准（RAS wt）
- 關鍵問題：一線推進（MOUNTAINEER-03）、最佳檢測標準（IHC vs ctDNA）、HER2-low 療效、ADC 抗藥與肺毒性管理

值得注意的里程碑類型：
- MOUNTAINEER-03 或其他 HER2 標靶一線 Phase 3 RCT
- T-DXd Phase 3 確認性試驗或合併方案
- 新型 HER2 ADC、bispecific（如 zanidatamab）或 TKI 臨床數據
- HER2-low 或抗藥後接續 HER2 治療的前瞻性證據""",
    "generic-CRS": """## 大腸直腸外科通用主題（不屬於特定 biomarker 或機器人手術的文獻歸類於此）

### Biomarker-Agnostic 後線治療
- Regorafenib (CORRECT 2013, CONCUR 2015, ReDOS 2019): 確立 3L+ 標靶與低劑量遞增策略
- TAS-102/Lonsurf (RECOURSE 2015, TERRA 2018) → SUNLIGHT (NEJM 2023): FTD-TPI + bevacizumab（OS HR 0.61）成為 3L 新標準
- Fruquintinib/Fruzaqla (FRESCO 2018, FRESCO-2 Lancet 2023): 選擇性 VEGFR-1/2/3 抑制劑（OS HR 0.66）
- STELLAR-303 (Lancet 2025): zanzalintinib + atezolizumab vs regorafenib；另收錄 regorafenib + sintilimab (Nat Commun 2025)
- 關鍵問題：後線 TKI/免疫組合驗證、最佳序貫策略、生物標記分層

### 早期治療、直腸癌 TNT 與一般結直腸外科
- 涵蓋不屬於特定突變主題的重要大腸直腸癌證據：
  - 直腸癌全程新輔助治療（TNT）、器官保留與 watch-and-wait（非 dMMR 族群）
  - ctDNA-guided 輔助化療決策（如 DYNAMIC / CIRCULATE / GALAXY 類型隨機與前瞻試驗）
  - 早期大腸直腸癌輔助化療療程、非特定 biomarker 的 mCRC 一線化療、肝轉移切除策略與篩檢／指引更新

值得注意的里程碑類型：
- 後線新型 TKI / 免疫組合 Phase 3 RCT 與頭對頭比較
- 直腸癌 TNT、watch-and-wait 與器官保留的大型 RCT／長期追蹤
- ctDNA 導引輔助化療升級或降階的前瞻性隨機試驗
- 重要國際指引（NCCN、ESMO、ASCO、ASCRS）重大修訂""",
    "mCRC-RAS-wt": """## RAS 野生型 Anti-EGFR 治療演進
- FIRE-3 / CALGB 80405 / PEAK: 確立左側 RAS-wt 一線 anti-EGFR 地位與腫瘤側性（sidedness）關鍵預測力
- PARADIGM (JAMA 2023): 首個達 OS 主要終點的 Phase 3（左側 mOS 37.9 mo）
- Maintenance: VALENTINO (2019) / PanaMa (2022) 確認 anti-EGFR + 5-FU 維持優於單藥
- CHRONOS (Nat Med 2022): 證實 ctDNA-guided anti-EGFR rechallenge 概念
- 關鍵問題：ctDNA rechallenge 的 Phase 3 驗證（PARERE / FIRE-4 / CITRIC）、去強化維持策略、新型 EGFR 雙抗／ADC

值得注意的里程碑類型：
- ctDNA-guided anti-EGFR rechallenge 隨機試驗（如 PARERE、FIRE-4、PULSE）
- 新型 EGFR 標靶（bispecific 如 petosemtamab/amivantamab、ADC）在 mCRC 的前瞻數據
- Anti-EGFR 與免疫治療或三藥化療合併的前瞻性 RCT
- Maintenance / de-escalation 策略的長期 OS 追蹤""",
    "robotic-surgery": """## 機器人與微創結直腸手術演進
- ROLARR (2017): robotic vs laparoscopic TME，轉換率無顯著差異（N=471）
- COLRAR (2023): TME 完整性無顯著差異（N=295）
- REAL (2025): 首個顯示機器人 TME 局部復發率顯著低於腹腔鏡的 RCT（1.6% vs 4.0%）
- Network MA (2024): 機器人 TME 在部分病理與圍術期指標具優勢
- 關鍵問題：長期腫瘤學結果（OS/DFS）、機器人 CME 的隨機證據、體內吻合（intracorporeal anastomosis）與降低吻合口滲漏、新型機器人平台比較

值得注意的里程碑類型：
- REAL 試驗後續長期存活或亞組分析
- 機器人 CME vs 腹腔鏡 CME 的 RCT
- TaTME vs Robotic TME、體內 vs 體外吻合或降低吻合口漏的大型 RCT
- 新型手術機器人平台（Hugo、Versius、單孔 SP 等）與 AI 手術輔助的臨床數據""",
}


def build_system_prompt(topic):
    """Build a topic-specific system prompt for the Claude API classifier."""
    context = _TOPIC_CONTEXTS.get(topic, "")
    papers_js, metrics_js = _current_kb_context()
    existing_js = papers_js.get(topic, "")
    existing_metrics = metrics_js.get(topic, "")

    return f"""你是一位大腸直腸癌（CRC）臨床研究專家 AI agent，專精於「{topic}」領域。
你的角色是**主動研究**新發表的文獻，判斷其臨床重要性，並以該領域的既有知識脈絡解釋新發現的意義。

## 你擁有的工具

你可以使用以下工具來做更深入的研究：

1. **search_pubmed** — 搜尋 PubMed 查找相關文獻（例如：查找同一試驗的前期報告、查找 citing articles）
2. **fetch_paper_details** — 用 PMID 獲取完整的論文資訊和摘要
3. **lookup_existing_papers** — 查看知識庫中已有哪些文獻（幫助判斷 relations）
4. **web_fetch** — 瀏覽網頁（DOI 頁面、會議 abstract 頁面等）
5. **query_guidelines** — 查詢最新 ASCO/ESMO/NCCN 臨床指引（預快取或 PubMed fallback）

**使用策略：**
- 如果候選文獻的 abstract 資訊不足，用 fetch_paper_details 取得完整摘要
- 如果不確定這篇是否是某試驗的更新報告，用 search_pubmed 搜尋同一試驗名稱
- 如果需要確認既有文獻的 id 來填寫 relations，用 lookup_existing_papers
- 如果有 DOI 但缺少摘要，用 web_fetch 瀏覽 DOI 頁面
- 如果需要判斷新文獻是否改變現行治療標準，用 query_guidelines 查詢最新 guideline 推薦
- 對於 score >= 4 的文獻，**建議使用 query_guidelines** 確認其與現行指引的關係
- 不需要工具時就直接做出判斷——不要為了用工具而用工具

{context}

## 你目前追蹤的文獻（JSON 格式）
```json
{existing_js}
```

## 目前的柱狀圖數據
{
        f'''```javascript
{existing_metrics}
```

柱狀圖用於視覺比較不同方案的療效指標（mOS、ORR、mPFS 等）。
每根柱子格式：{{ label:"顯示名稱", val:數值, hr:"HR 或統計量", color:"色碼" }}
- color 規則：對照組用灰色（#cbd5e0/#a0aec0）、實驗組用主題色
- ongoing:true 表示數據尚未成熟
- val:null 表示尚未報告'''
        if existing_metrics
        else "（此主題目前沒有柱狀圖）"
    }

## 你的任務

對每篇新候選文獻：

1. **Relevance Score (1-5)**：
   - 5 = Practice-changing（改變治療標準、Phase 3 主要終點達標）
   - 4 = High-impact（重要的 Phase 2/3 更新、新機制驗證、重要 biomarker 數據）
   - 3 = Moderate（Phase 1/2 初步數據、pooled analysis、有參考價值）
   - 2 = Low（重複性結果、回顧性小樣本）
   - 1 = Not relevant（主題不符或無臨床意義）

2. **Contextual Analysis**（繁體中文，150-200 字）：
   - 這篇新研究回答了什麼問題？
   - 它與既有文獻的關係（builds_on / supersedes / contradicts 哪篇？）
   - 它為什麼重要（或不重要）？對臨床實踐的潛在影響

3. **Structured Output**（只有 score >= 4 才產出）：
   - bottomLine：繁體中文，100 字以內，一句話摘要
   - JS 物件草稿（符合既有 schema：id, year, journal, studyType, n, regimen, endpoint, result, bottomLine, doi, file, relations）
   - studyType 只能用：Phase 3 RCT, Phase 3 RCT (updated), Phase 2 RCT, Phase 2, Phase 1-2, Phase 1, Phase 1b, Biomarker (exploratory), Post-hoc analysis, Meta-analysis, Pooled analysis, Prospective cohort, Retrospective cohort, Guideline, Phase 3 (Cohort N), Phase 2 (updated), Phase 2 (exploratory)
   - relations 中的 targetId 必須是既有文獻中的 id
   - studyType 的期別與 RCT 必須是標題或摘要明確寫出的：摘要沒寫 phase 就不要標 Phase，沒寫隨機分派就不要標 RCT
   - 觀察性研究依摘要寫的方向選：寫 prospective 用 Prospective cohort，寫 retrospective 用 Retrospective cohort，不可互換
   - result 與 bottomLine 也一樣：不要提到標題或摘要沒寫的期別（例如摘要是 Phase 2，就不要寫「待 Phase 3 驗證」）
   - evidence：suggested_js 的 n、regimen、endpoint、result、bottomLine 中出現的**每一個數字**都要有一筆出處（劑量、人數、百分比、時間、HR、p 值都算；試驗名稱裡的數字如 STELLAR-303、以及「Phase 3」這類期別不算）
     - claim：含該數字的片段，例如 "mOS 30.3 vs 15.1 mo"
     - source="abstract"：quote 填摘要原文中**逐字**包含該數字的片段（直接複製，不可改寫、翻譯或改單位）
     - source="web_fetch"：url 填你用 web_fetch 讀到的網址，quote 填該頁原文片段
     - source="inference"：你推算或推論的數字（例如由百分比推回人數、兩組相加），quote 與 url 填 null
   - 摘要裡沒有的數字盡量不要寫進 result；確實需要時必須照上面標明來源，不可與摘要數字混在一起
   - 系統會逐字比對 quote 是否真的出現在摘要中，檢查上述五個欄位的每個數字都在摘要裡，並核對 studyType 的期別、RCT 與前瞻／回溯。全部通過才會自動發布，否則轉人工審核

4. **Chart Updates**（只有當新文獻有明確的療效數據可加入柱狀圖時才產出）：
   - 判斷新文獻是否有 mOS/ORR/mPFS 等數據值得加入比較圖
   - 如果是更新既有 bar 的數據（例如 ongoing trial 報告了最終數據），指明要更新哪根柱子
   - 如果是新增 bar（例如新的治療組合），提供完整的 bar 物件
   - 如果 max 值需要調整（新數據超過目前的 max），也要指明
   - 不是所有文獻都需要更新圖表——只有帶有直接可比較的療效數據才需要

## 輸出格式

```json
{{
  "relevance_score": 4,
  "contextual_analysis": "...",
  "bottom_line": "...",
  "suggested_js": {{...}},
  "suggested_filename": "Author_Journal_Year_TrialName.html",
  "relations": [{{"targetId": "...", "type": "builds_on"}}],
  "chart_updates": {{
    "mOS": {{
      "action": "add",
      "bar": {{ "label": "New\\nArm", "val": 25.0, "hr": "0.65", "color": "#38a169" }},
      "new_max": 35
    }},
    "ORR": {{
      "action": "update",
      "match_label": "EC+\\nFOLFIRI",
      "updates": {{ "val": 64.4, "ongoing": false }}
    }}
  }}
}}
```

chart_updates 規則：
- action "add"：在該 metric 的 bars 陣列末端加入新的 bar
- action "update"：找到 match_label 對應的既有 bar，更新其欄位（常見：ongoing trial 報告最終數據時把 val 從 null 改為實際值、ongoing 從 true 改為 false）
- new_max：如果新的 val 超過目前的 max，需要調高 max
- chart_updates 是選填——沒有圖表數據的文獻不要加這個欄位
- 只有 score >= 4 才需要 suggested_js / suggested_filename / relations / chart_updates
- Score < 4 時只需 relevance_score + contextual_analysis"""


def build_paper_prompt(paper):
    """Build the user message for a single candidate paper."""
    parts = ["# 新候選文獻\n"]
    parts.append(f"**Title:** {paper.get('title', 'N/A')}")
    parts.append(f"**Authors:** {paper.get('authors', 'N/A')}")
    parts.append(f"**Journal:** {paper.get('journal', 'N/A')}")
    parts.append(f"**Year:** {paper.get('year', 'N/A')}")
    parts.append(f"**DOI:** {paper.get('doi', 'N/A')}")
    parts.append(f"**PMID:** {paper.get('pmid', 'N/A')}")
    parts.append(f"**Source:** {paper.get('source', 'N/A')}")
    status = paper.get("abstract_status", "full")
    if status != "full":
        parts.append(
            f"\n⚠ **此摘要{'被截斷' if status == 'truncated' else '缺失'}**："
            "結果數據可能不在摘要中。評分與分析請說明這個限制，所有數字都要標明實際來源。"
        )
    if paper.get("maintainer_requested"):
        parts.append(
            "\n**維護者已指定這篇送人工審核**：照實評分，但不論 score 多少，"
            "都要產出 suggested_js、suggested_filename 與 evidence，讓審核者可以直接收錄。"
        )
    if paper.get("abstract"):
        parts.append(f"\n**Abstract:**\n{paper['abstract']}")
    return "\n".join(parts)
