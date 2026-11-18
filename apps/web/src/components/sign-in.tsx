"use client";

import type { EmailOtpType } from "@supabase/supabase-js";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { setDisplayName, signOut, useAccount } from "@/components/account";
import {
  AFTER_LOGIN_KEY,
  apiFetch,
  authEnabled,
  callbackError,
  displayNameError,
  googleEnabled,
  safeNext,
  supabase,
} from "@/lib/auth";
import { retryAfterOf } from "@/lib/comments";

function rememberNext() {
  const next = safeNext(new URLSearchParams(location.search).get("next"));
  try {
    localStorage.setItem(AFTER_LOGIN_KEY, next);
  } catch {
    // Storage blocked: the reader lands on the home page afterwards.
  }
}

function takeNext(): string {
  try {
    const next = safeNext(localStorage.getItem(AFTER_LOGIN_KEY));
    localStorage.removeItem(AFTER_LOGIN_KEY);
    return next;
  } catch {
    return "/";
  }
}

const NOT_CONFIGURED = <p>登入功能尚未開放。</p>;

export function LoginForm() {
  const account = useAccount();
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<
    | { kind: "idle" | "sending" }
    | { kind: "sent"; email: string }
    | { kind: "error"; message: string }
  >({ kind: "idle" });

  if (!authEnabled) return NOT_CONFIGURED;
  if (account.status === "signed-in") {
    return (
      <p>
        你已經登入。<Link href="/account/">前往帳號設定</Link>
      </p>
    );
  }

  async function sendLink(event: React.FormEvent) {
    event.preventDefault();
    setStatus({ kind: "sending" });
    rememberNext();
    const address = email.trim();
    const { error } = await supabase().auth.signInWithOtp({
      email: address,
      options: {
        emailRedirectTo: `${location.origin}/auth/callback/`,
        shouldCreateUser: true,
      },
    });
    if (!error) return setStatus({ kind: "sent", email: address });
    setStatus({
      kind: "error",
      message:
        error.status === 429
          ? "寄信太頻繁，請稍後再試。"
          : "無法寄出登入連結，請確認 Email 是否正確，或稍後再試。",
    });
  }

  async function google() {
    rememberNext();
    const { error } = await supabase().auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${location.origin}/auth/callback/` },
    });
    if (error)
      setStatus({ kind: "error", message: "無法連到 Google，請稍後再試。" });
  }

  return (
    <div className="sign-in">
      {googleEnabled && (
        <>
          <button className="btn btn--secondary" type="button" onClick={google}>
            使用 Google 帳號登入
          </button>
          <p className="sign-in__or">或</p>
        </>
      )}
      <form className="sign-in__form" onSubmit={sendLink}>
        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          name="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <button
          className="btn btn--primary"
          type="submit"
          disabled={status.kind === "sending"}
        >
          寄送登入連結
        </button>
      </form>
      <div aria-live="polite">
        {status.kind === "sent" && (
          <p className="callout">
            登入連結已寄到 {status.email}。連結 1
            小時內有效，在這台或其他裝置開啟都可以。
          </p>
        )}
        {status.kind === "error" && (
          <p className="callout" role="alert">
            {status.message}
          </p>
        )}
      </div>
      <p className="note">
        不需要密碼。第一次登入時會請你自訂公開顯示名稱，不會自動使用 Google
        姓名或 Email。Google 信箱和你用來收連結的 Email
        不同時，兩種登入會是兩個帳號；先用 Email 登入，再到帳號設定連結
        Google，之後就能直接用 Google 登入同一個帳號。登入即表示你已閱讀
        <Link href="/privacy/">隱私權政策</Link>。
      </p>
    </div>
  );
}

const EMAIL_TYPES = new Set<EmailOtpType>(["email", "magiclink", "signup"]);
// Strict Mode runs effects twice in development; a one-time link must be redeemed once.
let redeeming = false;

/** Finishes sign-in from the email link (token_hash) or an OAuth / default-template redirect (PKCE code). */
export function AuthCallback() {
  const router = useRouter();
  const [failed, setFailed] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (!authEnabled || redeeming) return;
    const params = new URLSearchParams(location.search);
    const reported = callbackError(location.search, location.hash);
    redeeming = !reported;
    // The token must not stay in the address bar, history or a later Referer.
    history.replaceState(null, "", "/auth/callback/");
    (async () => {
      if (reported) return setProblem(reported);
      const tokenHash = params.get("token_hash");
      const type = params.get("type") as EmailOtpType | null;
      const code = params.get("code");
      const { data, error } =
        tokenHash && type && EMAIL_TYPES.has(type)
          ? await supabase().auth.verifyOtp({ token_hash: tokenHash, type })
          : code
            ? await supabase().auth.exchangeCodeForSession(code)
            : { data: { session: null }, error: new Error("missing token") };
      redeeming = false;
      if (error || !data.session) return setFailed(true);
      const next = takeNext();
      const me = await apiFetch("/me", data.session.access_token)
        .then((response) => (response.ok ? response.json() : null))
        .catch(() => null);
      router.replace(
        me && me.displayName === null
          ? `/account/?welcome=1&next=${encodeURIComponent(next)}`
          : next,
      );
    })();
  }, [router]);

  if (!authEnabled) return NOT_CONFIGURED;
  // Supabase sent back an error (a Google link that failed); the reader's own session, if any, is untouched.
  if (problem) {
    return (
      <p role="alert">
        {problem}
        <Link href="/account/">回帳號設定</Link>
      </p>
    );
  }
  if (failed) {
    return (
      <p role="alert">
        這個登入連結無效或已過期。<Link href="/login/">重新寄送登入連結</Link>
      </p>
    );
  }
  return <p aria-live="polite">登入中…</p>;
}

export function AccountSettings() {
  const account = useAccount();
  const router = useRouter();
  const [name, setName] = useState<string | null>(null);
  const [status, setStatus] = useState<
    { kind: "idle" | "saving" | "saved" } | { kind: "error"; message: string }
  >({ kind: "idle" });

  if (!authEnabled) return NOT_CONFIGURED;
  if (account.status === "loading") return <p aria-live="polite">載入中…</p>;
  if (account.status === "unavailable") {
    return <p role="alert">目前無法連線到帳號服務，請稍後再試。</p>;
  }
  if (account.status === "signed-out") {
    return (
      <p>
        尚未登入。<Link href="/login/?next=%2Faccount%2F">登入</Link>
      </p>
    );
  }

  const value = name ?? account.displayName ?? "";
  const firstTime = account.displayName === null;
  const token = account.token;

  async function save(event: React.FormEvent) {
    event.preventDefault();
    const problem = displayNameError(value);
    if (problem) return setStatus({ kind: "error", message: problem });
    setStatus({ kind: "saving" });
    const response = await apiFetch("/me", token, {
      method: "PUT",
      body: JSON.stringify({ displayName: value.trim() }),
    }).catch(() => null);
    if (!response?.ok) {
      return setStatus({
        kind: "error",
        message:
          response?.status === 409
            ? "這個帳號已刪除，無法再設定名稱。"
            : response?.status === 503 && retryAfterOf(response)
              ? "網站維護中，暫時無法修改名稱，請稍後再試。"
              : "儲存失敗，請稍後再試。",
      });
    }
    const saved: { displayName: string } = await response.json();
    setDisplayName(saved.displayName);
    setName(null);
    setStatus({ kind: "saved" });
    const params = new URLSearchParams(location.search);
    if (params.has("welcome")) {
      const next = safeNext(params.get("next"));
      if (next !== "/account/") router.replace(next);
    }
  }

  async function leave() {
    await signOut();
    router.replace("/");
  }

  return (
    <div className="sign-in">
      {firstTime && (
        <p className="callout">
          歡迎！請先設定公開顯示名稱。署名留言會顯示這個名稱；也可以選擇匿名留言，其他讀者看不到你的名稱。
        </p>
      )}
      <form className="sign-in__form" onSubmit={save}>
        <label htmlFor="display-name">顯示名稱</label>
        <input
          id="display-name"
          name="displayName"
          autoComplete="nickname"
          value={value}
          aria-describedby="display-name-help"
          onChange={(event) => {
            setName(event.target.value);
            setStatus({ kind: "idle" });
          }}
        />
        <p id="display-name-help" className="note">
          1 到 80 個字，之後可以修改。已發出的署名留言保留發文當時的名稱。
        </p>
        <button
          className="btn btn--primary"
          type="submit"
          disabled={status.kind === "saving"}
        >
          儲存
        </button>
      </form>
      <div aria-live="polite">
        {status.kind === "saved" && <p className="callout">已儲存。</p>}
        {status.kind === "error" && (
          <p className="callout" role="alert">
            {status.message}
          </p>
        )}
      </div>
      {account.email && (
        <p className="note">登入帳號：{account.email}（不會公開）</p>
      )}
      {googleEnabled && <GoogleLink />}
      {account.isAdmin && (
        <p>
          <Link href="/admin/comments/">留言審核</Link>
          {"　"}
          <Link href="/admin/stats/">每週活動</Link>
        </p>
      )}
      <button className="btn btn--secondary" type="button" onClick={leave}>
        登出
      </button>
    </div>
  );
}

type Linked =
  { kind: "loading" | "error" } | { kind: "ready"; google: string | null };

/**
 * Links a Google account to this one (H12 #185), so signing in with Google opens the same account, membership and
 * all. Supabase keeps the Google identity on this user; nothing new reaches the GutHub API. Surgeon auto-approval
 * still counts only a mailed link: a linked Google account proves nothing about a hospital mailbox.
 */
function GoogleLink() {
  const [linked, setLinked] = useState<Linked>({ kind: "loading" });
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    supabase()
      .auth.getUserIdentities()
      .then(({ data, error }) => {
        if (error || !data) return setLinked({ kind: "error" });
        const google = data.identities.find((i) => i.provider === "google");
        setLinked({
          kind: "ready",
          google: google
            ? String(google.identity_data?.email ?? "已連結")
            : null,
        });
      });
  }, []);

  async function link() {
    setFailed(false);
    try {
      localStorage.setItem(AFTER_LOGIN_KEY, "/account/");
    } catch {
      // Storage blocked: the reader lands on the home page afterwards.
    }
    const { error } = await supabase().auth.linkIdentity({
      provider: "google",
      options: { redirectTo: `${location.origin}/auth/callback/` },
    });
    if (error) setFailed(true);
  }

  if (linked.kind !== "ready") return null;
  return (
    <section className="sign-in__link" aria-labelledby="google-link">
      <h2 id="google-link">Google 登入</h2>
      {linked.google ? (
        <p className="note">
          已連結 Google 帳號（{linked.google}），可以直接用 Google
          登入這個帳號。
        </p>
      ) : (
        <>
          <p className="note">
            連結後可以直接用 Google
            登入這個帳號，會員身分、留言與通知設定都沿用。
          </p>
          <button className="btn btn--secondary" type="button" onClick={link}>
            連結 Google 帳號
          </button>
        </>
      )}
      {failed && (
        <p className="callout" role="alert">
          無法連到 Google，請稍後再試。
        </p>
      )}
    </section>
  );
}
