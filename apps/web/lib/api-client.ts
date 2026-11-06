/**
 * Hardened API client and client-side DICOM upload validator for RADAR AI.
 */

import type { Study } from "@radar-ai/contracts";
import { getValidIdToken } from "@/lib/firebase-auth";

export const API_BASE = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

export interface UploadProgress {
  loaded: number;
  total: number;
  percent: number;
}

export class ApiUploadError extends Error {
  status: number;
  code: string;
  retryAfterSeconds?: number;

  constructor(
    message: string,
    status = 0,
    code = "ERR_RADAR_UPLOAD",
    retryAfterSeconds?: number
  ) {
    super(message);
    this.name = "ApiUploadError";
    this.status = status;
    this.code = code;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1
  );
  const value = bytes / Math.pow(1024, index);
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

const UUID_REGEX =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export const CLIENT_UPLOAD_LIMITS = {
  maxFiles: 512,
  maxFileBytes: 64 * 1024 * 1024,
  maxSeriesBytes: 512 * 1024 * 1024,
} as const;

const FORBIDDEN_EXTENSIONS = new Set([
  ".exe",
  ".dll",
  ".bat",
  ".cmd",
  ".sh",
  ".ps1",
  ".php",
  ".py",
  ".js",
  ".mjs",
  ".ts",
  ".html",
  ".htm",
  ".svg",
  ".zip",
  ".tar",
  ".gz",
]);

export function isValidUuid(value: string): boolean {
  return UUID_REGEX.test(value.trim());
}

export function assertValidUuid(value: string, label = "identifier"): string {
  const trimmed = value.trim();
  if (!isValidUuid(trimmed)) {
    throw new Error(`Format ${label} tidak valid.`);
  }
  return trimmed;
}

export async function apiFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  if (!path.startsWith("/")) {
    throw new Error("API path harus diawali dengan '/'.");
  }
  const headers = new Headers(init.headers);
  headers.set("X-Requested-With", "XMLHttpRequest");

  const token = await getValidIdToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  return fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    cache: init.cache ?? "no-store",
  });
}

