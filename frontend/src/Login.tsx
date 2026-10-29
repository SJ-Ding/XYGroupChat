import React, { useState } from "react";
import { api, post } from "./api";

export default function Login() {
  const initial = new URLSearchParams(location.search).get("user");
  const [username, setUsername] = useState(
    ["dad", "mom", "child"].includes(initial || "") ? initial! : "child",
  );
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <section className="harness-login">
      <h2>登录个人空间</h2>
      <p>
        私人记忆、个人提醒和订阅需要密码登录。登录后，当前浏览器使用同一个成员身份。
      </p>
      <form
        className="settings-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            await api("/api/auth/login", post({ username, password }));
            location.reload();
          } catch (err) {
            setError((err as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          家庭成员
          <select
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          >
            <option value="dad">爸爸</option>
            <option value="mom">妈妈</option>
            <option value="child">小宇</option>
          </select>
        </label>
        <label>
          密码
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            maxLength={200}
          />
        </label>
        {error && <p role="alert">{error}</p>}
        <button className="primary" disabled={busy}>
          {busy ? "正在登录…" : "登录"}
        </button>
      </form>
      <p className="field-help">
        首次使用：由本机管理员运行 <code>python -m backend.auth dad</code>{" "}
        为对应成员设置密码。没有默认密码。
      </p>
    </section>
  );
}
