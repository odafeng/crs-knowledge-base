-- #238 and #239 (2026-11-21): two robotic-surgery papers the maintainer accepted. robotic-surgery renders hand-written
-- cards, not a papers list (ADR-0013), and after cutover the database is the only content writer (ADR-0021), so the
-- cards are added here. Both are about the anastomosis (planned intracorporeal anastomosis on both arms; the stapler
-- used for rectal transection and anastomosis), so they join the anastomosis section next to the ICA vs ECA cards.
-- Runs once per database; a database without the robotic-surgery row (CI, a fresh staging) is left unchanged.
update app.topics t
set robotic_sections = (
  select jsonb_agg(
    case when s ->> 'slug' = 'anastomosis' then
      jsonb_set(
        jsonb_set(s, '{cards}', (s -> 'cards') || $cards$[
  {
    "tag": "ICA",
    "title": "Robotic vs Lap 右半結腸切除（皆 ICA）Meta-analysis（Langenbecks Arch Surg 2026, N=977）",
    "body": "\n    <p><strong>Anwar et al.</strong> — GRADE 評估的系統性回顧，只納入兩組都計畫體內吻合（ICA）的研究，避免把「robotic ICA vs 腹腔鏡 ECA」混在一起；4 篇非隨機觀察性研究（Robotic 603 vs Lap 374）</p>\n    <table>\n      <tbody><tr><th>指標</th><th>Robotic vs Lap</th><th>效果量 (95% CI)</th></tr>\n      <tr><td>整體術後併發症（主要終點）</td><td>142/603 vs 107/374</td><td>RR 0.84 (0.67–1.05)</td></tr>\n      <tr><td>轉開腹</td><td>7/603 vs 8/374</td><td>RR 0.91 (0.13–6.33)</td></tr>\n      <tr><td>吻合口滲漏</td><td>16/603 vs 11/374</td><td>RR 0.88 (0.41–1.89)</td></tr>\n      <tr><td>住院天數</td><td>—</td><td>MD −0.47 天 (−1.00 to 0.06)</td></tr>\n      <tr><td>淋巴結數</td><td>—</td><td>MD −0.55 顆 (−3.16 to 2.06)</td></tr>\n      <tr><td>手術時間</td><td>Robotic 較長（NS）</td><td>MD +39.69 min (−2.19 to 81.57)，I²=96%</td></tr>\n    </tbody></table>\n    <div class=\"note\">兩組都做體內吻合時，機器人與腹腔鏡右半結腸切除的短期結果沒有顯著差異。只有 4 篇非隨機研究，屬探索性，不足以證明等效；死亡率與長期腫瘤學結果僅敘述性整理。</div>\n    <p><a href=\"https://doi.org/10.1007/s00423-026-04196-y\" rel=\"noopener noreferrer\">📄 DOI: 10.1007/s00423-026-04196-y</a></p>"
  },
  {
    "tag": "RCT",
    "title": "SureForm 機器人釘合器 RCT（Surg Endosc 2026, N=276）",
    "body": "\n    <p><strong>Ye et al.</strong> — 單中心前瞻性隨機試驗（2022–2024），機器人保肛前切除，直腸橫斷與吻合用 da Vinci SureForm 機器人線性釘合器 vs 傳統腹腔鏡可轉彎線性釘合器</p>\n    <table>\n      <tbody><tr><th>指標</th><th>SureForm</th><th>腹腔鏡釘合器</th><th>P</th></tr>\n      <tr><td>30 天吻合口滲漏（主要終點）</td><td><strong>6.67%</strong></td><td>14.07%</td><td>0.046</td></tr>\n      <tr><td>Clavien-Dindo ≥ II 滲漏</td><td>1.48%</td><td>6.67%</td><td>0.031</td></tr>\n      <tr><td>滲漏（ITT）</td><td>6.57%</td><td>14.39%</td><td>0.034</td></tr>\n      <tr><td>直腸橫斷釘匣數</td><td>1.95±0.67</td><td>2.32±0.85</td><td>&lt;0.001</td></tr>\n      <tr><td>使用 ≥3 個釘匣</td><td>18.50%</td><td>37.00%</td><td>&lt;0.001</td></tr>\n    </tbody></table>\n    <div class=\"note\">多變項分析中，釘匣 &gt;2、腫瘤位置、吻合口出血是滲漏的獨立危險因子，與「減少橫斷釘匣數」的機轉一致。單中心、主要終點 P 值接近 0.05，屬器材比較，需多中心試驗驗證。</div>\n    <p><a href=\"https://doi.org/10.1007/s00464-026-13349-5\" rel=\"noopener noreferrer\">📄 DOI: 10.1007/s00464-026-13349-5</a></p>"
  }
]$cards$::jsonb),
        '{timeline}', (s -> 'timeline') || $timeline$[
  {"yr": "2026", "cls": "beacon", "file": "https://doi.org/10.1007/s00464-026-13349-5", "venue": "Surg Endosc", "finding": "SureForm RCT<br>AL <strong>6.7%</strong> vs 14.1%<br>N=276"},
  {"yr": "2026", "cls": "breakwater", "file": "https://doi.org/10.1007/s00423-026-04196-y", "venue": "Langenbecks", "finding": "R vs L 右半（皆 ICA）MA<br>併發症 RR 0.84 NS<br>N=977"}
]$timeline$::jsonb)
    else s end
    order by ord)
  from jsonb_array_elements(t.robotic_sections) with ordinality as e(s, ord)
)
where t.key = 'robotic-surgery'
  and exists (select 1 from jsonb_array_elements(t.robotic_sections) s where s ->> 'slug' = 'anastomosis')
  and not exists (
    select 1 from jsonb_array_elements(t.robotic_sections) s, jsonb_array_elements(s -> 'cards') c
    where c ->> 'body' like '%10.1007/s00464-026-13349-5%'
  );
