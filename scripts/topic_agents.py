"""Topic-specific sub-agent prompts for classifying and contextualizing new papers.

Each topic agent has deep domain knowledge (existing papers, trial evolution,
treatment landscape) so it can explain WHY a new finding matters in context.
"""

import json
import re
from pathlib import Path

from config import INDEX_HTML

# ---------------------------------------------------------------------------
# Extract existing papers from index.html at import time
# ---------------------------------------------------------------------------

def _extract_papers_from_html():
    """Parse all *_PAPERS arrays from index.html into a dict keyed by topic."""
    html = INDEX_HTML.read_text(encoding="utf-8")

    topic_map = {
        "BRAF_PAPERS": "mCRC-BRAF-V600E",
        "RASWT_PAPERS": "mCRC-RAS-wt",
        "G12C_PAPERS": "mCRC-KRAS-G12C",
        "MSIH_PAPERS": "mCRC-MSI-H",
        "HER2_PAPERS": "mCRC-HER2",
    }

    papers_by_topic = {}
    for var_name, topic in topic_map.items():
        pattern = rf"const {var_name}\s*=\s*\[(.*?)\];"
        match = re.search(pattern, html, re.DOTALL)
        if match:
            papers_by_topic[topic] = match.group(1).strip()

    return papers_by_topic


_PAPERS_JS = _extract_papers_from_html()


def _extract_metrics_from_html():
    """Parse METRICS and TME_METRICS from index.html."""
    html = INDEX_HTML.read_text(encoding="utf-8")

    metrics_map = {
        "METRICS": "mCRC-BRAF-V600E",
        "TME_METRICS": "robotic-surgery",
    }

    metrics_by_topic = {}
    for var_name, topic in metrics_map.items():
        pattern = rf"const {var_name}\s*=\s*(\{{.*?\}});"
        match = re.search(pattern, html, re.DOTALL)
        if match:
            metrics_by_topic[topic] = match.group(1).strip()

    return metrics_by_topic


_METRICS_JS = _extract_metrics_from_html()

# ---------------------------------------------------------------------------
# Topic-specific system prompts
# ---------------------------------------------------------------------------

_TOPIC_CONTEXTS = {
    "mCRC-BRAF-V600E": """## BRAF V600E mCRC 治療演進
- BEACON (2019-2021): 確立二線 encorafenib+cetuximab (EC) doublet 為標準
- BREAKWATER (2025-2026): 一線 EC+化療，mOS 30.3 mo，首次讓 BRAF V600E 追上 wt 的存活
- 已有 ctDNA dynamics、subsequent therapy、FOLFIRI cohort 的子分析
- 關鍵問題：最佳化療骨幹選擇、biomarker-driven sequencing、抗藥機制

值得注意的里程碑類型：
- 新的 BREAKWATER cohort/長期追蹤
- 非 EC 的 BRAF 標靶（如 dabrafenib/trametinib combo）
- BRAF V600E 在 neoadjuvant 或 perioperative 場景的應用
- ctDNA-guided 治療決策的前瞻性驗證""",

    "mCRC-KRAS-G12C": """## KRAS G12C mCRC 治療演進
- CodeBreaK 101/300: sotorasib+panitumumab 是首個 Phase 3 陽性結果（PFS HR 0.49）
- KRYSTAL-1: adagrasib+cetuximab ORR 46%，已獲 FDA 加速核准
- Divarasib+cetuximab: 早期數據 ORR 62.5%，待 RCT 確認
- 所有 G12C 抑制劑+anti-EGFR 的組合都優於單藥
- 關鍵問題：OS 獲益確認、最佳組合、抗藥機制、一線推進

值得注意的里程碑類型：
- CodeBreaK 300 最終 OS 分析
- Divarasib Phase 3 RCT 結果
- 新一代共價/非共價 G12C 抑制劑
- G12C 在一線治療的探索""",

    "mCRC-MSI-H": """## MSI-H/dMMR CRC 治療演進
- KEYNOTE-177: pembrolizumab 一線標準（PFS HR 0.60）
- CheckMate 142: nivo+ipi 雙免疫 ORR 55-69%
- NICHE/NICHE-2: neoadjuvant 雙免疫 pCR 68%，零復發
- Dostarlimab: 12/12 dMMR 直腸癌 cCR，免手術
- 關鍵問題：「watch and wait」長期安全性、雙免疫 vs 單免疫 Phase 3、pMMR 的免疫策略

值得注意的里程碑類型：
- Dostarlimab 擴大樣本的長期追蹤
- 雙免疫 vs pembrolizumab 的頭對頭 Phase 3
- Non-operative management 的前瞻性確認
- pMMR CRC 的免疫治療突破""",

    "mCRC-HER2": """## HER2+ mCRC 治療演進
- MyPathway/TRIUMPH: pertuzumab+trastuzumab proof of concept
- DESTINY-CRC01/02: T-DXd ORR 45% (IHC3+/ISH+)，5.4 mg/kg 為最佳劑量
- MOUNTAINEER: tucatinib+trastuzumab 首個 FDA 核准
- 突破發現：T-DXd 對 RAS mutant + HER2+ 也有效
- 關鍵問題：最佳檢測方法（IHC vs ctDNA）、HER2-low 的治療、與化療的組合

值得注意的里程碑類型：
- T-DXd Phase 3 RCT
- HER2 標靶在一線的前瞻性數據
- 新型 HER2 ADC 或 bispecific
- HER2-low mCRC 的治療探索""",

    "mCRC-RAS-wt": """## RAS 野生型 Anti-EGFR 治療演進
- FIRE-3/CALGB 80405: 確立左側 RAS-wt 一線 anti-EGFR 為標準
- PARADIGM: 唯一達 OS 主要終點的 Phase 3（左側 OS 37.9 mo）
- Sidedness 是最重要的預測因子（右側無效益）
- Maintenance: VALENTINO/PanaMa 確認 anti-EGFR+5-FU 維持優於 anti-EGFR 單藥
- CHRONOS: ctDNA-guided rechallenge proof of concept
- 關鍵問題：rechallenge 的前瞻性驗證、ctDNA 最佳 cutoff、新型 anti-EGFR

值得注意的里程碑類型：
- ctDNA-guided rechallenge Phase 3
- Anti-EGFR + 免疫治療組合
- 新型 EGFR 標靶（bispecific、ADC）
- Maintenance/de-escalation 的前瞻性策略""",

    "robotic-surgery": """## 機器人結直腸手術演進
- ROLARR (2017): robotic vs laparoscopic TME，轉換率 NS（N=471）
- COLRAR (2023): TME 完整性 NS（N=295）
- REAL (2025): 首個顯示機器人 TME 局部復發率優於腹腔鏡的 RCT（1.6% vs 4.0%）
- Network MA (2024): 機器人 TME 在病理指標上優於腹腔鏡
- 關鍵問題：長期腫瘤學結果、CME 的機器人數據、intracorporeal anastomosis 的安全性

值得注意的里程碑類型：
- REAL 試驗長期 OS/DFS 追蹤
- 機器人 CME 的 RCT
- TaTME vs Robotic TME 比較
- AI-assisted 手術的早期數據""",
}


