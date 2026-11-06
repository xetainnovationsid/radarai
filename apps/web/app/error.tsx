"use client";

import { ErrorState } from "@/components/states/ErrorState";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <ErrorState
      title="Application Runtime Exception"
      message={
        error.message ||
        "An unexpected client or server rendering error occurred in the RADAR AI prototype interface."
      }
      errorCode={error.digest ? `ERR_NEXT_${error.digest}` : "ERR_RUNTIME_BOUNDARY"}
      onRetry={reset}
    />
  );
}
