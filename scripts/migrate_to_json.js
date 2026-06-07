/**
 * One-time migration: extract paper arrays and metrics from index.html
 * using Node's actual JS parser (not regex).
 *
 * Usage: node scripts/migrate_to_json.js
 * Output: data/papers.json
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const indexPath = path.join(__dirname, '..', 'index.html');
const outputPath = path.join(__dirname, '..', 'data', 'papers.json');

const html = fs.readFileSync(indexPath, 'utf-8');

// Extract the <script> content
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (!scriptMatch) {
  console.error('No <script> tag found');
  process.exit(1);
}

const scriptContent = scriptMatch[1];

// Extract just the data declarations (before the first function that uses DOM)
// We need: const *_PAPERS, const METRICS, const TME_METRICS, const CONF_HIGHLIGHTS
// Stop before: function navigate, function _activateView, etc.

// Find all const declarations we want
const dataVars = [
  'BRAF_PAPERS', 'RASWT_PAPERS', 'G12C_PAPERS', 'MSIH_PAPERS', 'HER2_PAPERS',
  'METRICS', 'TME_METRICS', 'CONF_HIGHLIGHTS'
];

// Extract each declaration by finding its start and the next const/let/function
let extractedCode = '';
for (const varName of dataVars) {
  const pattern = new RegExp(`const ${varName}\\s*=\\s*([\\s\\S]*?);\\s*(?=const |let |function |//)`, 'm');
  const match = scriptContent.match(pattern);
  if (match) {
    extractedCode += `const ${varName} = ${match[1]};\n`;
  }
}

// Run in a sandbox to get actual JS objects
const sandbox = {};
try {
  vm.runInNewContext(extractedCode + `
    this.BRAF_PAPERS = typeof BRAF_PAPERS !== 'undefined' ? BRAF_PAPERS : [];
    this.RASWT_PAPERS = typeof RASWT_PAPERS !== 'undefined' ? RASWT_PAPERS : [];
    this.G12C_PAPERS = typeof G12C_PAPERS !== 'undefined' ? G12C_PAPERS : [];
    this.MSIH_PAPERS = typeof MSIH_PAPERS !== 'undefined' ? MSIH_PAPERS : [];
    this.HER2_PAPERS = typeof HER2_PAPERS !== 'undefined' ? HER2_PAPERS : [];
    this.METRICS = typeof METRICS !== 'undefined' ? METRICS : null;
    this.TME_METRICS = typeof TME_METRICS !== 'undefined' ? TME_METRICS : null;
    this.CONF_HIGHLIGHTS = typeof CONF_HIGHLIGHTS !== 'undefined' ? CONF_HIGHLIGHTS : [];
  `, sandbox);
} catch (e) {
  console.error('Failed to evaluate JS:', e.message);
  console.error('Extracted code (first 500 chars):', extractedCode.substring(0, 500));
  process.exit(1);
}

// Build output structure keyed by Topic enum values
const output = {
  "mCRC-BRAF-V600E": {
    papers: sandbox.BRAF_PAPERS,
    metrics: sandbox.METRICS
  },
  "mCRC-KRAS-G12C": {
    papers: sandbox.G12C_PAPERS,
    metrics: null
  },
  "mCRC-MSI-H": {
    papers: sandbox.MSIH_PAPERS,
    metrics: null
  },
  "mCRC-HER2": {
    papers: sandbox.HER2_PAPERS,
    metrics: null
  },
  "mCRC-RAS-wt": {
    papers: sandbox.RASWT_PAPERS,
    metrics: null
  },
  "generic-CRS": {
    papers: [],
    metrics: null
  },
  "conference-highlights": {
    papers: [],
    metrics: null,
    highlights: sandbox.CONF_HIGHLIGHTS
  },
  "robotic-surgery": {
    papers: [],
    metrics: sandbox.TME_METRICS
  }
};

fs.writeFileSync(outputPath, JSON.stringify(output, null, 2));
console.log(`Written: ${outputPath}`);
console.log(`Topics: ${Object.keys(output).length}`);
for (const [topic, data] of Object.entries(output)) {
  const count = data.papers ? data.papers.length : 0;
  const highlights = data.highlights ? data.highlights.length : 0;
  const hasMetrics = data.metrics ? 'yes' : 'no';
  console.log(`  ${topic}: ${count} papers, ${highlights} highlights, metrics: ${hasMetrics}`);
}
