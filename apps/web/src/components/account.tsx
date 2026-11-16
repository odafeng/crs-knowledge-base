"use client";

// The reader's sign-in state, shared by the header and the account pages. It exists only in the browser: the server
// snapshot is always "loading", so every page renders the same HTML for everyone (ADR-0020).
import type { Session } from "@supabase/supabase-js";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";
import { Icon } from "@/components/reading";
import { apiFetch, authEnabled, returnPath, supabase } from "@/lib/auth";

export type Account =
  | { status: "loading" }
  | { status: "signed-out" }
  | { status: "unavailable" }
  | {
      status: "signed-in";
      userId: string;
      email: string | null;
      token: string;
      displayName: string | null;
      isAdmin: boolean;
    };

const LOADING: Account = { status: "loading" };
let state: Account = LOADING;
let started = false;
// Each sign-in/out bumps this, so a slow /me answer for the previous person is dropped instead of shown.
let generation = 0;
const listeners = new Set<() => void>();

function set(next: Account) {
  state = next;
  listeners.forEach((listener) => listener());
}

async function load(session: Session | null) {
  const mine = ++generation;
  if (!session) return set({ status: "signed-out" });
  set(LOADING);
  try {
    const response = await apiFetch("/me", session.access_token);
    if (mine !== generation) return;
    if (response.status === 401) {
      await supabase().auth.signOut({ scope: "local" });
      return;
    }
    if (!response.ok) throw new Error(`/me ${response.status}`);
    const me: { displayName: string | null; isAdmin: boolean } =
      await response.json();
    if (mine !== generation) return;
    set({
      status: "signed-in",
      userId: session.user.id,
      email: session.user.email ?? null,
      token: session.access_token,
      displayName: me.displayName,
      isAdmin: me.isAdmin,
    });
  } catch {
    if (mine === generation) set({ status: "unavailable" });
  }
}

function start() {
  if (started || !authEnabled) return;
  started = true;
  supabase().auth.onAuthStateChange((event, session) => {
    if (
      event === "TOKEN_REFRESHED" &&
      session &&
      state.status === "signed-in" &&
      state.userId === session.user.id
    ) {
      return set({ ...state, token: session.access_token });
    }
    // Supabase must not be called from inside this callback; defer the work.
    setTimeout(() => void load(session), 0);
  });
}

function subscribe(listener: () => void) {
  start();
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useAccount(): Account {
  return useSyncExternalStore(
    subscribe,
    () => state,
    () => LOADING,
  );
}

export function setDisplayName(displayName: string) {
  if (state.status === "signed-in") set({ ...state, displayName });
}

/** Signs out on this device only; the store resets through onAuthStateChange. */
export async function signOut() {
  await supabase().auth.signOut({ scope: "local" });
}

/** Header entry: "登入" for visitors, the account page once signed in. */
export function AccountLink() {
  const account = useAccount();
  const path = usePathname();
  if (!authEnabled) return null;
  if (account.status === "signed-in") {
    return (
      <Link
        className="btn btn--quiet btn--icon account-link account-link--signed-in"
        href="/account/"
        aria-label={`帳號：${account.displayName ?? "尚未設定顯示名稱"}`}
      >
        <Icon name="account" />
      </Link>
    );
  }
  return (
    <Link
      className="btn btn--quiet btn--icon account-link"
      href={`/login/?next=${encodeURIComponent(returnPath(path))}`}
      aria-label="登入"
    >
      <Icon name="account" />
    </Link>
  );
}
