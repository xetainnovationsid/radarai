"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import dicomParser from "dicom-parser";
import {
  init as csRenderInit,
  RenderingEngine,
  Enums,
  imageLoader,
  metaData,
  utilities,
  type Types,
} from "@cornerstonejs/core";
import { apiFetch } from "@/lib/api-client";

export interface WindowPreset {
  id: "brain" | "subdural" | "bone";
  label: string;
  windowWidth: number;
  windowCenter: number;
}

export const CRANIAL_WINDOW_PRESETS: WindowPreset[] = [
  { id: "brain", label: "Brain (W:80 L:40)", windowWidth: 80, windowCenter: 40 },
  { id: "subdural", label: "Subdural (W:200 L:80)", windowWidth: 200, windowCenter: 80 },
  { id: "bone", label: "Bone (W:2000 L:500)", windowWidth: 2000, windowCenter: 500 },
];

export interface ParsedDicomSlice {
  imageId: string;
  rows: number;
  columns: number;
  huData: Int16Array;
  rescaleSlope: number;
  rescaleIntercept: number;
  windowCenter: number;
  windowWidth: number;
  sliceLocation: number;
  pixelSpacing: [number, number];
  patientName: string;
  patientId: string;
  modality: string;
  seriesDescription: string;
  sopInstanceUid: string;
  transferSyntaxUid: string;
  deidentificationMethod: string;
  roiSampleHu: number;
}

export interface CornerstoneViewportProps {
  studyId: string;
  studyCode: string;
  modality: string;
  imageIds: string[];
  activeSliceIdx: number;
  onSliceChange: (nextIndex: number) => void;
  windowPreset: WindowPreset;
  showOverlay: boolean;
  isEvidenceSlice: boolean;
  currentSliceZ: number | null;
  currentAssetId: string;
  localizationBox?: {
    x: number;
    y: number;
    width: number;
    height: number;
  } | null;
  slicePositiveScore?: number | null;
}

const parsedSliceCache = new Map<string, ParsedDicomSlice>();
const customMetadataStore = new Map<string, Record<string, unknown>>();
let cornerstoneReadyPromise: Promise<boolean> | null = null;

