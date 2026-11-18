"use client";

// The account page's colorectal surgeon membership section (H5 #127). Membership opens the forum; the API decides
// who has it, this section only shows the state and the application form.
import Link from "next/link";
import { useEffect, useState } from "react";
import { useAccount } from "@/components/account";
import {
  formProblem,
  loadMembership,
  submitApplication,
  withdrawApplication,
  type ApplicationForm,
  type Membership,
} from "@/lib/surgeons";

const EMPTY: ApplicationForm = {
  realName: "",
  hospital: "",
  certificateDigits: "",
};

const FIELDS: [keyof ApplicationForm, string, string][] = [
  ["realName", "真實姓名", "name"],
  ["hospital", "執業院所", "organization"],
  ["certificateDigits", "證書字號後三碼", "off"],
];

export function SurgeonMembership() {
  const account = useAccount();
  const signedIn = account.status === "signed-in" ? account : null;
  const token = signedIn?.token;
  const [membership, setMembership] = useState<Membership | null>(null);
  const [form, setForm] = useState<ApplicationForm>(EMPTY);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token || !signedIn?.displayName) return;
    let live = true;
    loadMembership(token).then((loaded) => {
      if (!live) return;
      if (loaded) setMembership(loaded);
      else setStatus("暫時無法載入會員狀態，請稍後再試。");
    });
    return () => {
      live = false;
    };
    // Load once per account; hourly token refreshes do not change the state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signedIn?.userId, signedIn?.displayName]);

  if (!signedIn?.displayName) return null;

  async function send(event: React.FormEvent) {
    event.preventDefault();
    if (!token) return;
    const problem = formProblem(form);
    if (problem) return setStatus(problem);
    setBusy(true);
    const result = await submitApplication(token, form);
    setBusy(false);
    setStatus(result.message);
    if (result.membership) {
      setMembership(result.membership);
      setForm(EMPTY);
    }
  }

  async function withdraw() {
    if (!token) return;
    setBusy(true);
    const ok = await withdrawApplication(token);
    setBusy(false);
    if (ok) setMembership({ status: "none", since: null });
    setStatus(ok ? "已撤回申請，填寫的資料已刪除。" : "撤回失敗，請稍後再試。");
  }

  return (
    <section className="surgeon" aria-labelledby="surgeon-title">
      <h2 id="surgeon-title">大腸直腸外科會員</h2>
      {membership?.status === "verified" && (
        <>
          <p>
            你是大腸直腸外科會員
            {membership.since && `（${membership.since.slice(0, 10)} 起）`}
            ，可以進入論壇。
          </p>
          <Link className="btn btn--primary" href="/">
            回首頁
          </Link>
        </>
      )}
      {membership?.status === "pending" && (
        <>
          <p>申請審核中。管理者核對後會開通，審核完成後填寫的資料會刪除。</p>
          <button
            className="btn btn--secondary"
            type="button"
            disabled={busy}
            onClick={withdraw}
          >
            撤回申請
          </button>
        </>
      )}
      {membership?.status === "none" && (
        <form className="surgeon__form" onSubmit={send} noValidate>
          <p className="note">
            論壇只開放大腸直腸外科專科醫師與受訓中的住院醫師、fellow。管理者會對照大腸直腸外科醫學會的專科醫師名單或衛福部醫事人員查詢，核對後開通。
            如果你在學會官網的「醫師地圖」上，而且這次是用醫院信箱收信登入，審核會比較快。
            不收身分證字號與任何文件；審核完成後，下面的資料就會刪除，只保留「已驗證」與時間。
          </p>
          {FIELDS.map(([key, label, autoComplete]) => (
            <label className="surgeon__field" key={key}>
              {label}
              <input
                name={key}
                autoComplete={autoComplete}
                inputMode={key === "certificateDigits" ? "numeric" : undefined}
                maxLength={key === "certificateDigits" ? 3 : 80}
                value={form[key]}
                onChange={(event) => {
                  setForm({ ...form, [key]: event.target.value });
                  setStatus("");
                }}
              />
            </label>
          ))}
          <button className="btn btn--primary" type="submit" disabled={busy}>
            送出申請
          </button>
        </form>
      )}
      <p role="status">{status}</p>
    </section>
  );
}
