// Colorectal surgeon membership (H5 #127, ADR-0022). The application is checked by hand against the public registers;
// the API deletes its details once it is decided or withdrawn.
import { apiFetch } from "./auth";
import { retryAfterOf } from "./comments";

export type Membership = {
  status: "none" | "pending" | "verified";
  since: string | null;
};

export type ApplicationForm = {
  realName: string;
  hospital: string;
  department: string;
  certificateDigits: string;
};

/** Chinese input methods often type full-width digits; the form asks for the ASCII ones. */
export function asciiDigits(value: string): string {
  return value.replace(/[０-９]/g, (d) =>
    String.fromCharCode(d.charCodeAt(0) - 0xfee0),
  );
}

/** The first problem with the form, in words the applicant can act on, or null. */
export function formProblem(form: ApplicationForm): string | null {
  if (!form.realName.trim()) return "請填寫真實姓名。";
  if (!form.hospital.trim()) return "請填寫執業院所。";
  if (!form.department.trim()) return "請填寫科別。";
  if (!/^[0-9]{3}$/.test(asciiDigits(form.certificateDigits.trim())))
    return "證書字號後三碼請填三個數字。";
  return null;
}

export function submitMessage(
  status: number | null,
  retryAfter: number | null,
): string {
  switch (status) {
    case 202:
      return "已送出。管理者核對後會開通，通常在幾天內。";
    case 403:
      return "請先設定顯示名稱。";
    case 409:
      return "你已經是大腸直腸外科會員。";
    case 422:
      return "有欄位格式不符，請檢查後再送出。";
    case 503:
      return retryAfter
        ? "網站維護中，暫時無法送出，請稍後再試。"
        : "暫時無法送出，請稍後再試。";
    case null:
      return "送出失敗，請檢查網路後再試一次。";
    default:
      return "暫時無法送出，請稍後再試。";
  }
}

export async function loadMembership(
  token: string,
): Promise<Membership | null> {
  const response = await apiFetch("/me/surgeon", token).catch(() => null);
  return response?.ok ? ((await response.json()) as Membership) : null;
}

export async function submitApplication(
  token: string,
  form: ApplicationForm,
): Promise<{ message: string; membership: Membership | null }> {
  const body = {
    realName: form.realName.trim(),
    hospital: form.hospital.trim(),
    department: form.department.trim(),
    certificateDigits: asciiDigits(form.certificateDigits.trim()),
  };
  const response = await apiFetch("/me/surgeon", token, {
    method: "PUT",
    body: JSON.stringify(body),
  }).catch(() => null);
  return {
    message: submitMessage(response?.status ?? null, retryAfterOf(response)),
    membership:
      response?.status === 202 ? ((await response.json()) as Membership) : null,
  };
}

export async function withdrawApplication(token: string): Promise<boolean> {
  const response = await apiFetch("/me/surgeon", token, {
    method: "DELETE",
  }).catch(() => null);
  return response?.status === 204;
}
