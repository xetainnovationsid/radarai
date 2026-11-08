"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { Study, StudyStatus } from "@radar-ai/contracts";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingSkeleton } from "@/components/states/LoadingSkeleton";
import { apiFetch } from "@/lib/api-client";

type StatusFilter = "all" | StudyStatus;

const STATUS_LABELS: Record<StudyStatus, string> = {
  ready: "Awaiting review",
  uploaded: "Uploaded",
  processing: "Processing",
  failed: "Validation failed",
};

export default function StudiesLibraryPage() {
  return (
    <Suspense fallback={<div className="study-library-page"><LoadingSkeleton label="Loading study library…" /></div>}>
      <StudiesLibraryContent />
    </Suspense>
  );
}

function StudiesLibraryContent() {
  const searchParams = useSearchParams();
  const [studies, setStudies] = useState<Study[]>([]);
  const [selectedStudyId, setSelectedStudyId] = useState("");
  const [status, setStatus] = useState<StatusFilter>(() => {
    const initialStatus = searchParams.get("status");
    return initialStatus === "ready" || initialStatus === "uploaded" || initialStatus === "processing" || initialStatus === "failed"
      ? initialStatus
      : "all";
  });
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const fetchStudies = useCallback(async () => {
    const response = await apiFetch("/v1/studies");
    if (!response.ok) throw new Error(`Study library returned HTTP ${response.status}.`);
    return (await response.json()) as Study[];
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const data = await fetchStudies();
      setStudies(data);
      setSelectedStudyId((current) => current || data[0]?.study_id || "");
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The study library could not be reached.");
    } finally {
      setRefreshing(false);
    }
  }, [fetchStudies]);

  useEffect(() => {
    let cancelled = false;

    void fetchStudies()
      .then((data) => {
        if (cancelled) return;
        setStudies(data);
        setSelectedStudyId((current) => current || data[0]?.study_id || "");
        setError("");
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setError(cause instanceof Error ? cause.message : "The study library could not be reached.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [fetchStudies]);

  const filteredStudies = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return studies.filter((study) => {
      const matchesStatus = status === "all" || study.status === status;
      const matchesQuery = !normalized || study.study_id.toLowerCase().includes(normalized);
      return matchesStatus && matchesQuery;
    });
  }, [query, status, studies]);

  const selectedStudy = filteredStudies.find((study) => study.study_id === selectedStudyId) ?? filteredStudies[0] ?? null;

  return (
    <div className="study-library-page">
      <header className="library-intro">
        <div>
          <p className="eyebrow">STUDIES <span>/</span> LIBRARY</p>
          <h1>Find the right scan.</h1>
          <p>Search and manage de-identified CT studies across their lifecycle.</p>
        </div>
        <Link className="button-primary" href="/#dicom-upload">+ Upload CT</Link>
      </header>

      <section className="library-toolbar" aria-label="Filter studies">
        <label className="library-search">
          <span aria-hidden="true">⌕</span>
          <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search by study ID…" aria-label="Search by study ID" />
        </label>
        <label className="library-select-label">Status
          <select aria-label="Filter by status" value={status} onChange={(event) => setStatus(event.target.value as StatusFilter)}>
            <option value="all">All</option><option value="ready">Awaiting review</option><option value="uploaded">Uploaded</option><option value="processing">Processing</option><option value="failed">Failed</option>
          </select>
        </label>
        <label className="library-select-label">Modality
          <select aria-label="Filter by modality" value="CT" disabled><option value="CT">CT</option></select>
        </label>
        <button type="button" className="library-sort-button" onClick={() => void refresh()} disabled={loading || refreshing}>
          {refreshing ? "Refreshing…" : "Refresh list"}<span aria-hidden="true">↻</span>
        </button>
      </section>

      <section className="library-content" aria-label="Studies and selected study">
        <div className="library-results-card">
          <div className="library-results-heading"><span>ALL STUDIES</span><small>{loading ? "Loading" : `${filteredStudies.length} ${filteredStudies.length === 1 ? "result" : "results"}`}</small></div>
          {loading ? <LoadingSkeleton label="Loading studies…" /> : error ? (
            <ErrorState title="Study library unavailable" message={error} errorCode="ERR_RADAR_LIBRARY" onRetry={() => void refresh()} />
          ) : filteredStudies.length === 0 ? (
            <div className="library-empty">{studies.length === 0 ? "No studies have been uploaded yet." : "No studies match the current filters."}</div>
          ) : (
            <div className="library-table-wrap"><table className="library-table">
              <thead><tr><th>Study</th><th>Slices</th><th>Modality</th><th>State</th></tr></thead>
              <tbody>{filteredStudies.map((study) => (
                <tr key={study.study_id} className={selectedStudy?.study_id === study.study_id ? "selected" : ""}>
                  <td><button type="button" className="library-study-select" onClick={() => setSelectedStudyId(study.study_id)} aria-pressed={selectedStudy?.study_id === study.study_id}>CT-{study.study_id.slice(0, 8).toUpperCase()}<small>{study.study_id.slice(0, 8).toUpperCase()}</small></button></td>
                  <td>{String(study.slices.length).padStart(3, "0")}</td><td>{study.modality}</td>
                  <td><span className={`library-state status-${study.status}`}>{STATUS_LABELS[study.status]}</span></td>
                </tr>
              ))}</tbody>
            </table></div>
          )}
          {!loading && !error && filteredStudies.length > 0 && <p className="library-pagination">Showing 1–{filteredStudies.length} of {filteredStudies.length}</p>}
        </div>

        {selectedStudy && (
          <aside className="selected-study-card" aria-labelledby="selected-study-title">
            <p className="eyebrow">SELECTED STUDY</p>
            <h2 id="selected-study-title">CT-{selectedStudy.study_id.slice(0, 8).toUpperCase()}</h2>
            <p>{selectedStudy.modality} · Axial series</p>
            <dl>
              <div><dt>Slices</dt><dd>{selectedStudy.slices.length}</dd></div>
              <div><dt>Status</dt><dd>{STATUS_LABELS[selectedStudy.status]}</dd></div>
              <div><dt>Modality</dt><dd>{selectedStudy.modality}</dd></div>
            </dl>
            <small className="selected-study-disclaimer">Study identifiers are de-identified. Model outputs are experimental.</small>
            <Link className="selected-study-open" href={`/studies/${selectedStudy.study_id}`}>Open study <span aria-hidden="true">↗</span></Link>
          </aside>
        )}
      </section>

      <p className="library-footnote">Research demo / Study status is provided by the RADAR AI API. Not for clinical use.</p>
    </div>
  );
}