export async function fetchAuthenticatedImageBlobUrl(
  studyId: string,
  sliceId: string,
  signal?: AbortSignal
): Promise<string> {
  const safeStudyId = assertValidUuid(studyId, "Study ID");
  const safeSliceId = assertValidUuid(sliceId, "Slice ID");
  const response = await apiFetch(
    `/v1/studies/${safeStudyId}/slices/${safeSliceId}/image`,
    { signal }
  );
  if (!response.ok) {
    throw new Error(`Gagal memuat pratinjau irisan CT (HTTP ${response.status}).`);
  }
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

function hasForbiddenMagicBytes(bytes: Uint8Array): boolean {
  if (bytes.length < 4) return true;
  // MZ (Windows PE), ELF, #!, PK (ZIP), %PDF
  if (bytes[0] === 0x4d && bytes[1] === 0x5a) return true;
  if (
    bytes[0] === 0x7f &&
    bytes[1] === 0x45 &&
    bytes[2] === 0x4c &&
    bytes[3] === 0x46
  ) {
    return true;
  }
  if (bytes[0] === 0x23 && bytes[1] === 0x21) return true;
  if (
    bytes[0] === 0x50 &&
    bytes[1] === 0x4b &&
    bytes[2] === 0x03 &&
    bytes[3] === 0x04
  ) {
    return true;
  }
  if (
    bytes[0] === 0x25 &&
    bytes[1] === 0x50 &&
    bytes[2] === 0x44 &&
    bytes[3] === 0x46
  ) {
    return true;
  }
  const headText = new TextDecoder("utf-8", { fatal: false })
    .decode(bytes.slice(0, 32))
    .trimStart()
    .toLowerCase();
  if (
    headText.startsWith("<!doctype html") ||
    headText.startsWith("<html") ||
    headText.startsWith("<script") ||
    headText.startsWith("<?php") ||
    headText.startsWith("<svg")
  ) {
    return true;
  }
  return false;
}

export async function validateDicomFilesBeforeUpload(
  fileList: FileList | File[]
): Promise<File[]> {
  const files = Array.from(fileList);
  if (files.length === 0) {
    throw new Error("Pilih minimal satu file DICOM CT.");
  }
  if (files.length > CLIENT_UPLOAD_LIMITS.maxFiles) {
    throw new Error(
      `Jumlah file melebihi batas maksimum (${CLIENT_UPLOAD_LIMITS.maxFiles} file per seri).`
    );
  }

  let totalBytes = 0;
  for (const file of files) {
    const lowerName = file.name.toLowerCase();
    const dotIndex = lowerName.lastIndexOf(".");
    if (dotIndex !== -1) {
      const ext = lowerName.slice(dotIndex);
      if (FORBIDDEN_EXTENSIONS.has(ext)) {
        throw new Error(
          `File "${file.name}" memiliki ekstensi terlarang (${ext}). Hanya file DICOM (.dcm) yang diizinkan.`
        );
      }
    }
    if (file.size <= 132) {
      throw new Error(
        `File "${file.name}" kosong atau terlalu kecil untuk menjadi objek DICOM Part 10.`
      );
    }
    if (file.size > CLIENT_UPLOAD_LIMITS.maxFileBytes) {
      throw new Error(
        `File "${file.name}" melebihi batas ukuran per file (maksimal 64 MB).`
      );
    }
    totalBytes += file.size;
    if (totalBytes > CLIENT_UPLOAD_LIMITS.maxSeriesBytes) {
      throw new Error(
        "Total ukuran seri DICOM melebihi batas maksimum (512 MB)."
      );
    }

    const headerBuffer = await file.slice(0, 132).arrayBuffer();
    const headerBytes = new Uint8Array(headerBuffer);
    if (hasForbiddenMagicBytes(headerBytes)) {
      throw new Error(
        `File "${file.name}" terdeteksi sebagai file eksekusi/dokumen aktif yang dilarang.`
      );
    }

    const dicmMagic = String.fromCharCode(
      headerBytes[128],
      headerBytes[129],
      headerBytes[130],
      headerBytes[131]
    );
    if (dicmMagic !== "DICM") {
      throw new Error(
        `File "${file.name}" bukan file DICOM Part 10 yang valid (header 'DICM' pada byte 128 tidak ditemukan).`
      );
    }
  }

  return files;
}

export async function uploadDicomSeriesWithProgress(
  studyId: string,
  files: File[],
  onProgress?: (progress: UploadProgress) => void,
  signal?: AbortSignal
): Promise<Study> {
  const safeStudyId = assertValidUuid(studyId, "Study ID");
  const token = await getValidIdToken();
  const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }

  return new Promise<Study>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/v1/studies/${safeStudyId}/dicom`, true);
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
    if (token) {
      xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    }
    if (signal) {
      if (signal.aborted) {
        xhr.abort();
        reject(
          new ApiUploadError(
            "Unggahan dibatalkan oleh pengguna.",
            0,
            "ERR_UPLOAD_ABORTED"
          )
        );
        return;
      }
      signal.addEventListener(
        "abort",
        () => {
          xhr.abort();
        },
        { once: true }
      );
    }

    xhr.upload.onprogress = (event) => {
      if (!onProgress) return;
      const total = event.lengthComputable && event.total > 0 ? event.total : totalBytes;
      const loaded = Math.min(event.loaded, total);
      const percent = total > 0 ? Math.min(99, Math.round((loaded / total) * 100)) : 50;
      onProgress({ loaded, total, percent });
    };

    xhr.onload = () => {
      const status = xhr.status;
      if (status >= 200 && status < 300) {
        try {
          const study = JSON.parse(xhr.responseText) as Study;
          onProgress?.({ loaded: totalBytes, total: totalBytes, percent: 100 });
          resolve(study);
        } catch {
          reject(
            new ApiUploadError(
              "Respons server tidak dapat dibaca sebagai JSON yang valid.",
              status,
              `ERR_PARSE_${status}`
            )
          );
        }
        return;
      }

      let detail = "";
      try {
        const parsed = JSON.parse(xhr.responseText) as { detail?: string };
        if (typeof parsed.detail === "string") {
          detail = parsed.detail;
        }
      } catch {
        detail = "";
      }

      const retryAfterRaw = xhr.getResponseHeader("Retry-After");
      const retryAfterSeconds = retryAfterRaw
        ? Number.parseInt(retryAfterRaw, 10)
        : undefined;

      if (status === 401) {
        reject(
          new ApiUploadError(
            "Sesi autentikasi tidak valid atau telah berakhir. Silakan login kembali.",
            401,
            "ERR_AUTH_401"
          )
        );
        return;
      }
      if (status === 413) {
        reject(
          new ApiUploadError(
            detail || "Ukuran file atau jumlah irisan DICOM melebihi batas maksimum server (64 MB/file, 512 MB/seri).",
            413,
            "ERR_PAYLOAD_TOO_LARGE_413"
          )
        );
        return;
      }
      if (status === 422) {
        const mappedDetail =
          detail === "Only CT images are accepted"
            ? "Tag DICOM Modality (0008,0060) menyatakan modalitas selain CT. Hanya irisan CT yang diterima."
            : detail || "Validasi seri DICOM gagal di server (pastikan irisan berasal dari seri CT anonim yang sama).";
        reject(
          new ApiUploadError(mappedDetail, 422, "ERR_DICOM_VALIDATION_422")
        );
        return;
      }
      if (status === 429) {
        const waitHint =
          retryAfterSeconds && Number.isFinite(retryAfterSeconds)
            ? `Coba lagi dalam ${retryAfterSeconds} detik.`
            : "Tunggu sekitar 1 menit sebelum mencoba kembali.";
        reject(
          new ApiUploadError(
            `Batas laju unggahan (rate limit) tercapai. ${waitHint}`,
            429,
            "ERR_RATE_LIMIT_429",
            retryAfterSeconds
          )
        );
        return;
      }

      reject(
        new ApiUploadError(
          detail || `Unggah seri DICOM gagal (HTTP ${status}).`,
          status,
          `ERR_HTTP_${status}`
        )
      );
    };

    xhr.onerror = () => {
      reject(
        new ApiUploadError(
          "Koneksi jaringan ke server API terputus saat mengunggah irisan DICOM. Pastikan layanan backend berjalan di port 8000.",
          0,
          "ERR_NETWORK_DISCONNECTED"
        )
      );
    };

    xhr.onabort = () => {
      reject(
        new ApiUploadError(
          "Unggahan dibatalkan oleh pengguna.",
          0,
          "ERR_UPLOAD_ABORTED"
        )
      );
    };

    xhr.send(formData);
  });
}

const DEMO_FIXTURE_FILES = [
  "slice-0.dcm",
  "slice-1.dcm",
  "slice-2.dcm",
  "slice-3.dcm",
  "slice-4.dcm",
] as const;

export async function fetchDemoDicomFixtures(): Promise<File[]> {
  const files: File[] = [];
  for (const filename of DEMO_FIXTURE_FILES) {
    const response = await fetch(`/fixtures/dicom/brain-ct/${filename}`, {
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(
        `Gagal memuat sampel DICOM lokal (${filename}, HTTP ${response.status}).`
      );
    }
    const blob = await response.blob();
    files.push(
      new File([blob], filename, {
        type: "application/dicom",
        lastModified: Date.now(),
      })
    );
  }
  return files;
}


