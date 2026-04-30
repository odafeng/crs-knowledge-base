# CRS Knowledge Base

A **topic-first, structured evidence map** for Colorectal Surgery — built as a Progressive Web App (PWA) on GitHub Pages.

**Live:** [odafeng.github.io/crs-knowledge-base](https://odafeng.github.io/crs-knowledge-base/)

---

## What This Is

A curated knowledge base where **topics are the entry point, not papers**. Each clinical topic (e.g., "BRAF V600E mCRC") contains structured trial cards with one-line bottom lines, evidence timelines, efficacy comparison charts, and relationship edges between papers.

This is not an auto-generated literature dump. Every bottom line is a clinician-digested summary. Every relationship edge (builds on / supersedes / contradicts) is manually curated.

## Design Principles

1. **Topic-first navigation** — Home → Category → Molecular subtype → Evidence map
2. **Structured paper model** — Every paper has: `year`, `journal`, `studyType`, `n`, `regimen`, `endpoint`, `result`, `bottomLine`, `doi`, `relations[]`
3. **Typed relationship edges** — `builds_on`, `supersedes`, `subgroup_of`, `same_regimen`, `contradicts`
4. **Timeline as the visual backbone** — X-axis = year, because temporal context is the most important axis in clinical evidence evolution
5. **Mobile-first** — Designed for phone screens, collapsible cards, touch-friendly

## Content Coverage

### mCRC (36 structured papers)

| Topic | Papers | Key Trials |
|---|---|---|
| BRAF V600E | 7 | BEACON, BREAKWATER Phase 3, ctDNA, Cohort 3 |
| RAS-wt Anti-EGFR | 9 | PARADIGM, FIRE-3, CALGB 80405, sidedness, CHRONOS |
| KRAS G12C | 7 | CodeBreaK 300, KRYSTAL-1, Divarasib |
| MSI-H / dMMR | 8 | KEYNOTE-177, CheckMate 142, NICHE-2, Dostarlimab |
| HER2+ | 5 | MOUNTAINEER, DESTINY-CRC01/02, TRIUMPH |

### Robotic Surgery

| Topic | Papers | Key Trials |
|---|---|---|
| TME | 5 | REAL (JAMA 2025), ROLARR, COLRAR, meta-analyses |
| Anastomosis | 9 | RiSSA series (5), ICA vs ECA meta-analysis, Safe Anastomosis Project |

## Tech Stack

- Single-file PWA (`index.html` + `sw.js` + `manifest.json`)
- Zero external dependencies — pure HTML/CSS/JS
- GitHub Pages hosting
- Offline-capable via Service Worker (network-first strategy)
- Paper data as JS objects in `index.html` (no backend)

## Paper Data Schema

```javascript
{
  id: 'beacon-2021',
  year: 2021,
  journal: 'JCO',
  studyType: 'Phase 3 RCT (updated)',  // Phase 1/2/3, RCT, MA, retrospective
  n: 665,
  regimen: 'EC doublet vs triplet vs control',
  endpoint: 'OS (updated)',
  result: 'EC mOS 9.3 mo, HR 0.61; triplet = doublet',
  bottomLine: 'Doublet is enough — adding binimetinib adds no OS benefit. FDA/EMA approved EC doublet.',
  doi: '10.1200/JCO.20.02088',
  file: 'docs/mCRC-BRAF-V600E/Tabernero_JCO_2021_BEACON.html',
  relations: [
    { targetId: 'beacon-2019', type: 'supersedes' }
  ]
}
```

## Relationship Types

| Type | Meaning | Example |
|---|---|---|
| `builds_on` | Extends or is inspired by | BREAKWATER builds on BEACON |
| `supersedes` | Updated analysis of same trial | BEACON 2021 supersedes BEACON 2019 |
| `subgroup_of` | Subgroup or biomarker analysis | ctDNA analysis is subgroup of BREAKWATER |
| `same_regimen` | Same drug, different backbone | BREAKWATER Cohort 3 (FOLFIRI) same regimen as Phase 3 (mFOLFOX6) |
| `contradicts` | Conflicting results | (reserved for future use) |

## Local Development

```bash
# Just open the file
open index.html

# Or serve locally
python3 -m http.server 8000
# Then visit http://localhost:8000
```

## Adding a New Paper

Edit the relevant `*_PAPERS` array in `index.html`:

```javascript
const NEW_PAPERS = [
  {
    id: 'unique-id',
    year: 2025,
    journal: 'NEJM',
    studyType: 'Phase 3 RCT',
    n: 500,
    regimen: 'Drug A vs Drug B',
    endpoint: 'PFS (primary)',
    result: 'mPFS 12.0 vs 8.0 mo, HR 0.65',
    bottomLine: 'Your one-line clinical takeaway here',
    doi: '10.1056/NEJMoaXXXXXXX',
    file: null,
    relations: [
      { targetId: 'existing-paper-id', type: 'builds_on' }
    ]
  }
];
```

Then add a navigate hook in the `navigate()` function and bump the SW cache version.

## Future Directions

- [ ] DOI/PMID auto-ingestion (CrossRef + PubMed API → auto-fill metadata → Claude bottom line → confirm)
- [ ] Anal Surgery topics (hemorrhoids, fistula, abscess)
- [ ] CME (complete mesocolic excision) evidence
- [ ] Search across all papers
- [ ] pgvector for semantic similarity ("find papers with similar conclusions")
- [ ] Migration to Next.js + Supabase for multi-user editing

## License

For personal clinical reference use. Paper metadata sourced from PubMed. Full-text availability subject to publisher access rights.
