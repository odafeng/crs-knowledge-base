import { revalidatePath, revalidateTag } from "next/cache";
import { handleRevalidate } from "@/lib/revalidate";

export async function POST(request: Request) {
  return handleRevalidate(request, { revalidateTag, revalidatePath });
}
