"use client";

// An admin's buttons on an AI-unreviewed paper or story (E6 #159). The API decides who may use them
// (app.accounts.is_admin); everyone else never sees them. Unpublishing asks once more before sending.
import { useState } from "react";
import { useAccount } from "@/components/account";
import { apiFetch, authEnabled } from "@/lib/auth";
import { reviewMessage, type ReviewAction } from "@/lib/review";

type State =
  | { kind: "idle" | "confirm" | "sending" }
  | { kind: "done"; ok: boolean; message: string };

export function ReviewActions({
  kind,
  target,
}: {
  kind: "paper" | "news";
  target: string;
}) {
  const account = useAccount();
  const [state, setState] = useState<State>({ kind: "idle" });
  if (!authEnabled || account.status !== "signed-in" || !account.isAdmin)
    return null;
  const token = account.token;

  async function send(action: ReviewAction) {
    setState({ kind: "sending" });
    const response = await apiFetch("/admin/content-requests", token, {
      method: "POST",
      body: JSON.stringify({ action, kind, target }),
    }).catch(() => null);
    const started =
      response?.status === 202
        ? await response
            .json()
            .then((body: { started: boolean }) => body.started)
            .catch(() => false)
        : false;
    setState({
      kind: "done",
      ...reviewMessage(
        action,
        response?.status ?? null,
        started,
        response?.headers.get("Retry-After") ?? null,
      ),
    });
  }

  if (state.kind === "done")
    return (
      <p className="callout" role={state.ok ? "status" : "alert"}>
        {state.message}
      </p>
    );
  const busy = state.kind === "sending";
  return (
    <div className="review-actions" role="group" aria-label="管理者審閱">
      <button
        className="btn btn--primary"
        type="button"
        disabled={busy}
        onClick={() => send("review")}
      >
        標為已審
      </button>
      {state.kind === "confirm" ? (
        <button
          className="btn btn--secondary"
          type="button"
          onClick={() => send("unpublish")}
        >
          確定撤下
        </button>
      ) : (
        <button
          className="btn btn--secondary"
          type="button"
          disabled={busy}
          onClick={() => setState({ kind: "confirm" })}
        >
          撤下
        </button>
      )}
    </div>
  );
}
