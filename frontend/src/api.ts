export function identityUrl(path: string) {
  const url = new URL(path, location.origin);
  url.searchParams.set(
    "user",
    new URLSearchParams(location.search).get("user") ?? "child",
  );
  return url.pathname + url.search;
}
export const base = "/api/groups/1";
export function clientId() {
  // getRandomValues also works on a LAN HTTP origin, unlike randomUUID.
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}
export async function api<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const r = await fetch(identityUrl(path), {
    ...options,
    headers:
      options.body instanceof FormData
        ? options.headers
        : { "Content-Type": "application/json", ...options.headers },
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: "服务暂时不可用" }));
    throw Object.assign(
      new Error(typeof d.detail === "string" ? d.detail : "请检查填写内容"),
      { status: r.status },
    );
  }
  return r.json();
}
export const post = (body: unknown) => ({
  method: "POST",
  body: JSON.stringify(body),
});
export const time = (t: number) =>
  new Date(t * 1000).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  });
