import { describe, expect, it } from "vitest";
import { asciiDigits, formProblem, submitMessage } from "./surgeons";

const form = {
  realName: "王小明",
  hospital: "某醫學中心",
  department: "大腸直腸外科",
  certificateDigits: "042",
};

describe("surgeon application form", () => {
  it("turns full-width digits into the ASCII ones the API takes", () => {
    expect(asciiDigits("０４２")).toBe("042");
    expect(formProblem({ ...form, certificateDigits: "０４２" })).toBeNull();
  });

  it("names the first missing or malformed field", () => {
    expect(formProblem(form)).toBeNull();
    expect(formProblem({ ...form, realName: "  " })).toBe("請填寫真實姓名。");
    expect(formProblem({ ...form, certificateDigits: "42" })).toBe(
      "證書字號後三碼請填三個數字。",
    );
    expect(formProblem({ ...form, certificateDigits: "4a2" })).not.toBeNull();
  });

  it("explains each answer from the API", () => {
    expect(submitMessage(202, null)).toContain("已送出");
    expect(submitMessage(403, null)).toBe("請先設定顯示名稱。");
    expect(submitMessage(409, null)).toContain("已經是");
    expect(submitMessage(503, 600)).toContain("維護中");
    expect(submitMessage(null, null)).toContain("網路");
  });
});
