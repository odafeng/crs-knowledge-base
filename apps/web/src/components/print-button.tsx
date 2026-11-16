"use client";

export function PrintButton() {
  return (
    <button
      className="btn btn--primary"
      type="button"
      onClick={() => window.print()}
    >
      列印或存成 PDF
    </button>
  );
}
