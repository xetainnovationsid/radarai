# BUG-09: WebGL2 Context Leaks and Unhandled Context Loss on Rapid Study Switching

**Severity:** P2 (Medium)  
**Component:** `apps/web/components/CornerstoneViewport.tsx`  
**Found in:** Sprint 2 Hardening Audit  
**Type:** WebGL Lifecycle / Resource Contention  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Description

In [`apps/web/components/CornerstoneViewport.tsx`](file:///Users/shine/Documents/Shine's%20Personal%20Folder/Code/Tel-U/radar-ai/apps/web/components/CornerstoneViewport.tsx), a `@cornerstonejs/core` `RenderingEngine` is instantiated per study:

```typescript
// Line 282:
const engineId = `radar-cs3d-engine-${studyId}`;
const viewportId = `radar-ct-stack-${studyId}`;

// Line 352-365:
ensureCornerstoneInitialized().then(async (ok) => {
  if (!mounted || !ok || !csElementRef.current) return;
  try {
    const engine = new RenderingEngine(engineId);
    engineRef.current = engine;

    engine.enableElement({
      viewportId,
      type: Enums.ViewportType.STACK,
      element: csElementRef.current,
      defaultOptions: {
        background: [0, 0, 0] as Types.Point3,
      },
    });
    // ...
```

### Root Cause
1. **Asynchronous Initialization Race**: `ensureCornerstoneInitialized()` is asynchronous. If `studyId` or `imageIds` change in rapid succession (e.g. user clicks between studies in rapid navigation), the cleanup callback:
   ```typescript
   return () => {
     mounted = false;
     try {
       engineRef.current?.destroy();
       engineRef.current = null;
     } catch {}
   };
   ```
   runs *before* the in-flight `ensureCornerstoneInitialized().then(...)` completes. The previous `engine` reference is nullified, but if the promise executes right after, it may instantiate a `new RenderingEngine(engineId)` on an already unmounted or repurposed DOM node, leaking a WebGL2 rendering context.
2. **Exceeding Browser WebGL Context Limit**: Web browsers enforce a hard per-domain limit on concurrent active WebGL contexts (typically 8 to 16 in Chrome/Firefox/Safari). When repeatedly toggling render modes (`dicom` vs `preview`) or navigating between studies without explicit `engine.disableElement(viewportId)` prior to `destroy()`, old WebGL contexts are not reclaimed synchronously by the browser's GC. When the limit is exceeded, the browser triggers `webglcontextlost` on older contexts.
3. **No `webglcontextlost` Event Handling**: `CornerstoneViewport` does not attach `webglcontextlost` or `webglcontextrestored` event listeners to recover gracefully. Once a context is lost, the viewport remains pitch black with no user feedback.

---

## 2. Reproduction Steps

1. Run the web application (`npm run dev` in `apps/web`).
2. Rapidly switch back and forth between study URLs (e.g. 10 times in 5 seconds).
3. Switch `viewerMode` between `dicom` and `preview` repeatedly.
4. Check DevTools console for warnings:
   ```text
   WARNING: Too many active WebGL contexts. Oldest context will be lost.
   WebGL: CONTEXT_LOST_WEBGL: loseContext: context lost
   ```
5. Observe viewport rendering failure (canvas becomes permanently black).

---

## 3. Impact Analysis

- **Viewer Blackout**: Once WebGL context loss occurs, the Cornerstone3D stack viewport ceases rendering CT slices entirely until the user hard-refreshes the browser page.
- **Diagnostics Impairment**: Researchers cannot inspect slice series interactively without disrupting their workflow.

---

## 4. Recommended Remediation

1. Explicitly invoke `engine.disableElement(viewportId)` before `engine.destroy()`.
2. Add an initialization lock/cancellation token to avoid instantiating engines from orphaned promises.
3. Attach `webglcontextlost` listener on the canvas element to trigger fallback to the 2D canvas preview or auto-reinitialize the engine upon `webglcontextrestored`.

```typescript
// Example cleanup enhancement:
return () => {
  mounted = false;
  if (engineRef.current) {
    try {
      engineRef.current.disableElement(viewportId);
      engineRef.current.destroy();
    } catch {
      // Safe no-op
    } finally {
      engineRef.current = null;
    }
  }
};
```

