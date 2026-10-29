import React, { useState, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { Loader2, X } from "lucide-react";
import Chat from "./Chat";
import { api } from "./api";
import type { User } from "./types";
import "./style.css";
function App() {
  const [user, setUser] = useState<User | null>(null),
    [ready, setReady] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    const url = new URL(location.href);
    if (!url.searchParams.has("user")) {
      url.searchParams.set("user", "child");
      history.replaceState(null, "", url);
    }
    api<User>("/api/me")
      .then(setUser)
      .catch((e) => setError(e.message))
      .finally(() => setReady(true));
  }, []);
  if (!ready)
    return (
      <div className="loading">
        <Loader2 className="spin" /> 正在回家…
      </div>
    );
  return (
    <>
      {user ? (
        <Chat user={user} notify={setError} />
      ) : (
        <main className="loading">
          <div>
            <p>请选择家庭成员</p>
            <p>
              {[
                ["dad", "爸爸"],
                ["mom", "妈妈"],
                ["child", "小宇"],
              ].map(([id, name]) => (
                <a key={id} href={"/?user=" + id} style={{ marginRight: 16 }}>
                  {name}
                </a>
              ))}
            </p>
          </div>
        </main>
      )}{" "}
      {error && (
        <div className="toast" role="alert">
          {error}
          <button aria-label="关闭提示" onClick={() => setError("")}>
            <X size={17} />
          </button>
        </div>
      )}
    </>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