def build_system_prompt(topic):
    """Build a topic-specific system prompt for the Claude API classifier."""
    context = _TOPIC_CONTEXTS.get(topic, "")
    existing_js = _PAPERS_JS.get(topic, "")
    existing_metrics = _METRICS_JS.get(topic, "")

    return f"""你是一位大腸直腸癌（CRC）臨床研究專家 AI agent，專精於「{topic}」領域。
你的角色是**主動研究**新發表的文獻，判斷其臨床重要性，並以該領域的既有知識脈絡解釋新發現的意義。

## 你擁有的工具

你可以使用以下工具來做更深入的研究：

1. **search_pubmed** — 搜尋 PubMed 查找相關文獻（例如：查找同一試驗的前期報告、查找 citing articles）
2. **fetch_paper_details** — 用 PMID 獲取完整的論文資訊和摘要
3. **lookup_existing_papers** — 查看知識庫中已有哪些文獻（幫助判斷 relations）
4. **web_fetch** — 瀏覽網頁（DOI 頁面、會議 abstract 頁面等）

**使用策略：**
- 如果候選文獻的 abstract 資訊不足，用 fetch_paper_details 取得完整摘要
- 如果不確定這篇是否是某試驗的更新報告，用 search_pubmed 搜尋同一試驗名稱
- 如果需要確認既有文獻的 id 來填寫 relations，用 lookup_existing_papers
- 如果有 DOI 但缺少摘要，用 web_fetch 瀏覽 DOI 頁面
- 不需要工具時就直接做出判斷——不要為了用工具而用工具

{context}

## 你目前追蹤的文獻（JavaScript 物件格式）
```javascript
{existing_js}
```

## 目前的柱狀圖數據
{f'''```javascript
{existing_metrics}
```

柱狀圖用於視覺比較不同方案的療效指標（mOS、ORR、mPFS 等）。
每根柱子格式：{{ label:"顯示名稱", val:數值, hr:"HR 或統計量", color:"色碼" }}
- color 規則：對照組用灰色（#cbd5e0/#a0aec0）、實驗組用主題色
- ongoing:true 表示數據尚未成熟
- val:null 表示尚未報告''' if existing_metrics else '（此主題目前沒有柱狀圖）'}

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
   - studyType 只能用：Phase 3 RCT, Phase 3 RCT (updated), Phase 2 RCT, Phase 2, Phase 1-2, Phase 1, Phase 1b, Biomarker (exploratory), Post-hoc analysis, Meta-analysis, Pooled analysis, Phase 3 (Cohort N), Phase 2 (exploratory)
   - relations 中的 targetId 必須是既有文獻中的 id

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
    parts = [f"# 新候選文獻\n"]
    parts.append(f"**Title:** {paper.get('title', 'N/A')}")
    parts.append(f"**Authors:** {paper.get('authors', 'N/A')}")
    parts.append(f"**Journal:** {paper.get('journal', 'N/A')}")
    parts.append(f"**Year:** {paper.get('year', 'N/A')}")
    parts.append(f"**DOI:** {paper.get('doi', 'N/A')}")
    parts.append(f"**PMID:** {paper.get('pmid', 'N/A')}")
    parts.append(f"**Source:** {paper.get('source', 'N/A')}")
    if paper.get("abstract"):
        parts.append(f"\n**Abstract:**\n{paper['abstract']}")
    return "\n".join(parts)