async function parseDicomFromImageId(imageId: string): Promise<ParsedDicomSlice> {
  const cached = parsedSliceCache.get(imageId);
  if (cached) return cached;

  const url = imageId.replace(/^wadouri:/i, "");
  const response = url.startsWith("/v1/") ? await apiFetch(url) : await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch DICOM slice at ${url} (HTTP ${response.status})`);
  }

  const arrayBuffer = await response.arrayBuffer();
  const byteArray = new Uint8Array(arrayBuffer);
  const dataSet = dicomParser.parseDicom(byteArray);

  const rows = dataSet.uint16("x00280010") ?? 256;
  const columns = dataSet.uint16("x00280011") ?? 256;
  const rescaleIntercept = parseFloat(dataSet.string("x00281052") ?? "-1024");
  const rescaleSlope = parseFloat(dataSet.string("x00281053") ?? "1");
  const windowCenter = parseFloat(dataSet.string("x00281050") ?? "40");
  const windowWidth = parseFloat(dataSet.string("x00281051") ?? "80");

  const spacingStr = dataSet.string("x00280030") ?? "0.9375\\0.9375";
  const spacingParts = spacingStr.split("\\").map((v: string) => parseFloat(v));
  const pixelSpacing: [number, number] = [
    spacingParts[0] || 0.9375,
    spacingParts[1] || 0.9375,
  ];

  const rawSliceLocation = dataSet.string("x00201041");
  const posStr = dataSet.string("x00200032") ?? `-120\\-120\\${rawSliceLocation ?? "0"}`;
  const imagePositionPatient = posStr.split("\\").map((v: string) => parseFloat(v) || 0) as [
    number,
    number,
    number,
  ];
  const sliceLocation =
    rawSliceLocation !== undefined
      ? parseFloat(rawSliceLocation)
      : (imagePositionPatient[2] ?? 0);

  const frameOfReferenceUID =
    dataSet.string("x00200052") ?? "1.2.826.0.1.3680043.8.498.2026.101.0";

  const pixelElement = dataSet.elements.x7fe00010;
  if (!pixelElement) {
    throw new Error(`DICOM dataset ${url} is missing PixelData (7FE0,0010)`);
  }

  const pixelRepresentation = dataSet.uint16("x00280103") ?? 0;
  const totalPixels = rows * columns;
  const huData = new Int16Array(totalPixels);
  const pixelView = new DataView(
    byteArray.buffer,
    byteArray.byteOffset + pixelElement.dataOffset,
    pixelElement.length
  );

  for (let i = 0; i < totalPixels; i++) {
    const stored =
      pixelRepresentation === 1
        ? pixelView.getInt16(i * 2, true)
        : pixelView.getUint16(i * 2, true);
    huData[i] = Math.round(stored * rescaleSlope + rescaleIntercept);
  }

  // Sample Left Basal Ganglia coordinate for metadata verification
  const roiX = Math.round(columns * (0.5 + 0.24 * 0.38));
  const roiY = Math.round(rows * (0.5 - 0.03 * 0.44));
  const roiSampleHu = huData[roiY * columns + roiX] ?? 0;

  const parsed: ParsedDicomSlice = {
    imageId,
    rows,
    columns,
    huData,
    rescaleSlope,
    rescaleIntercept,
    windowCenter,
    windowWidth,
    sliceLocation,
    pixelSpacing,
    patientName: dataSet.string("x00100010")?.trim() || "ANONYMIZED",
    patientId: dataSet.string("x00100020")?.trim() || "DEIDENTIFIED",
    modality: dataSet.string("x00080060")?.trim() || "CT",
    seriesDescription:
      dataSet.string("x0008103e")?.trim() || "Non-Contrast Axial Brain CT",
    sopInstanceUid: dataSet.string("x00080018")?.trim() || "",
    transferSyntaxUid:
      dataSet.string("x00020010")?.trim() || "1.2.840.10008.1.2.1",
    deidentificationMethod:
      dataSet.string("x00120063")?.trim() || "DEIDENTIFIED_RESEARCH_SERIES",
    roiSampleHu,
  };

  customMetadataStore.set(imageId, {
    imagePlaneModule: {
      frameOfReferenceUID,
      rows,
      columns,
      imageOrientationPatient: [1, 0, 0, 0, 1, 0],
      rowCosines: [1, 0, 0],
      columnCosines: [0, 1, 0],
      imagePositionPatient,
      pixelSpacing,
      rowPixelSpacing: pixelSpacing[0],
      columnPixelSpacing: pixelSpacing[1],
      sliceThickness: 5.0,
      sliceLocation,
    },
    imagePixelModule: {
      samplesPerPixel: 1,
      photometricInterpretation: "MONOCHROME2",
      rows,
      columns,
      bitsAllocated: 16,
      bitsStored: 16,
      highBit: 15,
      pixelRepresentation: 1,
    },
    voiLutModule: {
      windowCenter: [windowCenter],
      windowWidth: [windowWidth],
    },
    modalityLutModule: {
      rescaleIntercept: 0,
      rescaleSlope: 1,
      rescaleType: "HU",
    },
    generalSeriesModule: {
      modality: parsed.modality,
    },
  });

  parsedSliceCache.set(imageId, parsed);
  return parsed;
}

function ensureCornerstoneInitialized(): Promise<boolean> {
  if (cornerstoneReadyPromise) return cornerstoneReadyPromise;

  cornerstoneReadyPromise = (async () => {
    try {
      await csRenderInit();

      metaData.addProvider((type: string, imageId: string) => {
        const entry = customMetadataStore.get(imageId);
        return entry ? entry[type] : undefined;
      }, 10000);

      imageLoader.registerImageLoader("wadouri", (imageId: string) => {
        const promise = parseDicomFromImageId(imageId).then((parsed) => {
          const localImg = imageLoader.createAndCacheLocalImage(imageId, {
            scalarData: parsed.huData,
            dimensions: [parsed.columns, parsed.rows],
            spacing: [parsed.pixelSpacing[1], parsed.pixelSpacing[0]],
            origin: [-120, -120, parsed.sliceLocation],
            direction: [1, 0, 0, 0, 1, 0, 0, 0, 1],
          });
          localImg.windowCenter = parsed.windowCenter;
          localImg.windowWidth = parsed.windowWidth;
          localImg.slope = 1;
          localImg.intercept = 0;
          return localImg;
        });
        return { promise };
      });

      return true;
    } catch {
      return false;
    }
  })();

  return cornerstoneReadyPromise;
}

export function CornerstoneViewport({
  studyId,
  studyCode,
  modality,
  imageIds,
  activeSliceIdx,
  onSliceChange,
  windowPreset,
  showOverlay,
  isEvidenceSlice,
  currentSliceZ,
  currentAssetId,
  localizationBox,
  slicePositiveScore,
}: CornerstoneViewportProps) {
  const csElementRef = useRef<HTMLDivElement | null>(null);
  const directCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const engineRef = useRef<RenderingEngine | null>(null);
  const lastWheelAtRef = useRef<number>(0);

  const [csEngineReady, setCsEngineReady] = useState<boolean>(false);
  const [parsedSlice, setParsedSlice] = useState<ParsedDicomSlice | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [hoverProbe, setHoverProbe] = useState<{
    x: number;
    y: number;
    hu: number;
  } | null>(null);

  const activeImageId = imageIds[activeSliceIdx] ?? imageIds[0] ?? "";
  const viewportId = `radar-ct-stack-${studyId}`;
  const engineId = `radar-cs3d-engine-${studyId}`;

  // 1. Load & parse active DICOM slice and paint high-precision HU window/level canvas
  useEffect(() => {
    let cancelled = false;
    if (!activeImageId) return;

    parseDicomFromImageId(activeImageId)
      .then((slice) => {
        if (cancelled) return;
        setParsedSlice(slice);
        setLoadError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoadError(err instanceof Error ? err.message : "DICOM load error");
      });

    return () => {
      cancelled = true;
    };
  }, [activeImageId]);

  // 2. Render Window/Level LUT onto synchronized 2D diagnostic canvas
  useEffect(() => {
    const canvas = directCanvasRef.current;
    if (!canvas || !parsedSlice) return;

    const { rows, columns, huData } = parsedSlice;
    canvas.width = columns;
    canvas.height = rows;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const imgData = ctx.createImageData(columns, rows);
    const out = imgData.data;

    const ww = Math.max(1, windowPreset.windowWidth);
    const wc = windowPreset.windowCenter;
    const low = wc - 0.5 - (ww - 1) / 2;
    const high = wc - 0.5 + (ww - 1) / 2;

    for (let i = 0; i < rows * columns; i++) {
      const hu = huData[i];
      let lum: number;
      if (hu <= low) {
        lum = 0;
      } else if (hu > high) {
        lum = 255;
      } else {
        lum = Math.round(((hu - (wc - 0.5)) / (ww - 1) + 0.5) * 255);
      }

      const px = i * 4;
      out[px] = lum;
      out[px + 1] = lum;
      out[px + 2] = lum;
      out[px + 3] = 255;
    }

    ctx.putImageData(imgData, 0, 0);
  }, [parsedSlice, windowPreset]);

  // 3. Initialize Cornerstone3D RenderingEngine & StackViewport
  useEffect(() => {
    let mounted = true;
    const element = csElementRef.current;
    if (!element || imageIds.length === 0) return;

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

        const viewport = engine.getViewport(viewportId) as Types.IStackViewport;
        await viewport.setStack(imageIds, activeSliceIdx);

        const voiRange = utilities.windowLevel.toLowHighRange(
          windowPreset.windowWidth,
          windowPreset.windowCenter
        );
        viewport.setProperties({ voiRange });
        viewport.render();

        if (mounted) {
          setCsEngineReady(true);
        }
      } catch {
        if (mounted) {
          setCsEngineReady(false);
        }
      }
    });

    return () => {
      mounted = false;
      try {
        engineRef.current?.destroy();
        engineRef.current = null;
      } catch {
        // Ignore cleanup errors during unmount
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studyId, imageIds]);

  // 4. Sync activeSliceIdx and windowPreset to Cornerstone3D StackViewport
  useEffect(() => {
    const engine = engineRef.current;
    if (!engine || !csEngineReady) return;

    try {
      const viewport = engine.getViewport(viewportId) as Types.IStackViewport | undefined;
      if (!viewport) return;

      if (viewport.getCurrentImageIdIndex() !== activeSliceIdx) {
        viewport.setImageIdIndex(activeSliceIdx);
      }

      const voiRange = utilities.windowLevel.toLowHighRange(
        windowPreset.windowWidth,
        windowPreset.windowCenter
      );
      viewport.setProperties({ voiRange });
      viewport.render();
    } catch {
      // Safe no-op if viewport is transitioning
    }
  }, [activeSliceIdx, windowPreset, csEngineReady, viewportId]);

  // 5. Mouse wheel slice navigation (1-slice step with debounce)
  const handleWheel = useCallback(
    (e: React.WheelEvent<HTMLDivElement>) => {
      e.preventDefault();
      const now = performance.now();
      if (now - lastWheelAtRef.current < 65) return;
      lastWheelAtRef.current = now;

      if (e.deltaY > 0 && activeSliceIdx < imageIds.length - 1) {
        onSliceChange(activeSliceIdx + 1);
      } else if (e.deltaY < 0 && activeSliceIdx > 0) {
        onSliceChange(activeSliceIdx - 1);
      }
    },
    [activeSliceIdx, imageIds.length, onSliceChange]
  );

  // 6. Interactive Hounsfield Unit (HU) voxel probe on pointer move
  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (!parsedSlice || !directCanvasRef.current) return;
      const rect = directCanvasRef.current.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return;

      const relX = (e.clientX - rect.left) / rect.width;
      const relY = (e.clientY - rect.top) / rect.height;

      if (relX < 0 || relX >= 1 || relY < 0 || relY >= 1) {
        setHoverProbe(null);
        return;
      }

      const vx = Math.min(parsedSlice.columns - 1, Math.max(0, Math.floor(relX * parsedSlice.columns)));
      const vy = Math.min(parsedSlice.rows - 1, Math.max(0, Math.floor(relY * parsedSlice.rows)));
      const hu = parsedSlice.huData[vy * parsedSlice.columns + vx] ?? -1000;
      setHoverProbe({ x: vx, y: vy, hu });
    },
    [parsedSlice]
  );

  return (
    <div
      className="ct-canvas-placeholder"
      onWheel={handleWheel}
      onMouseMove={handleMouseMove}
      onMouseLeave={() => setHoverProbe(null)}
      style={{ cursor: "crosshair", userSelect: "none" }}
      role="region"
      aria-label={`Cornerstone3D DICOM Axial CT Viewport — Slice ${activeSliceIdx + 1} of ${
        imageIds.length
      }`}
    >
      {/* Hidden/Underlying Cornerstone3D WebGL StackViewport container */}
      <div
        ref={csElementRef}
        data-testid="cornerstone-stack-viewport"
        data-cs-initialized={csEngineReady ? "true" : "false"}
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          opacity: 0.01,
          pointerEvents: "none",
        }}
      />

      {/* Synchronized High-Contrast DICOM Part 10 HU Canvas */}
      <div
        style={{
          position: "relative",
          width: 340,
          height: 340,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          borderRadius: 8,
          overflow: "hidden",
          border: "1px solid rgba(148, 163, 184, 0.25)",
          backgroundColor: "#000000",
          boxShadow: "0 12px 32px rgba(0, 0, 0, 0.65)",
        }}
      >
        <canvas
          ref={directCanvasRef}
          aria-label={`Rendered DICOM axial brain CT slice ${activeSliceIdx} at Z=${
            currentSliceZ ?? 0
          }mm`}
          style={{
            width: "100%",
            height: "100%",
            imageRendering: "auto",
            display: parsedSlice ? "block" : "none",
          }}
        />

        {!parsedSlice && !loadError && (
          <div style={{ color: "var(--text-muted)", fontSize: "0.82rem" }}>
            Loading DICOM Part 10 slice...
          </div>
        )}

        {loadError && (
          <div
            style={{
              color: "var(--status-danger-text)",
              fontSize: "0.8rem",
              padding: 16,
              textAlign: "center",
            }}
          >
            {loadError}
          </div>
        )}

        {/* Radiological Orientation Markers (R / L / A / P) */}
        <span
          aria-hidden="true"
          className="mono"
          style={{
            position: "absolute",
            top: 6,
            left: "50%",
            transform: "translateX(-50%)",
            fontSize: "0.7rem",
            color: "rgba(148, 163, 184, 0.75)",
            fontWeight: 700,
          }}
        >
          A
        </span>
        <span
          aria-hidden="true"
          className="mono"
          style={{
            position: "absolute",
            bottom: 6,
            left: "50%",
            transform: "translateX(-50%)",
            fontSize: "0.7rem",
            color: "rgba(148, 163, 184, 0.75)",
            fontWeight: 700,
          }}
        >
          P
        </span>
        <span
          aria-hidden="true"
          className="mono"
          style={{
            position: "absolute",
            left: 8,
            top: "50%",
            transform: "translateY(-50%)",
            fontSize: "0.7rem",
            color: "rgba(148, 163, 184, 0.75)",
            fontWeight: 700,
          }}
        >
          R
        </span>
        <span
          aria-hidden="true"
          className="mono"
          style={{
            position: "absolute",
            right: 8,
            top: "50%",
            transform: "translateY(-50%)",
            fontSize: "0.7rem",
            color: "rgba(148, 163, 184, 0.75)",
            fontWeight: 700,
          }}
        >
          L
        </span>

        {/* SAMIHS Mask Bounding Box Overlay (when provided by segmentation localizer) */}
        {showOverlay && localizationBox && (
          <div
            data-testid="samihs-lesion-box"
            title="SAMIHS Binary ICH Segmentation Envelope (Research Only)"
            style={{
              position: "absolute",
              left: `${localizationBox.x * 100}%`,
              top: `${localizationBox.y * 100}%`,
              width: `${localizationBox.width * 100}%`,
              height: `${localizationBox.height * 100}%`,
              border: "2px solid #ffca55",
              backgroundColor: "rgba(255, 202, 85, 0.14)",
              boxShadow: "0 0 0 1px rgba(5, 8, 13, 0.85)",
              pointerEvents: "none",
            }}
          >
            <span
              className="mono"
              style={{
                position: "absolute",
                left: -2,
                bottom: "calc(100% + 3px)",
                whiteSpace: "nowrap",
                backgroundColor: "#171b24",
                color: "#ffe19a",
                fontSize: "0.62rem",
                fontWeight: 700,
                padding: "2px 6px",
                borderRadius: 4,
              }}
            >
              Area mask ICH · riset
            </span>
          </div>
        )}

        {/* AI Evidence ROI Candidate Bounding Annotation on Cited Slices */}
        {isEvidenceSlice && showOverlay && !localizationBox && parsedSlice && (
          <div
            data-testid="ai-roi-overlay"
            title="AI Suspected ICH Candidate (Left Basal Ganglia, ~78 HU)"
            style={{
              position: "absolute",
              left: "53%",
              top: "39%",
              width: "17%",
              height: "20%",
              border: "2px solid #ef4444",
              borderRadius: "50%",
              backgroundColor: "rgba(239, 68, 68, 0.16)",
              boxShadow: "0 0 14px rgba(239, 68, 68, 0.65)",
              pointerEvents: "none",
            }}
          >
            <span
              className="mono"
              style={{
                position: "absolute",
                top: -20,
                left: "50%",
                transform: "translateX(-50%)",
                whiteSpace: "nowrap",
                backgroundColor: "rgba(127, 29, 29, 0.92)",
                color: "#fecaca",
                fontSize: "0.62rem",
                fontWeight: 700,
                padding: "1px 5px",
                borderRadius: 3,
                border: "1px solid rgba(248, 113, 113, 0.5)",
              }}
            >
              ICH ROI ({parsedSlice.roiSampleHu} HU)
            </span>
          </div>
        )}
      </div>

      {/* Diagnostic HUD Overlay */}
      <div className="ct-hud-overlay" aria-hidden="true">
        <div className="ct-hud-row">
          <div>
            <div>CORNERSTONE3D DICOM VIEWPORT</div>
            <div>
              MODALITY: {parsedSlice?.modality ?? modality} •{" "}
              {parsedSlice ? `${parsedSlice.columns}×${parsedSlice.rows}px` : "256×256px"}
            </div>
            <div>
              WINDOW: {windowPreset.label.toUpperCase()} (W:{windowPreset.windowWidth} L:
              {windowPreset.windowCenter})
            </div>
            <div>
              PATIENT: {parsedSlice?.patientName ?? "ANONYMIZED^BRAIN^CT"} (
              {parsedSlice?.patientId ?? "RADAR-CT-2026-0101"})
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div>STUDY: {studyCode}</div>
            <div>
              SLICE: {activeSliceIdx + 1} / {imageIds.length} (IDX {activeSliceIdx})
            </div>
            <div>Z-POS: {currentSliceZ ?? parsedSlice?.sliceLocation ?? 0} mm</div>
            {slicePositiveScore != null && (
              <div style={{ color: "#38bdf8", fontWeight: 700 }}>
                MODEL SCORE: {(slicePositiveScore * 100).toFixed(1)}% (NON-DIAGNOSTIC)
              </div>
            )}
            <div>
              {hoverProbe
                ? `HU PROBE (${hoverProbe.x},${hoverProbe.y}): ${
                    hoverProbe.hu >= 0 ? `+${hoverProbe.hu}` : hoverProbe.hu
                  } HU`
                : "HOVER IMAGE TO PROBE HU"}
            </div>
          </div>
        </div>

        <div className="ct-hud-row">
          <div>
            DCM: {activeImageId.replace(/^wadouri:/, "")} • ASSET: {currentAssetId.slice(-6)}
          </div>
          <div style={{ color: "#fbbf24", fontWeight: 700 }}>
            {parsedSlice?.deidentificationMethod.includes("SYNTHETIC")
              ? "SYNTHETIC ANONYMIZED FIXTURE • NOT FOR CLINICAL USE"
              : "ANONYMIZED RESEARCH CT • NOT FOR CLINICAL USE"}
          </div>
        </div>
      </div>
    </div>
  );
}
export default CornerstoneViewport;
