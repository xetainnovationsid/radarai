# BUG-16: Client-Side Report Draft LocalStorage Quota Starvation and Missing LRU Eviction

**Severity:** P3 (Low)  
**Component:** `apps/web/components/ReportEditor.tsx`  
**Found in:** Comprehensive Codebase Bug Audit  
**Status:** Documented / Fix Available  
**Type:** Storage Resource Exhaustion / Unbounded Client State  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Description

In [`apps/web/components/ReportEditor.tsx`](../../apps/web/components/ReportEditor.tsx), draft clinical research reports are persisted to the browser's `localStorage` to ensure user edits are retained across tab switches:

```typescript
// Line 14:
const STORAGE_PREFIX = "radar_report_draft_v1_";

// Inside persistDraft():
window.localStorage.setItem(
  `${STORAGE_PREFIX}${study.study_id}`,
  JSON.stringify(nextDraft)
);
```

### Root Cause
1. Browser engines allocate a strict origin quota for `localStorage` (typically 5 MB in Safari, Chrome, and Firefox).
2. Each structured draft contains full text for Clinical Indication, Technique, Findings (including slice annotations, model confidence, and SAMIHS mask coordinates), Impression, and Reviewer Notes (~3–8 KB per report).
3. In a clinical research trial evaluating hundreds of CT studies, `window.localStorage` accumulates dozens of study entries.
4. Once total origin usage reaches 5 MB, calling `window.localStorage.setItem` throws `DOMException: QuotaExceededError`.
5. Although `ReportEditor.tsx` wraps `setItem` in a `try...catch` and displays `ERR_REPORT_STORAGE`, there is no automatic cleanup or LRU (Least Recently Used) eviction of older study drafts.
6. Consequently, once quota is reached, the user can no longer save new drafts for any subsequent studies on that browser unless they open DevTools or clear their entire browser site data.

---

## 2. Reproduction Steps

1. In browser DevTools Console, fill `localStorage` to near capacity:
   ```javascript
   const filler = "X".repeat(1024 * 1024);
   for (let i = 0; i < 4; i++) localStorage.setItem(`filler_${i}`, filler);
   ```
2. Open a study in RADAR AI and navigate to the **Editor Laporan** tab.
3. Edit any text field or click **Buat Draf dari AI**.
4. Observe: The red notice banner appears displaying:
   `Gagal menyimpan draf ke penyimpanan lokal browser (kuota penuh atau mode privat). ERR_REPORT_STORAGE`.
5. Refreshing the browser causes all newly typed edits on that study to be lost.

---

## 3. Impact Analysis

- **Data Loss on Quota Exhaustion**: Long-form findings and clinician impression edits are not saved to persistent client storage once quota is reached.
- **Degraded Multi-Study Research Workflow**: High-throughput reviewers reviewing 50+ studies per shift encounter persistent storage errors.

---

## 4. Recommended Remediation

Implement an automated bounded LRU sweep in `ReportEditor.tsx` whenever `QuotaExceededError` is trapped:

```typescript
function evictOldestDrafts(targetStudyId: string, maxRetained = 20): void {
  try {
    const keys: { key: string; updatedAt: number }[] = [];
    for (let i = 0; i < window.localStorage.length; i++) {
      const k = window.localStorage.key(i);
      if (k && k.startsWith(STORAGE_PREFIX) && k !== `${STORAGE_PREFIX}${targetStudyId}`) {
        try {
          const item = JSON.parse(window.localStorage.getItem(k) || "{}");
          keys.push({ key: k, updatedAt: new Date(item.updated_at || 0).getTime() });
        } catch {
          keys.push({ key: k, updatedAt: 0 });
        }
      }
    }
    // Evict oldest drafts first
    keys.sort((a, b) => a.updatedAt - b.updatedAt);
    while (keys.length >= maxRetained) {
      const oldest = keys.shift();
      if (oldest) window.localStorage.removeItem(oldest.key);
    }
  } catch {
    // Ignore cleanup errors
  }
}
```

