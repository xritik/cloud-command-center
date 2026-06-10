import { StrictMode, useState, useEffect } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import Auth from "./Auth.jsx";

function Root() {
  const [token, setToken]       = useState(() => localStorage.getItem("aqp_token") || "");
  const [username, setUsername] = useState(() => localStorage.getItem("aqp_user") || "");

  const handleLogin = (tok, user) => {
    localStorage.setItem("aqp_token", tok);
    localStorage.setItem("aqp_user", user);
    setToken(tok);
    setUsername(user);
  };

  const handleLogout = () => {
    localStorage.removeItem("aqp_token");
    localStorage.removeItem("aqp_user");
    setToken("");
    setUsername("");
  };

  if (!token) return <Auth onLogin={handleLogin} />;
  return <App token={token} username={username} onLogout={handleLogout} />;
}

createRoot(document.getElementById("root")).render(
  <StrictMode><Root /></StrictMode>
);
